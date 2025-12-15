import re
from django import template
from django.utils.safestring import mark_safe
from django.utils.html import escape

register = template.Library()


@register.filter(name='linkify_hashtags_mentions')
def linkify_hashtags_mentions(text):
    """
    Converts #hashtags and @mentions to clickable links in tweet content.
    """
    if not text:
        return text
    
    # Escape HTML first to prevent XSS
    text = escape(text)
    
    # Convert hashtags to links
    # Match #word (alphanumeric and underscores)
    hashtag_pattern = r'#(\w+)'
    text = re.sub(
        hashtag_pattern,
        r'<a href="/api/hashtag/\1/" class="hashtag-link">#\1</a>',
        text
    )
    
    # Convert mentions to links
    # Match @username (alphanumeric, underscores, and dots)
    mention_pattern = r'@([\w.]+)'
    text = re.sub(
        mention_pattern,
        r'<a href="/profile/\1/" class="mention-link">@\1</a>',
        text
    )
    
    return mark_safe(text)


@register.filter(name='highlight_search')
def highlight_search(text, search_term):
    """
    Highlights search terms in text.
    """
    if not search_term or not text:
        return text
    
    text = escape(text)
    pattern = re.compile(re.escape(search_term), re.IGNORECASE)
    text = pattern.sub(
        lambda m: f'<mark class="search-highlight">{m.group()}</mark>',
        text
    )
    
    return mark_safe(text)
