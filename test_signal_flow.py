"""
Test script to verify P2P signal storage and retrieval
Run this after starting a call to check if signals are being stored correctly
"""
from django.contrib.auth import get_user_model
from chat.models import P2PSignal, Chat
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'odnix.settings')
django.setup()


User = get_user_model()


def test_signal_flow():
    print("=" * 60)
    print("P2P SIGNAL FLOW TEST")
    print("=" * 60)

    # Get all P2PSignals
    all_signals = P2PSignal.objects.all().order_by('-created_at')[:20]

    print(f"\n📊 Total signals in database: {P2PSignal.objects.count()}")
    print(f"📊 Recent signals (last 20):")
    print("-" * 60)

    if not all_signals:
        print("❌ No signals found in database!")
        print("\nPossible issues:")
        print("1. Signals are not being created by p2p_send_signal endpoint")
        print("2. sendViaServerRelay() is not being called")
        print("3. Database connection issue")
        return

    for signal in all_signals:
        signal_type = signal.signal_data.get('type', 'unknown') if isinstance(
            signal.signal_data, dict) else 'unknown'
        consumed = "✓ Consumed" if signal.is_consumed else "⏳ Pending"

        print(f"\n[Signal ID: {signal.id}]")
        print(f"  Type: {signal_type}")
        print(f"  From: {signal.sender.full_name} (ID: {signal.sender.id})")
        print(
            f"  To: {signal.target_user.full_name} (ID: {signal.target_user.id})")
        print(f"  Chat ID: {signal.chat.id}")
        print(f"  Status: {consumed}")
        print(f"  Created: {signal.created_at}")

    print("\n" + "=" * 60)

    # Check for unconsumed signals
    unconsumed = P2PSignal.objects.filter(is_consumed=False).count()
    print(f"\n⏳ Unconsumed signals: {unconsumed}")

    # Check by user
    print("\n📋 Signals by user:")
    for user in User.objects.all()[:10]:
        sent = P2PSignal.objects.filter(sender=user).count()
        received = P2PSignal.objects.filter(target_user=user).count()
        unconsumed_received = P2PSignal.objects.filter(
            target_user=user, is_consumed=False).count()

        if sent > 0 or received > 0:
            print(
                f"  {user.full_name} (ID: {user.id}): Sent={sent}, Received={received}, Pending={unconsumed_received}")

    print("\n" + "=" * 60)


if __name__ == '__main__':
    test_signal_flow()
