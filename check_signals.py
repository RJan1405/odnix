#!/usr/bin/env python
from chat.models import P2PSignal
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'odnix.settings')
django.setup()


print("=== Recent P2P Signals ===")
signals = P2PSignal.objects.all().order_by('-created_at')[:10]
for s in signals:
    signal_type = s.signal_data.get('type', 'unknown') if isinstance(
        s.signal_data, dict) else 'unknown'
    print(f"ID {s.id}: {signal_type} | From: User {s.sender_id} | To: User {s.target_user_id} | Consumed: {s.is_consumed} | Created: {s.created_at}")

print(f"\nTotal signals: {P2PSignal.objects.count()}")
