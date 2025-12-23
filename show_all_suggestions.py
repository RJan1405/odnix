from chat.views.chat import get_gender_balanced_suggestions
from chat.models import CustomUser
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'odnix.settings')
django.setup()


all_users = CustomUser.objects.all().order_by('id')

print("\n" + "="*80)
print("SUGGESTIONS FOR ALL USERS")
print("="*80 + "\n")

for user in all_users:
    suggestions = get_gender_balanced_suggestions(user, limit=5)
    print(f"User: {user.username} (ID: {user.id}, Gender: {user.gender})")
    if suggestions:
        print(f"  Suggestions ({len(suggestions)}):")
        for i, sugg in enumerate(suggestions, 1):
            print(f"    {i}. {sugg.username} ({sugg.gender})")
    else:
        print(f"  ⚠️  No suggestions returned")
    print()

print("="*80)
print("SUMMARY")
print("="*80)
print(f"Total users: {CustomUser.objects.count()}")
print(f"Males: {CustomUser.objects.filter(gender='male').count()}")
print(f"Females: {CustomUser.objects.filter(gender='female').count()}")
