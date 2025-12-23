from chat.models import CustomUser
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'odnix.settings')
django.setup()


def gender_balanced_for(user, limit=5):
    qs = CustomUser.objects.exclude(id=user.id)
    target_f = 3 if limit >= 5 else max(0, min(3, limit))
    target_m = limit - target_f

    females = list(qs.filter(gender='female').order_by('?')[:target_f])
    males = list(qs.filter(gender='male').order_by('?')[:target_m])

    selected = females + males
    if len(selected) < limit:
        need = limit - len(selected)
        selected_ids = [u.id for u in selected]
        filler = list(qs.exclude(id__in=selected_ids).order_by('?')[:need])
        selected += filler
    return selected


print("\n" + "="*80)
print("SUGGESTIONS FOR ALL USERS")
print("="*80 + "\n")

all_users = CustomUser.objects.all().order_by('id')

for user in all_users:
    suggestions = gender_balanced_for(user, limit=5)

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
