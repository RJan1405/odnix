#!/usr/bin/env python
from chat.models import P2PSignal
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'odnix.settings')
django.setup()


print("=== Latest Signal Data Structure ===")
latest = P2PSignal.objects.filter(
    signal_data__type__in=['webrtc.offer', 'offer']).order_by('-created_at').first()
if latest:
    print(f"\nSignal ID: {latest.id}")
    print(f"Type: {latest.signal_data.get('type')}")
    print(f"Full signal_data structure:")
    print(json.dumps(latest.signal_data, indent=2))
else:
    print("No offer signals found")
