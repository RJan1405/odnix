from django import template
from chat.models import Follow

register = template.Library()

@register.filter(name='is_followed_by')
def is_followed_by(user, observer):
    """
    Returns True if the user is being followed by the observer.
    Usage: {{ target_user|is_followed_by:request.user }}
    """
    if not observer or not observer.is_authenticated:
        return False
    # Check simple case (user following themselves is usually irrelevant here but let's return False)
    if user == observer:
        return False
    
    return Follow.objects.filter(follower=observer, following=user).exists()
