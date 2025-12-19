# admin.py - FIXED VERSION

from .models import Reel, ReelLike, ReelComment
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser, Chat, Message, Tweet, GroupJoinRequest,
    Like, Follow, EmailVerificationToken, Story, Comment,
    SavedPost, PostReport
)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'full_name', 'email',
                    'is_online', 'last_seen', 'is_email_verified']
    list_filter = ['is_online', 'is_email_verified',
                   'last_seen', 'date_joined']
    search_fields = ['username', 'name', 'lastname', 'email']

    fieldsets = UserAdmin.fieldsets + (
        ('Personal Info', {
            'fields': ('name', 'lastname', 'profile_picture', 'is_online', 'last_seen', 'is_email_verified')
        }),
    )

    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = 'Full Name'


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'chat_type', 'admin',
                    'participant_count', 'created_at', 'updated_at']
    list_filter = ['chat_type', 'is_public', 'created_at']
    search_fields = ['name', 'description', 'invite_code']
    filter_horizontal = ['participants']
    readonly_fields = ['invite_code', 'created_at', 'updated_at']

    def participant_count(self, obj):
        return obj.participant_count
    participant_count.short_description = 'Members'

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'chat_type', 'admin')
        }),
        ('Group Settings', {
            'fields': ('max_participants', 'is_public', 'invite_code'),
            'classes': ('collapse',),
        }),
        ('Participants', {
            'fields': ('participants',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


@admin.register(GroupJoinRequest)
class GroupJoinRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'group', 'status', 'requested_at', 'responded_by']
    list_filter = ['status', 'requested_at']
    search_fields = ['user__username', 'group__name', 'message']
    readonly_fields = ['requested_at', 'responded_at']
    raw_id_fields = ['user', 'group', 'responded_by']

    fieldsets = (
        ('Request Information', {
            'fields': ('group', 'user', 'message', 'status')
        }),
        ('Response', {
            'fields': ('responded_by', 'responded_at'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('requested_at',),
            'classes': ('collapse',),
        }),
    )

    actions = ['approve_requests', 'reject_requests']

    def approve_requests(self, request, queryset):
        for req in queryset.filter(status='pending'):
            if req.group.can_add_participants:
                req.group.participants.add(req.user)
                req.status = 'approved'
                req.responded_by = request.user
                req.save()
        self.message_user(request, f"{queryset.count()} requests processed.")
    approve_requests.short_description = "Approve selected requests"

    def reject_requests(self, request, queryset):
        queryset.filter(status='pending').update(
            status='rejected',
            responded_by=request.user
        )
        self.message_user(request, f"{queryset.count()} requests rejected.")
    reject_requests.short_description = "Reject selected requests"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['chat', 'sender', 'content_preview',
                    'message_type', 'timestamp', 'is_read']
    list_filter = ['message_type', 'timestamp', 'is_read']
    search_fields = ['content', 'sender__username', 'chat__name']
    readonly_fields = ['timestamp']
    raw_id_fields = ['chat', 'sender']

    def content_preview(self, obj):
        return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content
    content_preview.short_description = 'Content'


@admin.register(Tweet)
class TweetAdmin(admin.ModelAdmin):
    list_display = ['user', 'content_preview', 'has_image',
                    'timestamp', 'like_count', 'comment_count']
    list_filter = ['timestamp']
    search_fields = ['content', 'user__username',
                     'user__name', 'user__lastname']
    readonly_fields = ['timestamp']
    raw_id_fields = ['user']

    def content_preview(self, obj):
        if obj.content:
            return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content
        return "[Image only tweet]"
    content_preview.short_description = 'Content'

    def has_image(self, obj):
        return bool(obj.image)
    has_image.boolean = True
    has_image.short_description = 'Has Image'

    def like_count(self, obj):
        return obj.like_count
    like_count.short_description = 'Likes'

    def comment_count(self, obj):
        return obj.comment_count
    comment_count.short_description = 'Comments'


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ['user', 'tweet_preview',
                    'content_preview', 'timestamp', 'parent']
    list_filter = ['timestamp']
    search_fields = ['content', 'user__username', 'tweet__content']
    readonly_fields = ['timestamp']
    raw_id_fields = ['user', 'tweet', 'parent']

    def tweet_preview(self, obj):
        return obj.tweet.content[:30] + "..." if len(obj.tweet.content) > 30 else obj.tweet.content
    tweet_preview.short_description = 'Tweet'

    def content_preview(self, obj):
        return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content
    content_preview.short_description = 'Comment'


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ['user', 'tweet_preview', 'timestamp']
    list_filter = ['timestamp']
    search_fields = ['user__username', 'tweet__content']
    readonly_fields = ['timestamp']
    raw_id_fields = ['user', 'tweet']

    def tweet_preview(self, obj):
        if obj.tweet.content:
            return obj.tweet.content[:30] + "..." if len(obj.tweet.content) > 30 else obj.tweet.content
        return "[Image tweet]"
    tweet_preview.short_description = 'Tweet'


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ['follower', 'following', 'created_at']
    list_filter = ['created_at']
    search_fields = ['follower__username', 'following__username']
    readonly_fields = ['created_at']
    raw_id_fields = ['follower', 'following']


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    list_display = ['user', 'created_at', 'expires_at', 'is_used']
    list_filter = ['is_used', 'created_at', 'expires_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['token', 'created_at', 'expires_at']
    raw_id_fields = ['user']


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'story_type', 'content_preview', 'created_at',
                    'expires_at', 'is_active', 'view_count', 'like_count', 'reply_count']
    list_filter = ['story_type', 'is_active', 'created_at']
    search_fields = ['user__username', 'content']
    readonly_fields = ['created_at', 'expires_at',
                       'view_count', 'like_count', 'reply_count']
    raw_id_fields = ['user']

    def content_preview(self, obj):
        if obj.content:
            return obj.content[:30] + "..." if len(obj.content) > 30 else obj.content
        return f"[{obj.story_type} story]"
    content_preview.short_description = 'Content'

    def view_count(self, obj):
        return obj.view_count
    view_count.short_description = 'Views'

    def like_count(self, obj):
        return obj.like_count
    like_count.short_description = 'Likes'

    def reply_count(self, obj):
        return obj.reply_count


@admin.register(SavedPost)
class SavedPostAdmin(admin.ModelAdmin):
    list_display = ['user', 'tweet', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'tweet__content']
    raw_id_fields = ['user', 'tweet']
    readonly_fields = ['created_at']


@admin.register(PostReport)
class PostReportAdmin(admin.ModelAdmin):
    list_display = ['reporter', 'tweet', 'reason', 'created_at', 'reviewed']
    list_filter = ['reason', 'reviewed', 'created_at']
    search_fields = ['reporter__username', 'tweet__content', 'description']
    raw_id_fields = ['reporter', 'tweet']
    readonly_fields = ['created_at', 'reviewed_at']
    actions = ['mark_as_reviewed']

    def mark_as_reviewed(self, request, queryset):
        from django.utils import timezone
        queryset.update(reviewed=True, reviewed_at=timezone.now())
    mark_as_reviewed.short_description = "Mark selected reports as reviewed"


@admin.register(Reel)
class ReelAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'caption_preview', 'views_count',
                    'like_count', 'comment_count', 'rank_score', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'caption']
    readonly_fields = ['created_at', 'views_count',
                       'like_count', 'comment_count']

    def caption_preview(self, obj):
        return obj.caption[:50] + "..." if len(obj.caption) > 50 else obj.caption
    caption_preview.short_description = 'Caption'

    def like_count(self, obj):
        return obj.likes.count()
    like_count.short_description = 'Likes'

    def comment_count(self, obj):
        return obj.comments.count()
    comment_count.short_description = 'Comments'

    def rank_score(self, obj):
        """Display engagement-only rank (likes, comments, views)"""
        likes = obj.likes.count()
        comments = obj.comments.count()
        views = obj.views_count

        engagement = (likes * 2.0) + (comments * 4.0) + (views * 0.1)
        return f"{engagement:.2f} (L:{likes} C:{comments} V:{views})"
    rank_score.short_description = 'Rank (Likes/Comments/Views)'


@admin.register(ReelLike)
class ReelLikeAdmin(admin.ModelAdmin):
    list_display = ['user', 'reel', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'reel__caption']


@admin.register(ReelComment)
class ReelCommentAdmin(admin.ModelAdmin):
    list_display = ['user', 'reel', 'content', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'content']
