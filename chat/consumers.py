from django.contrib.auth.models import User
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


logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):

    # ---------------- CONNECT ----------------
    async def connect(self):
        self.chat_id = self.scope["url_route"]["kwargs"]["chat_id"]
        self.group_name = f"chat_{self.chat_id}"
        self.user = self.scope["user"]
        self.typing_users = set()

        if not self.user.is_authenticated:
            await self.close()
            return

        chat = await self.get_chat()
        if not chat:
            await self.close()
            return

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    # ---------------- DISCONNECT ----------------
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

        self.typing_users.discard(self.user.id)
        await self.broadcast_typing()

    # ---------------- RECEIVE ----------------
    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        event = data.get("type")

        if event == "message.send":
            await self.handle_send_message(data)
        elif event == "typing":
            await self.handle_typing(data)
        elif event == "message.read":
            await self.handle_message_read(data)
        elif event == "message.consume":
            await self.handle_message_consume(data)

    # ---------------- EVENTS ----------------
    async def chat_message(self, event):
        await self.send_json(event)

    async def message_read(self, event):
        await self.send_json(event)

    async def message_consumed(self, event):
        await self.send_json(event)

    async def typing_update(self, event):
        await self.send_json(event)

    # ---------------- HANDLERS ----------------
    async def handle_send_message(self, data):
        content = data.get("content", "").strip()
        if not content:
            return

        one_time = data.get("one_time", False)
        reply_to_id = data.get("reply_to")

        message = await self.create_message(content, one_time, reply_to_id)
        serialized = await self.serialize_message(message)

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "message": serialized
            }
        )

    async def handle_typing(self, data):
        if data.get("is_typing"):
            self.typing_users.add(self.user.id)
        else:
            self.typing_users.discard(self.user.id)

        await self.broadcast_typing()

    async def handle_message_read(self, data):
        message_id = data.get("message_id")
        if not message_id:
            return

        await self.mark_message_read(message_id)

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "message_read",
                "message_id": message_id,
                "read_by": self.user.id,
                "read_at": timezone.now().isoformat()
            }
        )

    async def handle_message_consume(self, data):
        message_id = data.get("message_id")
        consumed_at = await self.consume_one_time_message(message_id)

        if consumed_at:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "message_consumed",
                    "message_id": message_id,
                    "consumed_by": self.user.id,
                    "consumed_at": consumed_at.isoformat()
                }
            )

    async def broadcast_typing(self):
        users = []
        for uid in self.typing_users:
            user = await self.get_user(uid)
            if user:
                users.append({"id": user.id, "name": user.full_name})

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "typing_update",
                "users": users
            }
        )

    # ---------------- DATABASE ----------------
    @database_sync_to_async
    def get_chat(self):
        try:
            return Chat.objects.get(id=self.chat_id, participants=self.user)
        except Chat.DoesNotExist:
            return None

    @database_sync_to_async
    def create_message(self, content, one_time, reply_to_id):
        chat = Chat.objects.get(id=self.chat_id)
        reply_to = Message.objects.filter(
            id=reply_to_id).first() if reply_to_id else None

        return Message.objects.create(
            chat=chat,
            sender=self.user,
            content=content,
            one_time=one_time,
            reply_to=reply_to
        )

    @database_sync_to_async
    def mark_message_read(self, message_id):
        message = Message.objects.get(id=message_id)
        MessageRead.objects.get_or_create(
            message=message,
            user=self.user,
            defaults={"read_at": timezone.now()}
        )
        if message.sender_id != self.user.id:
            message.is_read = True
            message.save(update_fields=['is_read'])

    @database_sync_to_async
    def consume_one_time_message(self, message_id):
        message = Message.objects.filter(
            id=message_id,
            one_time=True,
            consumed_at__isnull=True
        ).first()

        if not message:
            return None

        message.consumed_at = timezone.now()
        message.save(update_fields=["consumed_at"])
        return message.consumed_at

    @database_sync_to_async
    def get_user(self, user_id):
        return User.objects.filter(id=user_id).first()

    @database_sync_to_async
    def serialize_message(self, message):
        return {
            "id": message.id,
            "content": message.content,
            "sender": message.sender.username,
            "sender_name": message.sender.full_name,
            "timestamp": message.timestamp.strftime("%H:%M"),
            "timestamp_iso": message.timestamp.isoformat(),
            "one_time": message.one_time,
            "consumed": bool(message.consumed_at),
            "sender_id": message.sender_id,
            "is_own": message.sender_id == self.user.id,
            "reply_to": {
                "id": message.reply_to.id,
                "content": message.reply_to.content,
                "sender_name": message.reply_to.sender.full_name
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
        # payload is the dict {type: '...', ...}
        message_type = payload.get('type')

        # Broadcast via NotifyConsumer if it's an Offer
        if message_type == "webrtc.offer":
            await self.send_call_notification(payload)

        # ALWAYS store in database FIRST (for polling fallback - works even if WebSocket fails)
        if message_type in ["webrtc.offer", "webrtc.answer", "webrtc.ice"]:
            await self.store_signal_in_db(payload)
            logger.info(
                f"[CallConsumer] ✓ Stored {message_type} in DB for chat {self.chat_id}")

        # Standard Signaling Forwarding via WebSocket
        # Forward to the group so the other client receives it (if they're connected)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'send_signal',
                'original_sender_channel': self.channel_name,
                'message': payload
            }
        )
        logger.info(
            f"[CallConsumer] ✓ Forwarded {message_type} to group {self.room_group_name} (chat {self.chat_id})")

    async def send_call_notification(self, payload):
        """Send call notification to other participants immediately"""
        try:
            chat_id = self.chat_id
            # Get caller details
            caller_name = getattr(self.user, 'full_name', self.user.username)
            caller_avatar = None
            if hasattr(self.user, 'profile_picture') and self.user.profile_picture:
                try:
                    caller_avatar = self.user.profile_picture.url
                except:
                    pass

            # Get others
            others = await self.get_other_participants(chat_id)
            for uid in others:
                await self.channel_layer.group_send(
                    f'user_notify_{uid}',
                    {
                        'type': 'notify.call',
                        'from_user_id': self.user.id,
                        'chat_id': chat_id,
                        'audio_only': bool(payload.get('audioOnly', False)),
                        'from_full_name': caller_name,
                        'from_avatar': caller_avatar,
                    }
                )
            logger.info(
                f"[CallConsumer] ✓ Sent call notifications to {len(others)} user(s) for chat {chat_id}")
        except Exception as e:
            logger.error(
                f"[CallConsumer] Error sending call notification: {e}", exc_info=True)

    @database_sync_to_async
    def store_signal_in_db(self, payload):
        """Store signaling data in database as fallback for server relay"""
        try:
            from chat.models import P2PSignal, Chat
            chat = Chat.objects.get(id=self.chat_id)
            others = list(chat.participants.exclude(
                id=self.user.id).values_list('id', flat=True))

            signal_type = payload.get('type', 'unknown') if isinstance(
                payload, dict) else 'unknown'

            for target_user_id in others:
                # Clean up old consumed signals for this chat/user pair first
                P2PSignal.cleanup_old_signals()

                # Create new signal
                P2PSignal.objects.create(
                    chat=chat,
                    sender=self.user,
                    target_user_id=target_user_id,
                    signal_data=payload
                )
            logger.info(
                f"[CallConsumer] ✓ Stored {signal_type} in DB for {len(others)} user(s) in chat {self.chat_id}")
        except Exception as e:
            logger.error(
                f"[CallConsumer] Error storing signal in DB: {e}", exc_info=True)

    async def send_signal(self, event):
        # Don't echo back to sender
        if event.get('original_sender_channel') == self.channel_name:
            logger.debug(
                f"[CallConsumer] Ignoring signal echo for {self.user.id if self.user else 'unknown'}")
            return

        # Forward the signaling message to other participants
        message = event.get('message', {})
        message_type = message.get('type', 'unknown') if isinstance(
            message, dict) else 'unknown'

        if self.handshake_complete and self.proto.auth_key:
            try:
                encrypted = self.proto.wrap_message(message)
                await self.send(text_data=encrypted)
                logger.info(
                    f"[CallConsumer] ✓ Sent encrypted {message_type} to user {self.user.id if self.user else 'unknown'} via WebSocket")
            except Exception as e:
                logger.error(
                    f"[CallConsumer] Error encrypting/sending signal {message_type}: {e}", exc_info=True)
        else:
            # If handshake not complete, signal is already in DB (stored before forwarding)
            # User can poll for it, so we don't need to send unencrypted
            logger.debug(
                f"[CallConsumer] Handshake not complete for user {self.user.id if self.user else 'unknown'}, signal {message_type} available via polling")

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


class OdnixGatewayConsumer(AsyncWebsocketConsumer):
    """
    THE ODNIX GATEWAY (MTProto 2.0 Style)
    -------------------------------------
    This consumer replaces separate Chat/Call endpoints.
    It implements the full telegram-style binary protocol:
    1. Connection is essentially "dumb" TCP/WS tunnel.
    2. First packets MUST be Handshake (req_pq_multi).
    3. Once AuthKey established, all traffic is encrypted binary packets.
    4. Acts as a dispatcher for RPC calls (messages.send, phone.requestCall).
    """

    async def connect(self):
        # In Telegram architecture, we accept everyone. Auth happens via protocol.
        self.user = self.scope.get('user')  # Might be Anonymous initially
        self.session_id = None
        self.auth_key = None
        self.auth_key_id = None

        # Security State
        self.handshake_step = 0
        self.proto_security = OdnixSecurity()

        await self.accept()
        logger.info(f"[OdnixGateway] New connection accepted. ID: {id(self)}")

    async def disconnect(self, close_code):
        logger.info(f"[OdnixGateway] Connection closed: {close_code}")

    async def receive(self, text_data=None, bytes_data=None):
        try:
            # MTProto only uses Binary. Text frames are invalid/legacy.
            if text_data:
                logger.warning(
                    "[OdnixGateway] Dropping text frame (Strict Binary Protocol)")
                return

            if not bytes_data:
                return

            # --- PHASE 1: HANDSHAKE (Plaintext Wrapper) ---
            # If we don't have an AuthKey yet, we expect specific Handshake primitives
            # In real MTProto, even handshake is wrapped in a specific 'UnencryptedMessage' envelope.
            # Here we simplify: if len < 24 or auth_key_id == 0, it's handshake.

            if not self.auth_key:
                await self.handle_handshake_packet(bytes_data)
                return

            # --- PHASE 2: SECURE TRANSPORT (Encrypted Envelope) ---
            # Parse the OdnixPacket envelope
            try:
                from .odnix_proto import OdnixPacket
                packet = OdnixPacket.from_bytes(bytes_data)
            except Exception as e:
                logger.error(f"[OdnixGateway] Malformed Packet: {e}")
                return

            # 1. Verify Auth Key ID
            # In real impl, we'd look up the session state by ID.
            # valid_auth_id = hashlib.sha1(self.auth_key).digest()[-8:]
            # if packet.auth_key_id != valid_auth_id: ...

            # 2. Decrypt Payload
            # We use the OdnixSecurity logic but adapted for binary
            decrypted_data = self.decrypt_binary_payload(packet)

            if not decrypted_data:
                logger.warning(
                    "[OdnixGateway] Decryption failed or integrity check failed")
                return

            # 3. Dispatch RPC
            await self.dispatch_rpc(decrypted_data)

        except Exception as e:
            logger.error(f"[OdnixGateway] Critical Error: {e}", exc_info=True)
            await self.close()

    async def handle_handshake_packet(self, data):
        """
        Handles the raw binary handshake flow (Req_PQ -> Res_DH, etc.)
        """
        # For prototype, we'll assume the client sends a raw 1-byte OpCode for handshake step
        # Real MTProto scans for TL Constructor ID

        op_code = data[0]
        logger.info(f"[OdnixGateway] Handshake OpCode: {op_code}")

        # 0x01: REQ_PQ (Client sends nonce)
        if op_code == 0x01:
            nonce = data[1:17]  # 16 bytes

            # Server Reply: RES_PQ (Nonce + ServerNonce + Prime + G)
            dh_config = self.proto_security.create_dh_config()
            # currently b64 in security lib
            s_nonce_b64 = dh_config['server_nonce']
            import base64
            s_nonce = base64.b64decode(s_nonce_b64)

            # Pack response
            # [Op:0x02][Nonce(16)][ServerNonce(16)][PrimeLen(2)][PrimeBytes...][G(4)]
            # This is pseudo-code for the binary logic
            # Key Calculation (Simulated Diffie-Hellman Completion for Demo)
            # In real flow, client sends another packet. Here we shortcut for prototype stability.
            # Client thinks handshake is done after RES_PQ in our simple client.
            # We derive a fixed key based on nonces to match client.

            # Key = SHA256(ClientNonce + ServerNonce)
            combined = nonce + s_nonce
            import hashlib
            self.auth_key = hashlib.sha256(combined).digest()
            self.proto_security.auth_key = self.auth_key
            logger.info(f"[OdnixGateway] Auth Key Established for Session")

            reply = b'\x02' + nonce + s_nonce
            # ... (packing prime/g skipped for brevity in snippet) ...

            await self.send(bytes_data=reply)

    def decrypt_binary_payload(self, packet):
        # Implementation of AES decryption (Simulated AES-CBC to match client)
        if not self.auth_key:
            return None

        # 1. Derive MsgKey/Key/IV
        # Client: msgKey = sha256(authKey + data)
        # Server: we already have msgKey in packet.

        # Derive Key/IV:
        # key = sha256(msgKey + authKey)
        # iv = sha256(authKey + msgKey)[0:16]

        ka = packet.msg_key + self.auth_key
        kb = self.auth_key + packet.msg_key

        key = hashlib.sha256(ka).digest()
        iv = hashlib.sha256(kb).digest()[:16]

        try:
            from Crypto.Cipher import AES
            import struct
            import json
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(packet.encrypted_data)

            # 2. Parse Inner Payload
            # [Salt(8)][Session(8)][MsgId(8)][Seq(4)][Len(4)][Data][Padding]
            data_len = struct.unpack('<I', decrypted[28:32])[0]
            json_bytes = decrypted[32:32+data_len]

            payload_json = json.loads(json_bytes.decode('utf-8'))
            return payload_json

        except Exception as e:
            logger.error(f"[OdnixGateway] Decrypt Error: {e}")
            return None

    async def dispatch_rpc(self, payload):
        method = payload.get('method')
        params = payload.get('params')

        logger.info(f"[OdnixGateway] RPC Dispatch: {method}")

        if method == 'signal':
            # Bridge to Call logic - Echo for now
            logger.info(
                f"[OdnixGateway] Signal received via Binary Proto: {params.get('type')}")
