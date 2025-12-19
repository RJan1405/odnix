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
        message = Message.objects.get(id=message_id, chat_id=self.chat_id, one_time=True)
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