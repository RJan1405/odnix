# models.py - FIXED VERSION with proper Tweet model

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.utils import timezone
import uuid
import string
import secrets
import os




class CustomUser(AbstractUser):
    """Custom user model with additional fields"""
    THEME_CHOICES = [
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('midnight', 'Midnight Blue'),
        ('forest', 'Forest Green'),
        ('sunset', 'Sunset Orange'),
        ('ocean', 'Ocean Teal'),
        ('lavender', 'Lavender Purple'),
        ('rose', 'Rose Pink'),
        ('charcoal', 'Charcoal'),
        ('nord', 'Nord'),
    ]
    
    name = models.CharField(max_length=50)
    lastname = models.CharField(max_length=50)
    email = models.EmailField(unique=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(default=timezone.now)
    is_email_verified = models.BooleanField(default=False)
    is_private = models.BooleanField(default=False)  # Private account feature
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='light')  # Theme preference
    
    def __str__(self):
        return f"{self.name} {self.lastname} (@{self.username})"
    
    @property
    def full_name(self):
        return f"{self.name} {self.lastname}"
    
    @property
    def initials(self):
        return f"{self.name[0] if self.name else ''}{self.lastname[0] if self.lastname else ''}".upper()
    
    @property
    def follower_count(self):
        """Get the number of followers"""
        return self.followers.count()
    
    @property
    def following_count(self):
        """Get the number of users this user is following"""
        return self.following.count()
    
    @property
    def profile_picture_url(self):
        """Get profile picture URL or return default"""
        if self.profile_picture and hasattr(self.profile_picture, 'url'):
            return self.profile_picture.url
        # Return a data URL for a simple gray placeholder
        return 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAiIGhlaWdodD0iNDAiIHZpZXdCb3g9IjAgMCA0MCA0MCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPGNpcmNsZSBjeD0iMjAiIGN5PSIyMCIgcj0iMjAiIGZpbGw9IiNFNUU3RUIiLz4KPHBhdGggZD0iTTIwIDI1QzIyLjc2MTQgMjUgMjIuNzYxNCAyNSAyMEMyNSAxNy4yMzg2IDIyLjc2MTQgMTUgMjAgMTVDMTcuMjM4NiAxNSAxNSAxNy4yMzg2IDE1IDIwQzE1IDIyLjc2MTQgMTcuMjM4NiAyNSAyMCAyNVoiIGZpbGw9IiM5Q0E0QUYiLz4KPHBhdGggZD0iTTMwIDI4QzMwIDI0LjY4NjMgMjYuNDI3MSAyMiAyMiAyMkgxOEMxMy41NzI5IDIyIDEwIDI0LjY4NjMgMTAgMjhWMzBIMzBWMjhaIiBmaWxsPSIjOUNBNEFGIi8+Cjwvc3ZnPgo='
    
    def mark_online(self):
        self.is_online = True
        self.last_seen = timezone.now()
        self.save(update_fields=['is_online', 'last_seen'])
    
    def mark_offline(self):
        self.is_online = False
        self.last_seen = timezone.now()  # Update last_seen when going offline
        self.save(update_fields=['is_online', 'last_seen'])

class Chat(models.Model):
    """Model for chats with enhanced group functionality"""
    CHAT_TYPE_CHOICES = [
        ('private', 'Private'),
        ('group', 'Group'),
    ]
    
    participants = models.ManyToManyField(CustomUser, related_name='chats', blank=True)
    chat_type = models.CharField(max_length=10, choices=CHAT_TYPE_CHOICES, default='private')
    name = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    admin = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='admin_chats', null=True, blank=True)
    invite_code = models.CharField(max_length=20, unique=True, blank=True, null=True)
    is_public = models.BooleanField(default=False)
    max_participants = models.IntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def save(self, *args, **kwargs):
        if self.chat_type == 'group' and not self.invite_code:
            self.invite_code = self.generate_invite_code()
        super().save(*args, **kwargs)
    
    def generate_invite_code(self):
        """Generate a unique invite code"""
        while True:
            code = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
            if not Chat.objects.filter(invite_code=code).exists():
                return code
    
    @property
    def invite_link(self):
        """Get the full invite link for this group"""
        if self.invite_code:
            from django.conf import settings
            domain = getattr(settings, 'SITE_DOMAIN', 'https://odnix.org')
            return f"{domain}/join-group/{self.invite_code}/"
        return None
    
    @property
    def participant_count(self):
        """Get current participant count"""
        return self.participants.count()
    
    @property
    def can_add_participants(self):
        """Check if more participants can be added"""
        return self.participant_count < self.max_participants
    
    def __str__(self):
        if self.chat_type == 'group':
            return self.name or f"Group Chat {self.id}"
        else:
            participants = self.participants.all()[:2]
            return f"Chat between {' and '.join([p.username for p in participants])}"

class GroupJoinRequest(models.Model):
    """Model for group join requests"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    group = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='join_requests')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='join_requests')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    message = models.TextField(blank=True, null=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    responded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='handled_requests')
    
    class Meta:
        unique_together = ('group', 'user')
        ordering = ['-requested_at']
    
    def __str__(self):
        return f"{self.user.username} wants to join {self.group.name} ({self.status})"

class Message(models.Model):
    """Model for chat messages with media support"""
    MESSAGE_TYPE_CHOICES = [
        ('text', 'Text'),
        ('system', 'System'),
        ('media', 'Media'),
    ]
    
    MEDIA_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
        ('document', 'Document'),
    ]
    
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True, blank=True)
    content = models.TextField()
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPE_CHOICES, default='text')
    media_url = models.URLField(blank=True, null=True)
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPE_CHOICES, blank=True, null=True)
    media_filename = models.CharField(max_length=255, blank=True, null=True)
    media_size = models.BigIntegerField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    reactions = models.JSONField(default=dict, blank=True)
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    one_time = models.BooleanField(default=False)  # For one-time messages
    consumed_at = models.DateTimeField(null=True, blank=True)  # When one-time message was consumed
    
    # Message Editing feature
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    original_content = models.TextField(blank=True, null=True)  # Store original content before edit
    
    # Pinned Messages feature
    is_pinned = models.BooleanField(default=False)
    pinned_at = models.DateTimeField(null=True, blank=True)
    pinned_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='pinned_messages')
    
    class Meta:
        ordering = ['timestamp']
    
    def __str__(self):
        sender_name = self.sender.username if self.sender else "System"
        if self.media_url:
            return f"{sender_name}: [Media: {self.media_type}]"
        return f"{sender_name}: {self.content[:50]}..."
    
    @property
    def has_media(self):
        """Check if message has media attachment"""
        return bool(self.media_url)
    
    @property
    def is_image(self):
        """Check if message contains an image"""
        return self.media_type == 'image'
    
    @property
    def is_video(self):
        """Check if message contains a video"""
        return self.media_type == 'video'
    
    @property
    def can_be_edited(self):
        """Check if message can still be edited (within 15 minutes)"""
        from django.utils import timezone
        if not self.timestamp:
            return False
        time_diff = timezone.now() - self.timestamp
        return time_diff.total_seconds() < 900  # 15 minutes = 900 seconds
    
    @property
    def is_read_by_recipient(self):
        """Check if message has been read by anyone other than the sender (for read receipts)"""
        if not self.sender:
            return False
        return self.read_receipts.exclude(user=self.sender).exists()

class Story(models.Model):
    """Model for user stories - Instagram-like"""
    STORY_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
        ('text', 'Text'),
    ]
    
    TEXT_POSITION_CHOICES = [
        ('top', 'Top'),
        ('center', 'Center'),
        ('bottom', 'Bottom'),
    ]
    
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='stories')
    content = models.TextField(blank=True, null=True)  # For text stories or captions
    media_file = models.FileField(upload_to='story_media/', blank=True, null=True)  # For image/video stories
    story_type = models.CharField(max_length=10, choices=STORY_TYPE_CHOICES, default='text')
    background_color = models.CharField(max_length=7, default='#667eea')  # For text stories
    text_color = models.CharField(max_length=7, default='#ffffff')  # For text stories
    text_position = models.CharField(max_length=10, choices=TEXT_POSITION_CHOICES, default='center')  # Text position
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()  # Stories expire after 24 hours
    is_active = models.BooleanField(default=True)
    # Removed old views ManyToManyField - now using StoryView model
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=24)
        super().save(*args, **kwargs)
    
    @property
    def is_expired(self):
        """Check if story has expired"""
        return timezone.now() > self.expires_at
    
    @property
    def view_count(self):
        """Get story view count"""
        return self.story_views.count()
    
    @property
    def like_count(self):
        """Get story like count"""
        return self.story_likes.count()
    
    @property
    def reply_count(self):
        """Get story reply count"""
        return self.story_replies.count()
    
    @property
    def is_liked_by_user(self, user):
        """Check if story is liked by a specific user"""
        if not user or user.is_anonymous:
            return False
        return self.story_likes.filter(user=user).exists()
    
    @property
    def media_url(self):
        """Get media URL if exists"""
        if self.media_file and hasattr(self.media_file, 'url'):
            return self.media_file.url
        return None
    
    def __str__(self):
        return f"{self.user.username}'s story - {self.story_type}"

class StoryView(models.Model):
    """Model to track detailed story views with timestamps"""
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='story_views')
    viewer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='story_views_made')
    viewed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['story', 'viewer']  # One view per user per story
        ordering = ['-viewed_at']
    
    def __str__(self):
        return f"{self.viewer.username} viewed {self.story.user.username}'s story"

class StoryLike(models.Model):
    """Model for story likes"""
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='story_likes')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='story_likes_given')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['story', 'user']  # One like per user per story
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} liked {self.story.user.username}'s story"

class StoryReply(models.Model):
    """Model for story replies - only visible to story poster"""
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='story_replies')
    replier = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='story_replies_made')
    content = models.TextField(max_length=500)  # Reply content
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)  # Track if story poster has read the reply
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"Reply to {self.story.user.username}'s story by {self.replier.username}"

class Tweet(models.Model):
    """Model for user tweets/posts with FIXED image support"""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='tweets')
    content = models.TextField(max_length=280, blank=True)  # Allow blank content for image-only tweets
    timestamp = models.DateTimeField(auto_now_add=True)
    
    # FIXED: Enhanced media support for tweets
    image = models.ImageField(upload_to='tweet_images/', blank=True, null=True)  # Direct image upload
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.user.username}: {self.content[:50]}..." if self.content else f"{self.user.username}: [Image Tweet]"
    
    @property
    def like_count(self):
        """Get the count of likes for this tweet"""
        return self.tweet_likes.count()
    
    @property
    def comment_count(self):
        """Get the count of comments for this tweet"""
        return self.comments.count()
    
    def is_liked_by(self, user):
        """Check if a specific user has liked this tweet"""
        if not user.is_authenticated:
            return False
        return self.tweet_likes.filter(user=user).exists()
    
    @property
    def has_media(self):
        """Check if tweet has media attachment"""
        return bool(self.image)
    
    @property
    def image_url(self):
        """Get tweet image URL"""
        if self.image and hasattr(self.image, 'url'):
            return self.image.url
        return None

class Comment(models.Model):
    """Model for tweet comments"""
    tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='user_comments')
    content = models.TextField(max_length=500)
    timestamp = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
    
    class Meta:
        ordering = ['timestamp']
    
    def __str__(self):
        return f"{self.user.username} commented on {self.tweet.user.username}'s tweet"
    
    @property
    def reply_count(self):
        """Get the count of replies to this comment"""
        return self.replies.count()

class Like(models.Model):
    """Model for tweet likes"""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='user_likes')
    tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='tweet_likes')
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user', 'tweet')
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.user.full_name} liked {self.tweet.user.full_name}'s tweet"

class SavedPost(models.Model):
    """Model for saved/bookmarked posts"""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='saved_posts')
    tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='saved_by')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user', 'tweet')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} saved {self.tweet.user.username}'s post"

class PostReport(models.Model):
    """Model for reported posts"""
    REPORT_REASONS = [
        ('spam', 'Spam'),
        ('inappropriate', 'Inappropriate Content'),
        ('harassment', 'Harassment or Bullying'),
        ('violence', 'Violence or Threats'),
        ('hate_speech', 'Hate Speech'),
        ('false_info', 'False Information'),
        ('other', 'Other'),
    ]
    
    reporter = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='reports_made')
    tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='reports')
    reason = models.CharField(max_length=20, choices=REPORT_REASONS)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed = models.BooleanField(default=False)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ('reporter', 'tweet')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.reporter.username} reported {self.tweet.user.username}'s post for {self.reason}"

class Follow(models.Model):
    """Model for user following relationships"""
    follower = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='following')
    following = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('follower', 'following')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.follower.full_name} follows {self.following.full_name}"


class Block(models.Model):
    """Model for user blocking relationships"""
    blocker = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='blocking')
    blocked = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='blocked_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('blocker', 'blocked')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.blocker.full_name} blocks {self.blocked.full_name}"


class FollowRequest(models.Model):
    """Model for follow requests to private accounts"""
    requester = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sent_requests')
    target = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='received_requests')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=[
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined')
    ], default='pending')

    class Meta:
        unique_together = ('requester', 'target')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.requester.full_name} → {self.target.full_name} ({self.status})"

class EmailVerificationToken(models.Model):
    """Model for email verification tokens"""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='verification_tokens')
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    
    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=24)
        super().save(*args, **kwargs)
    
    @property
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    def __str__(self):
        return f"Verification token for {self.user.email}"

class EmojiSet(models.Model):
    """Model for storing custom emoji sets"""
    name = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    emojis = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name


class MessageReaction(models.Model):
    """Model for emoji reactions to messages"""
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='message_reactions')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    emoji = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('message', 'user', 'emoji')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} reacted {self.emoji} to message {self.message.id}"


class MessageDeletion(models.Model):
    """Model to track messages deleted for specific users (delete for me functionality)"""
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='deletions')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    deleted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user')
        ordering = ['-deleted_at']

    def __str__(self):
        return f"Message {self.message.id} deleted for {self.user.username}"

class MessageRead(models.Model):
    """Model for tracking message read receipts per recipient"""
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='read_receipts')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user')
        ordering = ['-read_at']

    def __str__(self):
        return f"Message {self.message.id} read by {self.user.username} at {self.read_at}"


class Hashtag(models.Model):
    """Model for hashtags used in tweets"""
    name = models.CharField(max_length=100, unique=True)  # Hashtag without the # symbol
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"#{self.name}"
    
    @property
    def tweet_count(self):
        """Get count of tweets using this hashtag"""
        return self.tweets.count()


class TweetHashtag(models.Model):
    """Model for linking tweets to hashtags (many-to-many)"""
    tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='tweet_hashtags')
    hashtag = models.ForeignKey(Hashtag, on_delete=models.CASCADE, related_name='tweets')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('tweet', 'hashtag')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"#{self.hashtag.name} in tweet {self.tweet.id}"


class Mention(models.Model):
    """Model for @mentions in tweets"""
    tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='mentions')
    mentioned_user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='tweet_mentions')
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)  # Track if mentioned user has seen the mention
    
    class Meta:
        unique_together = ('tweet', 'mentioned_user')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"@{self.mentioned_user.username} mentioned in tweet {self.tweet.id}"


class PinnedChat(models.Model):
    """Model for pinned conversations per user"""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='pinned_chats')
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='pinned_by_users')
    pinned_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user', 'chat')
        ordering = ['-pinned_at']
    
    def __str__(self):
        return f"{self.user.username} pinned chat {self.chat.id}"


class StarredMessage(models.Model):
    """Model for starred/saved messages per user"""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='starred_messages')
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='starred_by')
    starred_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user', 'message')
        ordering = ['-starred_at']
    
    def __str__(self):
        return f"{self.user.username} starred message {self.message.id}"


class TypingStatus(models.Model):
    """Model for tracking typing status in chats"""
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='typing_statuses')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='typing_in_chats')
    started_typing_at = models.DateTimeField(auto_now=True)
    is_typing = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('chat', 'user')
    
    def __str__(self):
        status = "typing" if self.is_typing else "not typing"
        return f"{self.user.username} is {status} in chat {self.chat.id}"
    
    @property
    def is_still_typing(self):
        """Check if user is still typing (within last 3 seconds)"""
        if not self.is_typing:
            return False
        time_diff = timezone.now() - self.started_typing_at
        return time_diff.total_seconds() < 3  # 3 second timeout


class P2PSignal(models.Model):
    """Store P2P WebRTC signaling data for file transfers"""
    chat = models.ForeignKey('Chat', on_delete=models.CASCADE, related_name='p2p_signals')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_p2p_signals')
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_p2p_signals')
    signal_data = models.JSONField()  # Contains type, offer/answer/candidate, fileInfo
    created_at = models.DateTimeField(auto_now_add=True)
    is_consumed = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['chat', 'target_user', 'is_consumed']),
        ]
    
    def __str__(self):
        signal_type = self.signal_data.get('type', 'unknown') if isinstance(self.signal_data, dict) else 'unknown'
        return f"P2P Signal ({signal_type}) from {self.sender.username} to {self.target_user.username}"
    
    @classmethod
    def cleanup_old_signals(cls):
        """Remove signals older than 5 minutes"""
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(minutes=5)
        cls.objects.filter(created_at__lt=cutoff).delete()

class Reel(models.Model):
    """Model for short video reels"""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='reels')
    video_file = models.FileField(upload_to='reels/')
    caption = models.TextField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    views_count = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Reel by {self.user.username} at {self.created_at}"

    @property
    def like_count(self):
        return self.likes.count()

    @property
    def comment_count(self):
        return self.comments.count()

    def is_liked_by(self, user):
        if not user.is_authenticated:
            return False
        return self.likes.filter(user=user).exists()

class ReelLike(models.Model):
    """Model for reel likes"""
    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='liked_reels')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('reel', 'user')

class ReelComment(models.Model):
    """Model for reel comments"""
    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='reel_comments')
    content = models.TextField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
