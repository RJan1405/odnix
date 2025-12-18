#!/usr/bin/env python
from chat.models import Reel
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'odnix.settings')
django.setup()


print(f"Total reels: {Reel.objects.count()}")
for reel in Reel.objects.all()[:5]:
    print(
        f"- ID: {reel.id}, User: {reel.user.username}, Caption: {reel.caption[:50] if reel.caption else 'No caption'}")
