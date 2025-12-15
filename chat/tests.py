import json
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from .models import Chat, Message, MessageRead

User = get_user_model()

class ChatRealTimeTestCase(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='user1', email='user1@test.com', password='pass')
        self.user2 = User.objects.create_user(username='user2', email='user2@test.com', password='pass')
        self.chat = Chat.objects.create(chat_type='private')
        self.chat.participants.add(self.user1, self.user2)

    def test_one_time_message_flow(self):
        """Test one-time message creation and consumption"""
        # Create one-time message
        message = Message.objects.create(
            chat=self.chat,
            sender=self.user1,
            content='Secret message',
            one_time=True
        )

        # Test consumption
        self.client.login(username='user2', password='pass')
        response = self.client.post(reverse('consume_message', args=[message.id]))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['content'], 'Secret message')

        # Check message is marked consumed
        message.refresh_from_db()
        self.assertIsNotNone(message.consumed_at)

    def test_message_read_receipt(self):
        """Test message read receipts"""
        message = Message.objects.create(
            chat=self.chat,
            sender=self.user1,
            content='Test message'
        )

        # Mark as read
        self.client.login(username='user2', password='pass')
        response = self.client.post(reverse('mark_message_read', args=[message.id]))
        self.assertEqual(response.status_code, 200)

        # Check read receipt exists
        read_receipt = MessageRead.objects.get(message=message, user=self.user2)
        self.assertIsNotNone(read_receipt.read_at)