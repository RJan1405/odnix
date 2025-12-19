import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import Chat, Message, MessageRead
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.chat_id = self.scope['url_route']['kwargs']['chat_id']
        self.chat_group_name = f'chat_{self.chat_id}'
        self.user = self.scope['user']
        self.typing_users = set()

        # Check if user is authenticated and member of chat
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

        # Join chat group
        await self.channel_layer.group_add(
            self.chat_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave chat group
        await self.channel_layer.group_discard(
            self.chat_group_name,
            self.channel_name
        )

        # Remove from typing users if typing
        if self.user.id in self.typing_users:
            self.typing_users.remove(self.user.id)
            await self.broadcast_typing_update()

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            event_type = data.get('type')

            if event_type == 'message.send':
                await self.handle_send_message(data)
            elif event_type == 'typing':
                await self.handle_typing(data)
            elif event_type == 'message.read':
                await self.handle_message_read(data)
            elif event_type == 'message.consume':
                await self.handle_message_consume(data)

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON'
            }))
        except Exception as e:
            logger.error(f"Error in receive: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Internal server error'
            }))

    async def handle_send_message(self, data):
        content = data.get('content', '').strip()
        one_time = data.get('one_time', False)
        reply_to_id = data.get('reply_to')

        if not content:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Message cannot be empty'
            }))
            return

        try:
            message = await self.create_message(content, one_time, reply_to_id)
            if message:
                # Broadcast new message
                await self.channel_layer.group_send(
                    self.chat_group_name,
                    {
                        'type': 'message.new',
                        'message': await self.serialize_message(message)
                    }
                )
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Failed to send message'
            }))

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
            # Broadcast read receipt
            await self.channel_layer.group_send(
                self.chat_group_name,
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
                # Broadcast consumption
                await self.channel_layer.group_send(
                    self.chat_group_name,
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
                    typing_users_data.append({
                        'id': user.id,
                        'name': user.full_name
                    })
            except:
                pass

        await self.channel_layer.group_send(
            self.chat_group_name,
            {
                'type': 'typing.update',
                'users': typing_users_data
            }
        )

    # Event handlers for group messages
    async def message_new(self, event):
        await self.send(text_data=json.dumps(event))

    async def message_read(self, event):
        await self.send(text_data=json.dumps(event))

    async def message_consumed(self, event):
        await self.send(text_data=json.dumps(event))

    async def message_reaction(self, event):
        await self.send(text_data=json.dumps(event))

    async def typing_update(self, event):
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def get_chat(self, chat_id):
        try:
            chat = Chat.objects.get(id=chat_id, participants=self.user)
            return chat
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

        message = Message.objects.create(
            chat=chat,
            sender=self.user,
            content=content,
            one_time=one_time,
            reply_to=reply_to
        )
        return message

    @database_sync_to_async
    def mark_message_read(self, message_id):
        message = Message.objects.get(id=message_id, chat_id=self.chat_id)
        # Only mark read if not already read by this user
        MessageRead.objects.get_or_create(
            message=message,
            user=self.user,
            defaults={'read_at': timezone.now()}
        )

    @database_sync_to_async
    def consume_one_time_message(self, message_id):
        message = Message.objects.get(
            id=message_id, chat_id=self.chat_id, one_time=True)
        # Check if already consumed
        if hasattr(message, 'consumed_at') and message.consumed_at:
            return None
        # Mark as consumed
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
        self.chat_id = self.scope['url_route']['kwargs']['chat_id']
        self.group_name = f'call_{self.chat_id}'
        self.user = self.scope['user']

        if not self.user.is_authenticated:
            await self.close()
            return

        chat = await self.get_chat(self.chat_id)
        if not chat:
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = data.get('type')
        payload = data.get('payload', {})

        # Forward signaling messages to other peers in the chat
        if msg_type in {"webrtc.offer", "webrtc.answer", "webrtc.ice", "webrtc.end", "webrtc.ringing"}:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'signal.forward',
                    'from_user_id': self.user.id,
                    'event_type': msg_type,
                    'payload': payload,
                }
            )

            # Also send a global notification for incoming offers so callee can be notified anywhere
            if msg_type == "webrtc.offer":
                # Determine other participants in private chat and notify them
                chat = await self.get_chat(self.chat_id)
                if chat:
                    if chat.chat_type == 'private':
                        others = await self.get_other_participants(chat.id)
                        # Deduplicate just in case
                        others = list(set(others))
                        logger.info(f"Call offer in chat {self.chat_id}. Notifying {len(others)} others: {others}")
                        
                        caller_name = getattr(self.user, 'full_name', None) or getattr(
                            self.user, 'username', 'Someone')
                        try:
                            caller_avatar = getattr(
                                self.user, 'profile_picture_url', None)
                        except Exception as e:
                            logger.error(f"Error getting avatar: {e}")
                            caller_avatar = None
                            
                        for uid in others:
                            logger.info(f"Sending notify.call to user_notify_{uid}")
                            await self.channel_layer.group_send(
                                f'user_notify_{uid}',
                                {
                                    'type': 'notify.call',
                                    'from_user_id': self.user.id,
                                    'chat_id': int(self.chat_id),
                                    'audio_only': bool(payload.get('audioOnly')),
                                    'from_full_name': caller_name,
                                    'from_avatar': caller_avatar,
                                }
                            )
                    else:
                        logger.warning(f"Call offer received for non-private chat {self.chat_id}. Global notifications skipped.")

    async def signal_forward(self, event):
        # Do not echo back to sender; client can ignore if desired, but we filter here
        if event.get('from_user_id') == self.user.id:
            return
        await self.send(text_data=json.dumps({
            'type': event['event_type'],
            'from_user_id': event['from_user_id'],
            'payload': event['payload'],
        }))

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
        # No-op; server only pushes notifications
        return

    async def notify_call(self, event):
        logger.info(f"NotifyConsumer: Sending incoming.call to user {self.user.id} from {event.get('from_user_id')}")
        await self.send(text_data=json.dumps({
            'type': 'incoming.call',
            'from_user_id': event.get('from_user_id'),
            'chat_id': event.get('chat_id'),
            'audioOnly': event.get('audio_only', False),
            'from_full_name': event.get('from_full_name'),
            'from_avatar': event.get('from_avatar'),
        }))
