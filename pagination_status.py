from chat.views.chat import _get_explore_content_batch
from django.db.models import Q
from chat.models import Tweet, Reel
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'odnix.settings')
django.setup()


# Get scribes with actual images or code
scribes_shown = Tweet.objects.exclude(image='').filter(
    Q(image__isnull=False) | Q(code_bundle__isnull=False) | Q(
        code_html__isnull=False)
)

# Get reels
reels_shown = Reel.objects.all()

print("=" * 80)
print("CURRENT PAGINATION STATUS")
print("=" * 80)

print("\n📊 CONTENT IN DATABASE:")
print("-" * 80)
print(f"📝 Scribes with media (shown):        {scribes_shown.count()}")
print(f"🎬 Reels (shown):                     {reels_shown.count()}")
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(
    f"Total in Explore Page:                {scribes_shown.count() + reels_shown.count()}")
print("=" * 80)

print("\n📄 PAGINATION BREAKDOWN (15 items per page):")
print("-" * 80)
print(f"{'Page':<6} {'Items':<7} {'Scribes':<10} {'Reels':<7} {'Status'}")
print("-" * 80)

total_items = 0
total_scribes = 0
total_reels = 0

for page in range(1, 10):
    result = _get_explore_content_batch(page=page, per_page=15)
    if result:
        types = {}
        for item in result:
            t = item['type']
            types[t] = types.get(t, 0) + 1

        scribes_count = types.get('scribe', 0)
        reels_count = types.get('reel', 0)
        total_items += len(result)
        total_scribes += scribes_count
        total_reels += reels_count

        status = "✓ Full" if len(result) == 15 else "✓ Last page"
        print(
            f"{page:<6} {len(result):<7} {scribes_count:<10} {reels_count:<7} {status}")
    else:
        print(f"{page:<6} {'0':<7} {'0':<10} {'0':<7} END")
        break

print("-" * 80)
print(f"{'TOTAL':<6} {total_items:<7} {total_scribes:<10} {total_reels:<7}")
print("=" * 80)
