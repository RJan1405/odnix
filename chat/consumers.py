import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import Chat, Message, MessageRead
from django.utils import timezone
from .odnix_security import OdnixSecurity, DH_PRIME, DH_G

logger = logging.getLogger(__name__)
User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.chat_id = self.scope['url_route']['kwargs']['chat_id']
        self.chat_group_name = f'chat_{self.chat_id}'
        self.user = self.scope['user']
        self.typing_users = set()

        # Odnix Security Context
        self.proto = OdnixSecurity()
        self.handshake_complete = False

        if not self.user.is_authenticated:
            await self.close()
            return

        try:
            chat = await self.get_chat(self.chat_id)
            if not chat:
                await self.close()
                return
        except Exception as e:
            logger.error(f"Error checking chat membership: {e}")
            await self.close()
            return

        await self.channel_layer.group_add(
            self.chat_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.chat_group_name,
            self.channel_name
        )
        if self.user.id in self.typing_users:
            self.typing_users.remove(self.user.id)
            await self.broadcast_typing_update()

    async def receive(self, text_data):
        try:
            # Attempt to parse as standard JSON first for Handshake
            try:
                data = json.loads(text_data)
                is_json = True
            except json.JSONDecodeError:
                is_json = False

            if is_json and data.get('type') == 'req_dh_params':
                # Step 1: Client requests DH params
                # Generate Server DH Params
                dh_config = self.proto.create_dh_config()
                response = {
                    'type': 'res_dh_params',
                    'data': dh_config
                }
                await self.send(text_data=json.dumps(response))
                return

            if is_json and data.get('type') == 'set_client_dh_params':
                # Step 2: Client sends their Public Key
                client_pub = int(data.get('pub_key'), 16)

                # Generate server ephemeral private/public
                from Crypto.Util import number
                self.server_dh_private = number.getRandomRange(
                    1, int(self.proto.create_dh_config()['prime']) - 1)
                dh_prime = int(self.proto.create_dh_config()['prime'])
                dh_g = self.proto.create_dh_config()['g']
                server_pub = pow(dh_g, self.server_dh_private, dh_prime)

                self.proto.compute_shared_key(
                    client_pub, self.server_dh_private)
                self.handshake_complete = True

                await self.send(text_data=json.dumps({
                    'type': 'dh_gen_ok',
                    'server_pub': hex(server_pub)[2:]
                }))
                return

            # If Handshake complete, expect Encrypted Packet
            if self.handshake_complete:
                decrypted_payload = self.proto.unwrap_message(text_data)
                if not decrypted_payload:
                    logger.warning(
                        "Failed to decrypt message or invalid format")
                    return

                await self.handle_decrypted_event(decrypted_payload)

            else:
                # If not handshake and not complete, generic error
                if is_json:
                    # Maybe it's a legacy client?
                    pass
                # For now, strict mode:
                await self.send(text_data=json.dumps({'type': 'error', 'message': 'Encryption Handshake Required'}))

        except Exception as e:
            logger.error(f"Error in receive: {e}")

    async def handle_decrypted_event(self, data):
        event_type = data.get('type')

        if event_type == 'message.send':
            await self.handle_send_message(data)
        elif event_type == 'typing':
            await self.handle_typing(data)
        elif event_type == 'message.read':
            await self.handle_message_read(data)
        elif event_type == 'message.consume':
            await self.handle_message_consume(data)

    async def send_encrypted(self, data):
        if self.handshake_complete and self.proto and hasattr(self.proto, 'wrap_message'):
            encrypted_b64 = self.proto.wrap_message(data)
            await self.send(text_data=encrypted_b64)
        else:
            # Cannot send encrypted without completed handshake
            logger.warning(
                f"Cannot send encrypted: handshake_complete={self.handshake_complete}")
            pass

    # Wrappers for Group sends (which trigger self.send)
    async def message_new(self, event):
        await self.send_encrypted(event)

    async def message_read(self, event):
        await self.send_encrypted(event)

    async def message_consumed(self, event):
        await self.send_encrypted(event)

    async def typing_update(self, event):
        await self.send_encrypted(event)

    # ... [Keep existing logic for DB operations] ...
    async def handle_send_message(self, data):
        content = data.get('content', '').strip()
        one_time = data.get('one_time', False)
        reply_to_id = data.get('reply_to')

        if not content:
            await self.send_encrypted({'type': 'error', 'message': 'Message cannot be empty'})
            return

        try:
            message = await self.create_message(content, one_time, reply_to_id)
            if message:
                await self.channel_layer.group_send(
                    self.chat_group_name,  # Changed from room_group_name to chat_group_name
                    {
                        'type': 'message.new',
                        'message': await self.serialize_message(message)
                    }
                )
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            await self.send_encrypted({'type': 'error', 'message': 'Failed to send message'})

    async def handle_typing(self, data):
        is_typing = data.get('is_typing', False)
        if is_typing:
            self.typing_users.add(self.user.id)
        else:
            self.typing_users.discard(self.user.id)
        await self.broadcast_typing_update()

    async def handle_message_read(self, data):
        message_id = data.get('message_id')
        if not message_id:
            return
        try:
            await self.mark_message_read(message_id)
            await self.channel_layer.group_send(
                self.chat_group_name,  # Changed from room_group_name to chat_group_name
                {
                    'type': 'message.read',
                    'message_id': message_id,
                    'read_by': self.user.id,
                    'read_at': timezone.now().isoformat()
                }
            )
        except Exception as e:
            logger.error(f"Error marking message read: {e}")

    async def handle_message_consume(self, data):
        message_id = data.get('message_id')
        if not message_id:
            return
        try:
            consumed_at = await self.consume_one_time_message(message_id)
            if consumed_at:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'message.consumed',
                        'message_id': message_id,
                        'consumed_by': self.user.id,
                        'consumed_at': consumed_at.isoformat()
                    }
                )
        except Exception as e:
            logger.error(f"Error consuming message: {e}")

    async def broadcast_typing_update(self):
        typing_users_data = []
        for user_id in self.typing_users:
            try:
                user = await self.get_user(user_id)
                if user:
                    typing_users_data.append(
                        {'id': user.id, 'name': user.full_name})
            except:
                pass
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing.update',
                'users': typing_users_data
            }
        )

    # Database methods
    @database_sync_to_async
    def get_chat(self, chat_id):
        try:
            return Chat.objects.get(id=chat_id, participants=self.user)
        except Chat.DoesNotExist:
            return None

    @database_sync_to_async
    def create_message(self, content, one_time, reply_to_id):
        chat = Chat.objects.get(id=self.chat_id, participants=self.user)
        reply_to = None
        if reply_to_id:
            try:
                reply_to = Message.objects.get(id=reply_to_id, chat=chat)
            except Message.DoesNotExist:
                pass
        return Message.objects.create(
            chat=chat, sender=self.user, content=content, one_time=one_time, reply_to=reply_to
        )

    @database_sync_to_async
    def mark_message_read(self, message_id):
        message = Message.objects.get(id=message_id, chat_id=self.chat_id)
        MessageRead.objects.get_or_create(
            message=message, user=self.user, defaults={
                'read_at': timezone.now()}
        )

    @database_sync_to_async
    def consume_one_time_message(self, message_id):
        message = Message.objects.get(
            id=message_id, chat_id=self.chat_id, one_time=True)
        if hasattr(message, 'consumed_at') and message.consumed_at:
            return None
        message.consumed_at = timezone.now()
        message.save(update_fields=['consumed_at'])
        return message.consumed_at

    @database_sync_to_async
    def get_user(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

    @database_sync_to_async
    def serialize_message(self, message):
        return {
            'id': message.id,
            'content': message.content,
            'sender': message.sender.username,
            'sender_name': message.sender.full_name,
            'timestamp': message.timestamp.strftime('%H:%M'),
            'timestamp_iso': message.timestamp.isoformat(),
            'message_type': message.message_type,
            'one_time': message.one_time,
            'consumed': hasattr(message, 'consumed_at') and message.consumed_at is not None,
            'is_own': message.sender == self.user,
            'reply_to': {
                'id': message.reply_to.id if message.reply_to else None,
                'content': message.reply_to.content if message.reply_to else None,
                'sender_name': message.reply_to.sender.full_name if message.reply_to else None,
            } if message.reply_to else None
        }


class CallConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            self.chat_id = self.scope['url_route']['kwargs']['chat_id']
            self.room_group_name = f'call_{self.chat_id}'
            self.user = self.scope.get('user')

            logger.info(
                f"[CallConsumer] Connect attempt - chat_id={self.chat_id}, user={self.user.id if self.user and hasattr(self.user, 'is_authenticated') and self.user.is_authenticated else 'anonymous'}")

            self.proto = OdnixSecurity()
            self.handshake_complete = False

            # Accept connection for now - we'll validate auth if needed
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            await self.accept()
            logger.info(
                f"[CallConsumer] WebSocket accepted for user {self.user.id if self.user and hasattr(self.user, 'is_authenticated') and self.user.is_authenticated else 'unauthenticated'}")
        except Exception as e:
            logger.error(
                f"[CallConsumer] Error in connect: {e}", exc_info=True)
            try:
                await self.close()
            except:
                pass

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            try:
                # Attempt JSON parse for Handshake
                try:
                    data = json.loads(text_data)
                    is_json = True
                except json.JSONDecodeError:
                    is_json = False
                    logger.warning(
                        f"[CallConsumer] Failed to parse JSON: {text_data[:100]}")

                # --- Handshake Step 1: Request DH Params ---
                if is_json and data.get('type') == 'req_dh_params':
                    try:
                        logger.info(
                            f"[CallConsumer] Received req_dh_params from user {self.user.id if self.user else 'unknown'}")
                        client_nonce = data.get('nonce') or []

                        # Generate Server Params
                        dh_config = self.proto.create_dh_config()
                        logger.info(
                            f"[CallConsumer] DH config created, prime length: {len(str(dh_config['prime']))}")

                        import base64
                        server_nonce_b64 = dh_config.get('server_nonce')
                        server_nonce_bytes = base64.b64decode(
                            server_nonce_b64) if server_nonce_b64 else b''

                        response = {
                            'type': 'res_dh_params',
                            'nonce': client_nonce,
                            'server_nonce': list(server_nonce_bytes),
                            # Ensure it's a string for JSON
                            'p': str(dh_config['prime']),
                            'g': int(dh_config['g']),  # Ensure it's an integer
                        }
                        response_json = json.dumps(response)
                        logger.info(
                            f"[CallConsumer] Sending res_dh_params (size: {len(response_json)} bytes)")
                        logger.debug(
                            f"[CallConsumer] Response preview: {response_json[:200]}...")
                        await self.send(text_data=response_json)
                        logger.info(
                            f"[CallConsumer] res_dh_params sent successfully")
                        return
                    except Exception as e:
                        logger.error(
                            f"[CallConsumer] Error handling req_dh_params: {e}", exc_info=True)
                        try:
                            error_response = json.dumps({
                                'type': 'error',
                                'message': f'Handshake error: {str(e)}'
                            })
                            await self.send(text_data=error_response)
                            logger.info(
                                f"[CallConsumer] Sent error response to client")
                        except Exception as send_err:
                            logger.error(
                                f"[CallConsumer] Failed to send error response: {send_err}")
                        return

                # --- Handshake Step 2: Set Client DH Params ---
                if is_json and data.get('type') == 'set_client_dh_params':
                    try:
                        logger.info(
                            f"[CallConsumer] Received set_client_dh_params from user {self.user.id}")
                        # Client sends: type, nonce, server_nonce, gb (hex string)
                        client_pub_hex = data.get('gb')

                        if not client_pub_hex:
                            raise ValueError(
                                "Missing 'gb' (client public key) in set_client_dh_params")

                        from Crypto.Util import number
                        # Re-derive Prime/G
                        prime = DH_PRIME
                        g = DH_G

                        # Generate Server Private
                        server_priv = number.getRandomRange(1, prime - 1)
                        # Generate Server Public (ga)
                        server_pub = pow(g, server_priv, prime)

                        # Compute Shared Secret: client_pub ^ server_priv % p
                        client_pub = int(client_pub_hex, 16)
                        shared_secret = pow(client_pub, server_priv, prime)

                        # Derive auth key (sha256 of shared secret bytes)
                        import hashlib
                        secret_bytes = number.long_to_bytes(shared_secret)
                        self.proto.auth_key = hashlib.sha256(
                            secret_bytes).digest()
                        self.handshake_complete = True

                        logger.info(
                            f"[CallConsumer] Handshake complete, shared key established")

                        # Send OK with Server Public Key
                        response = {
                            'type': 'dh_gen_ok',
                            'nonce': data.get('nonce'),
                            'server_nonce': data.get('server_nonce'),
                            'ga': hex(server_pub)[2:]
                        }
                        logger.info(f"[CallConsumer] Sending dh_gen_ok")
                        await self.send(text_data=json.dumps(response))
                        logger.info(
                            f"[CallConsumer] dh_gen_ok sent successfully")
                        return
                    except Exception as e:
                        logger.error(
                            f"[CallConsumer] Error handling set_client_dh_params: {e}", exc_info=True)
                        await self.send(text_data=json.dumps({
                            'type': 'error',
                            'message': f'Handshake error at step 2: {str(e)}'
                        }))
                        return

                # --- Encrypted Messages ---
                if self.handshake_complete and self.proto.auth_key:
                    # If we have a key, try to decrypt
                    try:
                        decrypted = self.proto.unwrap_message(text_data)
                        if decrypted:
                            logger.debug(
                                f"[CallConsumer] Decrypted message type: {decrypted.get('type')}")
                            # Handle signaling
                            await self.handle_decrypted_signal(decrypted)
                        else:
                            logger.warning(
                                f"[CallConsumer] Decryption returned None")
                    except Exception as e:
                        logger.error(
                            f"[CallConsumer] Error decrypting message: {e}", exc_info=True)
                else:
                    if is_json:
                        logger.warning(
                            f"[CallConsumer] Received JSON '{data.get('type')}' but handshake not complete (auth_key={bool(self.proto.auth_key)})")
                    else:
                        logger.warning(
                            f"[CallConsumer] Received non-JSON data and handshake not complete")

            except Exception as e:
                logger.error(
                    f"[CallConsumer] Unexpected error in receive: {e}", exc_info=True)

    async def handle_decrypted_signal(self, payload):
        """
        Handle decrypted WebRTC signaling messages
        Strategy: P2P First, Server Relay as Fallback
        1. Store signal in DB (for polling fallback)
        2. Forward via WebSocket (for real-time P2P)
        3. Send call notification for offers
        """
        message_type = payload.get('type')
        logger.info(
            f"[CallConsumer] Processing signal: {message_type} from user {self.user.id} in chat {self.chat_id}")

        # STEP 1: Store in database FIRST (ensures fallback works even if WebSocket fails)
        if message_type in ["webrtc.offer", "webrtc.answer", "webrtc.ice", "webrtc.end"]:
            try:
                await self.store_signal_in_db(payload)
                logger.info(
                    f"[CallConsumer] ✓ Stored {message_type} in DB for polling fallback")
            except Exception as e:
                logger.error(
                    f"[CallConsumer] Failed to store signal in DB: {e}")

        # STEP 2: Forward via WebSocket for real-time P2P (if recipient is connected)
        try:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'send_signal',
                    'original_sender_channel': self.channel_name,
                    'message': payload
                }
            )
            logger.info(
                f"[CallConsumer] ✓ Forwarded {message_type} to group {self.room_group_name}")
        except Exception as e:
            logger.error(
                f"[CallConsumer] Failed to forward signal via WebSocket: {e}")

        # STEP 3: Send call notification for offers (ringing banner)
        if message_type == "webrtc.offer":
            try:
                await self.send_call_notification(payload)
                logger.info(
                    f"[CallConsumer] ✓ Sent call notification for offer")
            except Exception as e:
                logger.error(
                    f"[CallConsumer] Failed to send call notification: {e}")

    async def send_call_notification(self, payload):
        """
        Send call notification to other participants immediately
        This creates the ringing UI banner for incoming calls
        """
        try:
            chat_id = self.chat_id

            # Get caller details
            caller_name = getattr(self.user, 'full_name',
                                  self.user.username) if self.user else 'Unknown'
            caller_avatar = None
            if self.user and hasattr(self.user, 'profile_picture') and self.user.profile_picture:
                try:
                    caller_avatar = self.user.profile_picture.url
                except:
                    pass

            # Get other participants
            others = await self.get_other_participants(chat_id)

            # Send notification to each participant
            notification_count = 0
            for uid in others:
                try:
                    await self.channel_layer.group_send(
                        f'user_notify_{uid}',
                        {
                            'type': 'notify.call',
                            'from_user_id': self.user.id if self.user else None,
                            'chat_id': chat_id,
                            'audio_only': bool(payload.get('audioOnly', False)),
                            'from_full_name': caller_name,
                            'from_avatar': caller_avatar,
                        }
                    )
                    notification_count += 1
                except Exception as e:
                    logger.error(
                        f"[CallConsumer] Failed to send notification to user {uid}: {e}")

            logger.info(
                f"[CallConsumer] ✓ Sent call notifications to {notification_count}/{len(others)} user(s) for chat {chat_id}")
        except Exception as e:
            logger.error(
                f"[CallConsumer] Error sending call notification: {e}", exc_info=True)

    @database_sync_to_async
    def store_signal_in_db(self, payload):
        """
        Store signaling data in database for server relay fallback
        This ensures signals are delivered even if WebSocket connection fails
        """
        try:
            from chat.models import P2PSignal, Chat
            chat = Chat.objects.get(id=self.chat_id)

            # Get all participants except sender
            others = list(chat.participants.exclude(
                id=self.user.id).values_list('id', flat=True))

            signal_type = payload.get('type', 'unknown') if isinstance(
                payload, dict) else 'unknown'

            # Clean up old signals first (older than 5 minutes)
            P2PSignal.cleanup_old_signals()

            # Create signal for each recipient
            created_count = 0
            for target_user_id in others:
                try:
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    target_user = User.objects.get(id=target_user_id)

                    P2PSignal.objects.create(
                        chat=chat,
                        sender=self.user,
                        target_user=target_user,  # Fixed: use target_user instead of target_user_id
                        signal_data=payload
                    )
                    created_count += 1
                except Exception as e:
                    logger.error(
                        f"[CallConsumer] Error creating signal for user {target_user_id}: {e}")

            logger.info(
                f"[CallConsumer] ✓ Stored {signal_type} for {created_count} user(s) in chat {self.chat_id}")
        except Exception as e:
            logger.error(
                f"[CallConsumer] Error storing signal in DB: {e}", exc_info=True)

    async def send_signal(self, event):
        """
        Forward signaling messages to connected clients via WebSocket
        This provides real-time P2P signaling when both peers are online
        """
        # Don't echo back to sender
        if event.get('original_sender_channel') == self.channel_name:
            logger.debug(
                f"[CallConsumer] Skipping echo to sender {self.user.id if self.user else 'unknown'}")
            return

        message = event.get('message', {})
        message_type = message.get('type', 'unknown') if isinstance(
            message, dict) else 'unknown'

        # Only send if handshake is complete (encryption ready)
        if self.handshake_complete and self.proto.auth_key:
            try:
                encrypted = self.proto.wrap_message(message)
                await self.send(text_data=encrypted)
                logger.info(
                    f"[CallConsumer] ✓ Sent encrypted {message_type} to user {self.user.id if self.user else 'unknown'}")
            except Exception as e:
                logger.error(
                    f"[CallConsumer] Error sending signal {message_type}: {e}", exc_info=True)
        else:
            # Client will poll for signals from DB if WebSocket handshake not complete
            logger.debug(
                f"[CallConsumer] Handshake not complete for user {self.user.id if self.user else 'unknown'}, signal {message_type} available via DB polling")

    async def signal_forward(self, event):
        if event.get('from_user_id') == self.user.id:
            return
        await self.send_encrypted({
            'type': event['event_type'],
            'from_user_id': event['from_user_id'],
            'payload': event['payload'],
        })

    async def send_encrypted(self, data):
        if self.handshake_complete:
            await self.send(text_data=self.proto.wrap_message(data))

    @database_sync_to_async
    def get_chat(self, chat_id):
        try:
            return Chat.objects.get(id=chat_id, participants=self.user)
        except Chat.DoesNotExist:
            return None

    @database_sync_to_async
    def get_other_participants(self, chat_id):
        try:
            chat = Chat.objects.get(id=chat_id)
            return list(chat.participants.exclude(id=self.user.id).values_list('id', flat=True))
        except Chat.DoesNotExist:
            return []


class NotifyConsumer(AsyncWebsocketConsumer):
    # NotifyConsumer remains standard WebSocket for simplicity as it's just 'ringing'
    # and establishing context before the actual secured Call connection is made.

    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return
        self.group_name = f'user_notify_{self.user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        return

    async def notify_call(self, event):
        await self.send(text_data=json.dumps({
            'type': 'incoming.call',
            'from_user_id': event.get('from_user_id'),
            'chat_id': event.get('chat_id'),
            'audioOnly': event.get('audio_only', False),
            'from_full_name': event.get('from_full_name'),
            'from_avatar': event.get('from_avatar'),
        }))
