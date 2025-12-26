from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q, Max, Exists, OuterRef
from django.core.cache import cache
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
import logging
from datetime import timedelta

from chat.models import (
    CustomUser, Chat, Message, GroupJoinRequest, Follow, Story, StoryView,
    StoryLike, StoryReply, Tweet, Like, Comment, MessageDeletion, MessageRead,
    MessageReaction, StarredMessage, PinnedChat, SavedPost, Reel
)
from chat.forms import TweetForm
from .media import handle_media_upload
from django.conf import settings
import json as _json

logger = logging.getLogger(__name__)


@login_required
def dashboard(request):
    """FIXED - Enhanced dashboard with proper multiple stories support"""

    # Get user's chats
    user_chats = Chat.objects.filter(
        participants=request.user).select_related('admin')
    private_chats = user_chats.filter(chat_type='private')
    group_chats = user_chats.filter(chat_type='group')

    # Get other users
    other_users = CustomUser.objects.exclude(
        id=request.user.id).distinct().order_by('name', 'lastname')

    # Get pending join requests
    pending_requests = GroupJoinRequest.objects.filter(
        group__admin=request.user,
        status='pending'
    ).select_related('user', 'group').order_by('-requested_at')

    # Get following users
    following_users = Follow.objects.filter(
        follower=request.user).values_list('following', flat=True)

    # Get suggestions (users not followed)
    # Priority: Min 3 Female, 2 Male
    candidates = CustomUser.objects.exclude(
        id=request.user.id
    ).exclude(
        id__in=following_users
    )

    females = list(candidates.filter(gender='female').order_by('?')[:3])
    males = list(candidates.filter(gender='male').order_by('?')[:2])
    suggestion_users = females + males

    # If we don't have 5 yet, fill with anyone
    if len(suggestion_users) < 5:
        existing_ids = [u.id for u in suggestion_users]
        needed = 5 - len(suggestion_users)
        fillers = list(candidates.exclude(
            id__in=existing_ids).order_by('?')[:needed])
        suggestion_users.extend(fillers)

    # Shuffle result
    import random
    random.shuffle(suggestion_users)

    # FIXED: Get active stories from followed users - SUPPORT MULTIPLE STORIES PER USER
    active_stories = Story.objects.filter(
        user__in=following_users,
        is_active=True,
        expires_at__gt=timezone.now()
    ).select_related('user').order_by('-created_at')

    # FIXED: Group stories by user (latest first) - ALLOW MULTIPLE STORIES
    stories_by_user = {}
    for story in active_stories:
        if story.user.id not in stories_by_user:
            stories_by_user[story.user.id] = {
                'user': story.user,
                'stories': [],
                'latest_story': story,
                'story_count': 0,
                'viewed_count': 0,
                'all_viewed': True
            }
        stories_by_user[story.user.id]['stories'].append(story)
        stories_by_user[story.user.id]['story_count'] += 1

        # Check if current user has viewed this story
        has_viewed = StoryView.objects.filter(
            story=story, viewer=request.user).exists()
        if has_viewed:
            stories_by_user[story.user.id]['viewed_count'] += 1
        else:
            stories_by_user[story.user.id]['all_viewed'] = False

    # FIXED: Get user's own active stories (separate from others) - ALLOW MULTIPLE
    user_stories = Story.objects.filter(
        user=request.user,
        is_active=True,
        expires_at__gt=timezone.now()
    ).order_by('-created_at')

    # Get the latest user story for the main display
    user_story = user_stories.first()
    user_story_count = user_stories.count()

    # Get tweets from followed users (social media feed)
    tweets_queryset = Tweet.objects.filter(
        Q(user__in=following_users) | Q(user=request.user)  # Include own tweets
    ).select_related('user').prefetch_related('comments__user').distinct().order_by('-timestamp')

    # Process tweets with like/comment data
    tweets_data = []
    processed_tweet_ids = set()

    for tweet in tweets_queryset[:20]:  # Limit to 20 most recent
        if tweet.id in processed_tweet_ids:
            continue
        processed_tweet_ids.add(tweet.id)

        # Get like count and if current user liked it
        like_count = Like.objects.filter(tweet=tweet).count()
        is_liked = Like.objects.filter(tweet=tweet, user=request.user).exists()

        # Check if current user has saved this post
        is_saved = SavedPost.objects.filter(
            tweet=tweet, user=request.user).exists()

        # Get comment count
        comment_count = Comment.objects.filter(tweet=tweet).count()

        # Get recent comments (latest 3)
        recent_comments = Comment.objects.filter(
            tweet=tweet,
            parent__isnull=True
        ).select_related('user').order_by('-timestamp')[:3]

        # Calculate time ago
        time_diff = timezone.now() - tweet.timestamp
        if time_diff.days > 0:
            time_ago = f"{time_diff.days}d"
        elif time_diff.seconds > 3600:
            time_ago = f"{time_diff.seconds // 3600}h"
        else:
            time_ago = f"{time_diff.seconds // 60}m"

        tweets_data.append({
            'id': tweet.id,
            'content': tweet.content,
            'content_type': getattr(tweet, 'content_type', 'text'),
            'code_bundle': getattr(tweet, 'code_bundle', None),
            'code_html': getattr(tweet, 'code_html', None),
            'code_css': getattr(tweet, 'code_css', None),
            'code_js': getattr(tweet, 'code_js', None),
            'user': tweet.user,
            'user_id': tweet.user.id,
            'username': tweet.user.username,
            'fullname': tweet.user.full_name,
            'user_initials': tweet.user.initials,
            'profile_picture_url': tweet.user.profile_picture_url,
            'formatted_time': tweet.timestamp.strftime('%b %d, %Y %H:%M'),
            'time_ago': time_ago,
            'like_count': like_count,
            'comment_count': comment_count,
            'is_liked': is_liked,
            'is_saved': is_saved,
            'is_own': tweet.user == request.user,
            'image_url': tweet.image_url,
            'has_media': tweet.has_media,
            'recent_comments': recent_comments,
        })

    # Create tweet form instance for proper rendering
    tweet_form = TweetForm()

    # Get story inbox count (replies/likes to user's stories)
    story_inbox_count = StoryReply.objects.filter(
        story__user=request.user,
        is_read=False
    ).count() + StoryLike.objects.filter(
        story__user=request.user,
    ).exclude(user=request.user).count()

    # Get unread message count for the DM badge - count unique chats with unread messages
    unread_message_count = Chat.objects.filter(
        participants=request.user,
        messages__is_read=False
    ).exclude(messages__sender=request.user).distinct().count()

    # Combine all chats for the chats panel with additional info
    all_chats = []
    for chat in user_chats.order_by('-updated_at')[:20]:
        chat_info = {
            'id': chat.id,
            'name': chat.name,
            'is_group': chat.chat_type == 'group',
        }

        # Get other user for private chats
        if chat.chat_type == 'private':
            other_participant = chat.participants.exclude(
                id=request.user.id).first()
            chat_info['other_user'] = other_participant

        # Get last message
        last_message = chat.messages.order_by('-timestamp').first()
        if last_message:
            chat_info['last_message_preview'] = last_message.content[:50] + \
                ('...' if len(last_message.content) > 50 else '')
            chat_info['last_message_time'] = last_message.timestamp
        else:
            chat_info['last_message_preview'] = None
            chat_info['last_message_time'] = None

        # Get unread count
        chat_info['unread_count'] = chat.messages.filter(
            is_read=False).exclude(sender=request.user).count()

        all_chats.append(chat_info)

    context = {
        'private_chats': private_chats,
        'group_chats': group_chats,
        'chats': all_chats,  # Combined chats for the panel
        'other_users': other_users,
        'suggestion_users': suggestion_users,
        'pending_requests': pending_requests,
        'current_user': request.user,
        'stories_by_user': stories_by_user,  # Keep as dict for template iteration
        'user_story': user_story,  # Latest user story for display
        'user_stories': user_stories,  # ALL user stories for navigation
        'user_story_count': user_story_count,  # Count for display
        'tweets_data': tweets_data,
        'tweet_form': tweet_form,  # Pass form to template
        'story_inbox_count': story_inbox_count,  # Notification count
        'unread_message_count': unread_message_count,  # DM badge count
    }

    # Use Instagram-style template
    return render(request, 'chat/dashboard_instagram.html', context)


@login_required
def chat_view(request, chat_id):
    chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

    # Update current user's online status
    request.user.last_seen = timezone.now()
    request.user.is_online = True
    request.user.save(update_fields=['last_seen', 'is_online'])

    messages_list = chat.messages.exclude(
        deletions__user=request.user
    ).order_by('timestamp')
    other_participants = chat.participants.exclude(id=request.user.id)

    # Fix stale online status for other participants
    # A user is only truly online if is_online=True AND last_seen is within 2 minutes
    for participant in other_participants:
        if participant.is_online and participant.last_seen:
            time_since_last_seen = timezone.now() - participant.last_seen
            if time_since_last_seen >= timedelta(seconds=15):
                # Mark as offline - their session is stale
                participant.is_online = False
                participant.save(update_fields=['is_online'])

    is_admin = chat.admin == request.user if chat.chat_type == 'group' else False

    join_requests = []
    if is_admin:
        join_requests = GroupJoinRequest.objects.filter(
            group=chat,
            status='pending'
        ).select_related('user').order_by('-requested_at')

    context = {
        'chat': chat,
        'messages': messages_list,
        'other_participants': other_participants,
        'is_admin': is_admin,
        'join_requests': join_requests,
    }
    # Calls feature flags and ICE servers for WebRTC
    context['calls_enabled'] = getattr(settings, 'ENABLE_CALLS', True)
    ice_servers = getattr(settings, 'WEBRTC_ICE_SERVERS', [])
    try:
        context['ice_servers_json'] = _json.dumps(ice_servers)
    except Exception:
        context['ice_servers_json'] = '[]'

    # Use Instagram-style template
    return render(request, 'chat/chat_detail_instagram.html', context)


@login_required
def messages_page(request):
    """Dedicated messages page to pick a chat (replaces sidebar/panel)."""
    # User chats split by type
    user_chats = Chat.objects.filter(participants=request.user).select_related(
        'admin').order_by('-updated_at')
    private_chats = user_chats.filter(chat_type='private')
    group_chats = user_chats.filter(chat_type='group')

    # Other users for search/help
    other_users = CustomUser.objects.exclude(
        id=request.user.id).distinct().order_by('name', 'lastname')

    # Counts for navbar badges
    story_inbox_count = (
        StoryReply.objects.filter(
            story__user=request.user, is_read=False).count()
        + StoryLike.objects.filter(story__user=request.user).exclude(user=request.user).count()
    )
    unread_message_count = Chat.objects.filter(
        participants=request.user,
        messages__is_read=False
    ).exclude(messages__sender=request.user).distinct().count()

    context = {
        'current_user': request.user,
        'private_chats': private_chats,
        'group_chats': group_chats,
        'other_users': other_users,
        'story_inbox_count': story_inbox_count,
        'unread_message_count': unread_message_count,
    }

    # Render a chat-style messages selector (two-pane layout with empty chat area)
    return render(request, 'chat/messages_instagram.html', context)


@login_required
def get_chat_messages(request, chat_id):
    """FIXED - Get chat messages with proper API response"""
    chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

    last_message_time = request.GET.get('last_message_time')
    after_id = request.GET.get('after_id')
    messages_query = chat.messages.all().order_by('timestamp')

    # Filter by message ID (preferred method to avoid duplicates)
    if after_id:
        try:
            messages_query = messages_query.filter(id__gt=int(after_id))
        except:
            pass
    # Fallback to time-based filtering
    elif last_message_time:
        try:
            from datetime import datetime
            last_time = datetime.fromisoformat(
                last_message_time.replace('Z', '+00:00'))
            messages_query = messages_query.filter(timestamp__gt=last_time)
        except:
            pass

    messages_data = []
    for msg in messages_query:
        # Check if this message has been read by anyone other than the sender
        is_read = msg.read_receipts.exclude(
            user=msg.sender).exists() if msg.sender else False

        message_data = {
            'id': msg.id,
            'content': msg.content,
            'sender': msg.sender.username if msg.sender else 'System',
            'sender_name': msg.sender.full_name if msg.sender else 'System',
            'sender_avatar': msg.sender.profile_picture_url if msg.sender else None,
            'sender_initials': msg.sender.initials if msg.sender else 'S',
            'timestamp': msg.timestamp.strftime('%H:%M'),
            'timestamp_iso': msg.timestamp.isoformat(),
            'message_type': msg.message_type,
            'is_own': msg.sender == request.user if msg.sender else False,
            'is_read': is_read,
            'one_time': msg.one_time,
            'consumed': msg.consumed_at is not None,
            'has_media': msg.has_media,
            'media_url': msg.media_url,
            'media_type': msg.media_type,
            'media_filename': msg.media_filename,
            'reply_to': {
                'id': msg.reply_to.id if msg.reply_to else None,
                'content': msg.reply_to.content if msg.reply_to else None,
                'sender_name': msg.reply_to.sender.full_name if msg.reply_to else None,
            } if msg.reply_to else None
        }

        messages_data.append(message_data)

    return JsonResponse({
        'messages': messages_data,
        'chat_updated': chat.updated_at.isoformat()
    })


@login_required
@require_POST
def send_message(request):
    try:
        chat_id = request.POST.get('chat_id')
        content = request.POST.get('content', '').strip()
        media_file = request.FILES.get('media')
        one_time = request.POST.get('one_time', 'false').lower() == 'true'

        if not content and not media_file:
            return JsonResponse({'success': False, 'error': 'Message cannot be empty'})

        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        # Handle reply
        reply_to_id = request.POST.get('reply_to')
        reply_to_message = None
        if reply_to_id:
            try:
                reply_to_message = Message.objects.get(
                    id=reply_to_id, chat=chat)
            except Message.DoesNotExist:
                pass

        # Handle media upload
        media_url = None
        media_type = None
        media_filename = None
        media_size = None

        if media_file:
            media_url, media_type, media_filename, media_size = handle_media_upload(
                media_file)
            if not media_url:
                return JsonResponse({'success': False, 'error': 'Failed to upload media file'})

        message_type = 'media' if media_file else 'text'

        # Create message
        message = Message.objects.create(
            chat=chat,
            sender=request.user,
            content=content or f'Sent {media_type}' if media_file else content,
            message_type=message_type,
            media_url=media_url,
            media_type=media_type,
            media_filename=media_filename,
            media_size=media_size,
            reply_to=reply_to_message,
            one_time=one_time
        )

        # Update chat timestamp
        chat.updated_at = timezone.now()
        chat.save()

        return JsonResponse({
            'success': True,
            'message': {
                'id': message.id,
                'content': message.content,
                'sender': message.sender.username,
                'sender_name': message.sender.full_name,
                'sender_avatar': message.sender.profile_picture_url,
                'sender_initials': message.sender.initials,
                'timestamp': message.timestamp.strftime('%H:%M'),
                'timestamp_iso': message.timestamp.isoformat(),
                'message_type': message.message_type,
                'media_url': message.media_url,
                'media_type': message.media_type,
                'media_filename': message.media_filename,
                'one_time': message.one_time,
                'consumed': False,
                'is_own': message.sender == request.user,
                'has_media': message.has_media,
                'reply_to': {
                    'id': message.reply_to.id if message.reply_to else None,
                    'content': message.reply_to.content if message.reply_to else None,
                    'sender_name': message.reply_to.sender.full_name if message.reply_to else None,
                } if message.reply_to else None
            }
        })

    except Exception as e:
        logger.error(f"Error in send_message: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to send message'})


@login_required
def get_chats_api(request):
    """API endpoint to get user's chats for the slide-in panel"""
    try:
        user_chats = Chat.objects.filter(
            participants=request.user).select_related('admin')

        chats_data = []
        for chat in user_chats:
            # Get last message
            last_message = chat.messages.order_by('-timestamp').first()
            last_msg_content = last_message.content if last_message else 'No messages yet'
            if last_message and last_message.message_type == 'image':
                last_msg_content = 'Sent an image'

            # Get unread count
            unread_count = chat.messages.filter(
                ~Q(read_by=request.user)
            ).exclude(sender=request.user).count()

            # Get other participant for private chats
            other_user = None
            if chat.chat_type == 'private':
                other_user = chat.participants.exclude(
                    id=request.user.id).first()

            chat_info = {
                'id': chat.id,
                'name': chat.name if chat.chat_type == 'group' else (other_user.full_name if other_user else 'Unknown'),
                'is_group': chat.chat_type == 'group',
                'last_message': last_msg_content,
                'unread_count': unread_count,
                'avatar': other_user.profile_picture_url if other_user else None,
                'initials': other_user.initials if other_user else (chat.name[:1].upper() if chat.name else 'G')
            }
            chats_data.append(chat_info)

        return JsonResponse({'success': True, 'chats': chats_data})
    except Exception as e:
        logger.error(f"Error in get_chats_api: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to load chats'})


@login_required
@require_POST
def create_chat(request):
    try:
        data = json.loads(request.body)
        username = data.get('username')

        other_user = get_object_or_404(CustomUser, username=username)

        if other_user == request.user:
            return JsonResponse({'success': False, 'error': 'Cannot create chat with yourself'})

        # Check if chat already exists
        existing_chat = Chat.objects.filter(
            participants=request.user,
            chat_type='private'
        ).filter(participants=other_user).first()

        if existing_chat:
            return JsonResponse({
                'success': True,
                'chat_id': existing_chat.id,
                'exists': True
            })

        # Create new chat
        chat = Chat.objects.create(chat_type='private')
        chat.participants.add(request.user, other_user)

        return JsonResponse({
            'success': True,
            'chat_id': chat.id,
            'exists': False
        })

    except Exception as e:
        logger.error(f"Error in create_chat: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to create chat'})


@login_required
@require_POST
def create_group(request):
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        max_participants = int(data.get('max_participants', 50))
        is_public = data.get('is_public', False)

        if not name:
            return JsonResponse({'success': False, 'error': 'Group name is required'})

        if len(name) > 100:
            return JsonResponse({'success': False, 'error': 'Group name too long'})

        if max_participants < 2 or max_participants > 500:
            return JsonResponse({'success': False, 'error': 'Max participants must be between 2 and 500'})

        # Create group
        chat = Chat.objects.create(
            chat_type='group',
            name=name,
            description=description,
            admin=request.user,
            max_participants=max_participants,
            is_public=is_public
        )

        # Add creator as participant
        chat.participants.add(request.user)

        # Create system message
        Message.objects.create(
            chat=chat,
            content=f'{request.user.full_name} created the group',
            message_type='system'
        )

        return JsonResponse({
            'success': True,
            'group': {
                'id': chat.id,
                'name': chat.name,
                'invite_link': chat.invite_link,
                'invite_code': chat.invite_code,
            }
        })

    except Exception as e:
        logger.error(f"Error in create_group: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to create group'})


@login_required
@require_POST
def join_group_api(request):
    """API endpoint to join a group by ID (for public groups from discover page)"""
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')

        if not group_id:
            return JsonResponse({'success': False, 'error': 'Group ID is required'})

        chat = Chat.objects.filter(id=group_id, chat_type='group').first()

        if not chat:
            return JsonResponse({'success': False, 'error': 'Group not found'})

        # Check if already a member
        if chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'success': False, 'error': 'You are already a member of this group'})

        # Check if group is full
        if not chat.can_add_participants:
            return JsonResponse({'success': False, 'error': 'This group is full'})

        # For public groups, add directly
        if chat.is_public:
            chat.participants.add(request.user)

            # Create system message
            Message.objects.create(
                chat=chat,
                content=f'{request.user.full_name} joined the group',
                message_type='system'
            )

            return JsonResponse({
                'success': True,
                'chat_id': chat.id,
                'message': f'You have joined {chat.name}!'
            })
        else:
            # For private groups, create a join request
            existing_request = GroupJoinRequest.objects.filter(
                group=chat,
                user=request.user,
                status='pending'
            ).first()

            if existing_request:
                return JsonResponse({'success': False, 'error': 'You already have a pending request'})

            GroupJoinRequest.objects.create(
                group=chat,
                user=request.user,
                message=''
            )

            return JsonResponse({
                'success': True,
                'pending': True,
                'message': f'Join request sent to {chat.name}'
            })

    except Exception as e:
        logger.error(f"Error in join_group_api: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to join group'})


@login_required
def join_group_view(request, invite_code):
    chat = get_object_or_404(Chat, invite_code=invite_code, chat_type='group')

    # Check if already a member
    already_member = chat.participants.filter(id=request.user.id).exists()
    if already_member:
        return render(request, 'chat/join_group.html', {'chat': chat, 'already_member': True})

    if not chat.can_add_participants:
        messages.error(request, f'{chat.name} is full')
        return redirect('dashboard')

    # Handle POST - actually join or send request
    if request.method == 'POST':
        if chat.is_public:
            # Public groups - join directly
            chat.participants.add(request.user)

            # Create system message
            Message.objects.create(
                chat=chat,
                content=f'{request.user.full_name} joined the group',
                message_type='system'
            )

            messages.success(request, f'You have joined {chat.name}!')
            return redirect('chat_detail', chat_id=chat.id)
        else:
            # Private groups - send join request
            existing_request = GroupJoinRequest.objects.filter(
                group=chat,
                user=request.user,
                status='pending'
            ).first()

            if existing_request:
                messages.info(
                    request, f'You already have a pending request to join {chat.name}')
                return redirect('dashboard')

            message = request.POST.get('message', '').strip()

            GroupJoinRequest.objects.create(
                group=chat,
                user=request.user,
                message=message
            )

            messages.success(request, f'Join request sent to {chat.name}.')
            return redirect('dashboard')

    # GET request - show the join confirmation page
    return render(request, 'chat/join_group.html', {'chat': chat, 'already_member': False})


def _get_explore_content_batch(page=1, per_page=15):
    """Helper function to get a batch of explore content with pagination
    Optimized for production - only loads needed items from database
    Only shows scribes with images/code (no text-only scribes)"""
    import random
    from django.core.cache import cache

    # Create a cache key for the shuffled order (changes every hour)
    cache_key = 'explore_order_' + str(int(__import__('time').time()) // 3600)

    # Try to get cached order from Redis/Cache
    shuffled_ids = cache.get(cache_key)

    if shuffled_ids is None:
        # Cache miss - rebuild the shuffled order
        # Get only the IDs and types (lightweight)
        # Show scribes with actual images or code bundles (excluding empty/text-only)
        scribes_ids = list(
            Tweet.objects.filter(
                # Has actual image (non-empty)
                Q(image__isnull=False, image__gt='') |
                Q(code_bundle__isnull=False) |           # Has code bundle
                Q(code_html__isnull=False)              # Has code HTML
            )
            .values_list('id', flat=True)
            .order_by('-timestamp'))

        reels_ids = list(
            Reel.objects.values_list('id', flat=True)
            .order_by('-created_at'))

        # Create combined list of (id, type) tuples
        shuffled_ids = [(sid, 'scribe') for sid in scribes_ids] + \
                       [(rid, 'reel') for rid in reels_ids]

        # Shuffle
        random.shuffle(shuffled_ids)

        # Cache for 1 hour
        cache.set(cache_key, shuffled_ids, 3600)

    # Get only the items needed for this page
    offset = (page - 1) * per_page
    page_ids = shuffled_ids[offset:offset + per_page]

    if not page_ids:
        return []

    # Fetch only the needed items from database
    paginated = []
    for item_id, item_type in page_ids:
        if item_type == 'scribe':
            obj = Tweet.objects.select_related('user').get(id=item_id)
        else:
            obj = Reel.objects.select_related('user').get(id=item_id)

        paginated.append({
            'type': item_type,
            'object': obj,
            'sort_key': random.random()
        })

    return paginated


@login_required
def discover_groups_view(request):
    """Explore page: show random scribes, omzo reels, people, and groups with pagination."""

    # Get first page (15 items)
    mixed_content = _get_explore_content_batch(page=1, per_page=15)

    # Get user's chats for the DM panel in navbar
    private_chats = Chat.objects.filter(
        participants=request.user,
        chat_type='private'
    ).order_by('-updated_at').distinct()

    group_chats = Chat.objects.filter(
        participants=request.user,
        chat_type='group'
    ).order_by('-updated_at').distinct()

    # Get unread message count for the DM badge
    unread_message_count = Chat.objects.filter(
        participants=request.user,
        messages__is_read=False
    ).exclude(messages__sender=request.user).distinct().count()

    # Get story inbox count
    story_inbox_count = StoryReply.objects.filter(
        story__user=request.user,
        is_read=False
    ).count()

    context = {
        'mixed_content': mixed_content,
        'current_user': request.user,
        'private_chats': private_chats,
        'group_chats': group_chats,
        'unread_message_count': unread_message_count,
        'story_inbox_count': story_inbox_count,
    }

    return render(request, 'chat/discover_groups.html', context)


@login_required
def load_more_explore_content(request):
    """API endpoint for infinite scroll on explore page"""
    try:
        page = int(request.GET.get('page', 2))
        per_page = 15

        mixed_content = _get_explore_content_batch(
            page=page, per_page=per_page)

        # Serialize to JSON
        data = []
        for item in mixed_content:
            obj = item['object']
            item_data = {'type': item['type']}

            if item['type'] == 'scribe':
                item_data.update({
                    'id': obj.id,
                    'content': obj.content,
                    'image_url': obj.image.url if obj.image else None,
                    'code_bundle': obj.code_bundle,
                    'code_html': obj.code_html,
                    'code_css': obj.code_css,
                    'code_js': obj.code_js,
                    'user': {
                        'username': obj.user.username,
                        'full_name': obj.user.full_name,
                    }
                })
            elif item['type'] == 'reel':
                item_data.update({
                    'id': obj.id,
                    'caption': obj.caption,
                    'video_url': obj.video_file.url if obj.video_file else None,
                    'user': {
                        'username': obj.user.username,
                        'full_name': obj.user.full_name,
                    }
                })
            elif item['type'] == 'person':
                item_data.update({
                    'username': obj.username,
                    'full_name': obj.full_name,
                    'profile_picture': obj.profile_picture.url if obj.profile_picture else None,
                })
            elif item['type'] == 'group':
                item_data.update({
                    'id': obj.id,
                    'name': obj.name,
                })

            data.append(item_data)

        has_next = len(data) >= per_page

        return JsonResponse({
            'success': True,
            'content': data,
            'has_next': has_next,
            'page': page
        })

    except Exception as e:
        logger.error(f"Error in load_more_explore_content: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to load content'})


@login_required
@require_POST
def manage_join_request(request):
    try:
        data = json.loads(request.body)
        request_id = data.get('request_id')
        action = data.get('action')

        if action not in ['approve', 'reject']:
            return JsonResponse({'success': False, 'error': 'Invalid action'})

        join_request = get_object_or_404(
            GroupJoinRequest,
            id=request_id,
            group__admin=request.user,
            status='pending'
        )

        if action == 'approve':
            if not join_request.group.can_add_participants:
                return JsonResponse({'success': False, 'error': 'Group is full'})

            join_request.group.participants.add(join_request.user)
            join_request.status = 'approved'

            # Create system message
            Message.objects.create(
                chat=join_request.group,
                content=f'{join_request.user.full_name} joined the group',
                message_type='system'
            )
        else:
            join_request.status = 'rejected'

        join_request.responded_at = timezone.now()
        join_request.responded_by = request.user
        join_request.save()

        return JsonResponse({
            'success': True,
            'action': action,
            'username': join_request.user.full_name
        })

    except Exception as e:
        logger.error(f"Error in manage_join_request: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to manage join request'})


@login_required
@require_POST
def delete_message_for_me(request, message_id):
    """Delete message for current user only (hide it)"""
    try:
        message = Message.objects.get(id=message_id)
        # Check if user is participant in the chat
        if not message.chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)

        # Create deletion record for this user
        MessageDeletion.objects.get_or_create(
            message=message,
            user=request.user
        )
        return JsonResponse({'status': 'success'})
    except Message.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Message not found'}, status=404)


@login_required
@require_POST
def delete_message_for_everyone(request, message_id):
    """Delete message for everyone (only sender can do this)"""
    try:
        message = Message.objects.get(id=message_id)

        # Check if user is the sender
        if message.sender != request.user:
            return JsonResponse({'status': 'error', 'message': 'You can only delete your own messages'}, status=403)

        # Check if user is participant in the chat
        if not message.chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)

        # Delete the message completely
        message.delete()

        return JsonResponse({'status': 'success'})
    except Message.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Message not found'}, status=404)


@login_required
@require_POST
def consume_one_time_message(request, message_id):
    """Consume a one-time message"""
    try:
        message = Message.objects.get(
            id=message_id, chat__participants=request.user, one_time=True)

        # Check if already consumed
        if message.consumed_at:
            return JsonResponse({'success': False, 'error': 'Message already consumed'})

        # Mark as consumed
        message.consumed_at = timezone.now()
        message.save(update_fields=['consumed_at'])

        return JsonResponse({
            'success': True,
            'content': message.content,
            'media_url': message.media_url,
            'media_type': message.media_type,
            'media_filename': message.media_filename,
            'consumed_at': message.consumed_at.isoformat()
        })

    except Message.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Message not found or not accessible'})
    except Exception as e:
        logger.error(f"Error consuming message: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to consume message'})


@login_required
@require_POST
def mark_message_read(request, message_id):
    """Mark a message as read"""
    try:
        message = Message.objects.get(
            id=message_id, chat__participants=request.user)

        # Mark as read
        MessageRead.objects.get_or_create(
            message=message,
            user=request.user,
            defaults={'read_at': timezone.now()}
        )

        return JsonResponse({'success': True})

    except Message.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Message not found'})
    except Exception as e:
        logger.error(f"Error marking message read: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to mark message read'})


@login_required
@require_POST
def react_to_message(request, message_id):
    """Add or remove emoji reaction to a message"""
    try:
        data = json.loads(request.body)
        emoji = data.get('emoji', '').strip()

        if not emoji:
            return JsonResponse({'status': 'error', 'message': 'Emoji is required'})

        # Get the message
        message = get_object_or_404(Message, id=message_id)

        # Check if user is participant in the chat
        if not message.chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'})

        # Check if reaction already exists
        existing_reaction = MessageReaction.objects.filter(
            message=message,
            user=request.user,
            emoji=emoji
        ).first()

        if existing_reaction:
            # Remove reaction
            existing_reaction.delete()
            return JsonResponse({
                'status': 'removed',
                'emoji': emoji,
                'message_id': message_id
            })
        else:
            # Add reaction
            MessageReaction.objects.create(
                message=message,
                user=request.user,
                emoji=emoji
            )
            return JsonResponse({
                'status': 'added',
                'emoji': emoji,
                'message_id': message_id
            })

    except Exception as e:
        logger.error(f"Error reacting to message: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)})


@login_required
@require_POST
def update_typing_status(request, chat_id):
    """Update typing status for a chat"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)
        is_typing = request.POST.get('is_typing', 'false').lower() == 'true'

        # Store typing status in cache (simple implementation)
        from django.core.cache import cache
        cache_key = f'chat_{chat_id}_typing'

        typing_users = cache.get(cache_key, set())
        if is_typing:
            typing_users.add(request.user.id)
        else:
            typing_users.discard(request.user.id)

        # Set cache with 5 second expiry for more responsive typing indicators
        cache.set(cache_key, typing_users, 5)

        return JsonResponse({'success': True})

    except Exception as e:
        logger.error(f"Error updating typing status: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to update typing status'})


@login_required
def get_typing_status(request, chat_id):
    """Get current typing users for a chat"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        from django.core.cache import cache
        cache_key = f'chat_{chat_id}_typing'
        typing_user_ids = cache.get(cache_key, set())

        typing_users = []
        for user_id in typing_user_ids:
            try:
                user = CustomUser.objects.get(id=user_id)
                if user != request.user:  # Don't show own typing status
                    typing_users.append({
                        'id': user.id,
                        'name': user.full_name
                    })
            except CustomUser.DoesNotExist:
                pass

        return JsonResponse({'typing_users': typing_users})

    except Exception as e:
        logger.error(f"Error getting typing status: {str(e)}")
        return JsonResponse({'typing_users': []})


@login_required
@require_POST
def edit_message(request, message_id):
    """Edit a message (within 15 minute window)"""
    try:
        message = get_object_or_404(Message, id=message_id)

        # Check if user is the sender
        if message.sender != request.user:
            return JsonResponse({'success': False, 'error': 'You can only edit your own messages'})

        # Check if message can still be edited (15 minute limit)
        if not message.can_be_edited:
            return JsonResponse({'success': False, 'error': 'Message can no longer be edited (15 minute limit exceeded)'})

        # Check if it's a media-only message
        if message.message_type == 'media' and not message.content:
            return JsonResponse({'success': False, 'error': 'Cannot edit media-only messages'})

        data = json.loads(request.body)
        new_content = data.get('content', '').strip()

        if not new_content:
            return JsonResponse({'success': False, 'error': 'Message content cannot be empty'})

        if len(new_content) > 5000:
            return JsonResponse({'success': False, 'error': 'Message too long (max 5000 characters)'})

        # Store original content if first edit
        if not message.is_edited:
            message.original_content = message.content

        # Update message
        message.content = new_content
        message.is_edited = True
        message.edited_at = timezone.now()
        message.save()

        return JsonResponse({
            'success': True,
            'message': {
                'id': message.id,
                'content': message.content,
                'is_edited': message.is_edited,
                'edited_at': message.edited_at.isoformat() if message.edited_at else None
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'})
    except Exception as e:
        logger.error(f"Error editing message: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to edit message'})


@login_required
@require_POST
def pin_message(request, message_id):
    """Toggle pin/unpin a message in a chat (admin only for groups, any participant for private)"""
    try:
        message = get_object_or_404(Message, id=message_id)
        chat = message.chat

        # Check if user is participant
        if not chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'success': False, 'error': 'You are not a participant of this chat'})

        # For group chats, only admin can pin/unpin
        if chat.chat_type == 'group' and chat.admin != request.user:
            return JsonResponse({'success': False, 'error': 'Only group admin can pin/unpin messages'})

        # Toggle pin status
        if message.is_pinned:
            # Unpin the message
            message.is_pinned = False
            message.pinned_at = None
            message.pinned_by = None
            message.save()

            return JsonResponse({
                'success': True,
                'pinned': False,
                'message_id': message.id
            })
        else:
            # Pin the message
            message.is_pinned = True
            message.pinned_at = timezone.now()
            message.pinned_by = request.user
            message.save()

            return JsonResponse({
                'success': True,
                'pinned': True,
                'message_id': message.id,
                'pinned_at': message.pinned_at.isoformat(),
                'pinned_by': request.user.full_name
            })

    except Exception as e:
        logger.error(f"Error toggling pin message: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to toggle pin'})


@login_required
@require_POST
def unpin_message(request, message_id):
    """Unpin a message in a chat"""
    try:
        message = get_object_or_404(Message, id=message_id)
        chat = message.chat

        # Check if user is participant
        if not chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'success': False, 'error': 'You are not a participant of this chat'})

        # For group chats, only admin can unpin
        if chat.chat_type == 'group' and chat.admin != request.user:
            return JsonResponse({'success': False, 'error': 'Only group admin can unpin messages'})

        # Unpin the message
        message.is_pinned = False
        message.pinned_at = None
        message.pinned_by = None
        message.save()

        return JsonResponse({
            'success': True,
            'message': {
                'id': message.id,
                'is_pinned': False
            }
        })

    except Exception as e:
        logger.error(f"Error unpinning message: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to unpin message'})


@login_required
def get_pinned_messages(request, chat_id):
    """Get all pinned messages in a chat"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        pinned_messages = Message.objects.filter(
            chat=chat,
            is_pinned=True
        ).select_related('sender', 'pinned_by').order_by('-pinned_at')

        messages_data = []
        for msg in pinned_messages:
            messages_data.append({
                'id': msg.id,
                'content': msg.content[:200] + '...' if len(msg.content) > 200 else msg.content,
                'sender': {
                    'id': msg.sender.id if msg.sender else None,
                    'username': msg.sender.username if msg.sender else 'System',
                    'full_name': msg.sender.full_name if msg.sender else 'System'
                },
                'timestamp': msg.timestamp.isoformat(),
                'pinned_at': msg.pinned_at.isoformat() if msg.pinned_at else None,
                'pinned_by': msg.pinned_by.full_name if msg.pinned_by else None,
                'media_type': msg.media_type,
                'has_media': msg.has_media
            })

        return JsonResponse({
            'success': True,
            'pinned_messages': messages_data,
            'count': len(messages_data)
        })

    except Exception as e:
        logger.error(f"Error getting pinned messages: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get pinned messages'})


@login_required
@require_POST
def pin_chat(request, chat_id):
    """Pin a chat/conversation to the top"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        # Check if already pinned
        if PinnedChat.objects.filter(user=request.user, chat=chat).exists():
            return JsonResponse({'success': False, 'error': 'Chat is already pinned'})

        # Limit pinned chats to 5
        if PinnedChat.objects.filter(user=request.user).count() >= 5:
            return JsonResponse({'success': False, 'error': 'You can only pin up to 5 chats'})

        PinnedChat.objects.create(user=request.user, chat=chat)

        return JsonResponse({'success': True, 'message': 'Chat pinned successfully'})

    except Exception as e:
        logger.error(f"Error pinning chat: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to pin chat'})


@login_required
@require_POST
def unpin_chat(request, chat_id):
    """Unpin a chat/conversation"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        pinned = PinnedChat.objects.filter(user=request.user, chat=chat)
        if not pinned.exists():
            return JsonResponse({'success': False, 'error': 'Chat is not pinned'})

        pinned.delete()

        return JsonResponse({'success': True, 'message': 'Chat unpinned successfully'})

    except Exception as e:
        logger.error(f"Error unpinning chat: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to unpin chat'})


@login_required
@require_POST
def toggle_star_message(request, message_id):
    """Toggle star/unstar a message for the current user"""
    try:
        message = get_object_or_404(Message, id=message_id)
        chat = message.chat

        # Verify user is participant
        if request.user not in chat.participants.all():
            return JsonResponse({'success': False, 'error': 'Not authorized'}, status=403)

        starred, created = StarredMessage.objects.get_or_create(
            user=request.user,
            message=message
        )

        if not created:
            # Already starred, so unstar it
            starred.delete()
            return JsonResponse({
                'success': True,
                'is_starred': False,
                'message': 'Message unstarred'
            })

        return JsonResponse({
            'success': True,
            'is_starred': True,
            'message': 'Message starred'
        })

    except Exception as e:
        logger.error(f"Error toggling star: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to toggle star'})


@login_required
def get_starred_messages(request):
    """Get all starred messages for the current user"""
    try:
        starred = StarredMessage.objects.filter(user=request.user).select_related(
            'message', 'message__sender', 'message__chat'
        )

        messages_data = []
        for star in starred:
            msg = star.message
            messages_data.append({
                'id': msg.id,
                'content': msg.content,
                'sender': {
                    'id': msg.sender.id if msg.sender else None,
                    'username': msg.sender.username if msg.sender else 'System',
                    'full_name': msg.sender.full_name if msg.sender else 'System'
                },
                'chat_id': msg.chat.id,
                'chat_name': msg.chat.name if msg.chat.chat_type == 'group' else None,
                'timestamp': msg.timestamp.strftime('%b %d, %Y %I:%M %p'),
                'starred_at': star.starred_at.strftime('%b %d, %Y %I:%M %p'),
                'media_type': msg.media_type,
                'media_url': msg.media_url
            })

        return JsonResponse({
            'success': True,
            'starred_messages': messages_data,
            'count': len(messages_data)
        })

    except Exception as e:
        logger.error(f"Error getting starred messages: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get starred messages'})


@login_required
def is_message_starred(request, message_id):
    """Check if a message is starred by current user"""
    try:
        is_starred = StarredMessage.objects.filter(
            user=request.user,
            message_id=message_id
        ).exists()

        return JsonResponse({'success': True, 'is_starred': is_starred})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
def mark_messages_read(request, chat_id):
    """Mark all messages in a chat as read by current user"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        # Get all unread messages from other users
        unread_messages = Message.objects.filter(
            chat=chat
        ).exclude(
            sender=request.user
        ).exclude(
            read_receipts__user=request.user
        )

        # Create read receipts for each
        read_receipts = []
        for msg in unread_messages:
            read_receipts.append(MessageRead(message=msg, user=request.user))

        if read_receipts:
            MessageRead.objects.bulk_create(
                read_receipts, ignore_conflicts=True)

        return JsonResponse({
            'success': True,
            'marked_count': len(read_receipts)
        })

    except Exception as e:
        logger.error(f"Error marking messages read: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to mark messages read'})


@login_required
def get_message_read_status(request, message_id):
    """Get read receipt status for a specific message"""
    try:
        message = get_object_or_404(Message, id=message_id)

        # Only sender can see read receipts
        if message.sender != request.user:
            return JsonResponse({'success': False, 'error': 'Not authorized'}, status=403)

        read_receipts = MessageRead.objects.filter(
            message=message).select_related('user')

        readers = []
        for receipt in read_receipts:
            readers.append({
                'user_id': receipt.user.id,
                'username': receipt.user.username,
                'full_name': receipt.user.full_name,
                'read_at': receipt.read_at.strftime('%b %d, %I:%M %p')
            })

        # Get total participants (excluding sender)
        total_recipients = message.chat.participants.exclude(
            id=request.user.id).count()

        return JsonResponse({
            'success': True,
            'readers': readers,
            'read_count': len(readers),
            'total_recipients': total_recipients,
            'all_read': len(readers) >= total_recipients
        })

    except Exception as e:
        logger.error(f"Error getting read status: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get read status'})


@login_required
def get_chat_read_status(request, chat_id):
    """Get read status for all messages in a chat (for current user's messages)"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        # Get user's messages that have been read
        user_messages = Message.objects.filter(
            chat=chat,
            sender=request.user
        ).annotate(
            read_count=Count('read_receipts')
        )

        total_recipients = chat.participants.exclude(
            id=request.user.id).count()

        read_status = {}
        for msg in user_messages:
            read_status[str(msg.id)] = {
                'read_count': msg.read_count,
                'total_recipients': total_recipients,
                'status': 'read' if msg.read_count >= total_recipients else ('delivered' if msg.read_count > 0 else 'sent')
            }

        return JsonResponse({
            'success': True,
            'read_status': read_status
        })

    except Exception as e:
        logger.error(f"Error getting chat read status: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get read status'})


@login_required
def get_user_online_status(request, user_id):
    """Get online status of a specific user"""
    try:
        user = get_object_or_404(CustomUser, id=user_id)

        # A user is considered online only if:
        # 1. is_online flag is True AND
        # 2. last_seen is within the last 15 seconds (indicating active session)
        is_truly_online = False
        if user.is_online and user.last_seen:
            time_since_last_seen = timezone.now() - user.last_seen
            is_truly_online = time_since_last_seen < timedelta(seconds=15)

            # If is_online is True but last_seen is too old, mark them offline
            if not is_truly_online and user.is_online:
                user.is_online = False
                user.save(update_fields=['is_online'])

        # Calculate last seen display
        if is_truly_online:
            last_seen_display = "Online"
        elif user.last_seen:
            time_diff = timezone.now() - user.last_seen
            if time_diff.days > 0:
                last_seen_display = f"{time_diff.days}d ago"
            elif time_diff.seconds >= 3600:
                last_seen_display = f"{time_diff.seconds // 3600}h ago"
            elif time_diff.seconds >= 60:
                last_seen_display = f"{time_diff.seconds // 60}m ago"
            else:
                last_seen_display = "Just now"
        else:
            last_seen_display = "Unknown"

        return JsonResponse({
            'success': True,
            'user_id': user.id,
            'username': user.username,
            'is_online': is_truly_online,
            'last_seen': user.last_seen.isoformat() if user.last_seen else None,
            'last_seen_display': last_seen_display
        })

    except Exception as e:
        logger.error(f"Error getting user online status: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get online status'})


@login_required
@require_http_methods(["POST"])
def user_heartbeat(request):
    """Update user's online status - heartbeat endpoint"""
    try:
        request.user.last_seen = timezone.now()
        request.user.is_online = True
        request.user.save(update_fields=['last_seen', 'is_online'])

        return JsonResponse({
            'success': True,
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Heartbeat error for user {request.user.id}: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Heartbeat failed'})


@login_required
def get_chat_participant_status(request, chat_id):
    """Get online status of all participants in a chat (for private chats, returns the other user's status)"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        # Update current user's last_seen to mark them as active
        request.user.last_seen = timezone.now()
        request.user.is_online = True
        request.user.save(update_fields=['last_seen', 'is_online'])

        participants_status = []
        for participant in chat.participants.exclude(id=request.user.id):
            # A user is considered online only if:
            # 1. is_online flag is True AND
            # 2. last_seen is within the last 15 seconds (indicating active session)
            is_truly_online = False
            if participant.is_online and participant.last_seen:
                time_since_last_seen = timezone.now() - participant.last_seen
                is_truly_online = time_since_last_seen < timedelta(seconds=15)

                # If is_online is True but last_seen is too old, mark them offline
                if not is_truly_online and participant.is_online:
                    participant.is_online = False
                    participant.save(update_fields=['is_online'])

            # Calculate last seen display
            if is_truly_online:
                last_seen_display = "Online"
            elif participant.last_seen:
                time_diff = timezone.now() - participant.last_seen
                if time_diff.days > 0:
                    last_seen_display = f"Last seen {time_diff.days}d ago"
                elif time_diff.seconds >= 3600:
                    last_seen_display = f"Last seen {time_diff.seconds // 3600}h ago"
                elif time_diff.seconds >= 60:
                    last_seen_display = f"Last seen {time_diff.seconds // 60}m ago"
                else:
                    last_seen_display = "Last seen just now"
            else:
                last_seen_display = "Never seen online"

            participants_status.append({
                'user_id': participant.id,
                'username': participant.username,
                'full_name': participant.full_name,
                'is_online': is_truly_online,
                'last_seen': participant.last_seen.isoformat() if participant.last_seen else None,
                'last_seen_display': last_seen_display
            })

        return JsonResponse({
            'success': True,
            'chat_id': chat_id,
            'chat_type': chat.chat_type,
            'participants': participants_status
        })

    except Exception as e:
        logger.error(f"Error getting chat participant status: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get participant status'})


@login_required
def get_group_details(request, chat_id):
    """Get detailed information about a group chat"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, chat_type='group')

        # Check if user is a participant
        if not chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'success': False, 'error': 'You are not a member of this group'}, status=403)

        is_admin = chat.admin == request.user

        # Get all participants with their details
        members = []
        for participant in chat.participants.all():
            # Check if truly online (with 15 second threshold)
            is_truly_online = participant.is_online and participant.last_seen and (
                timezone.now() - participant.last_seen).total_seconds() < 15

            members.append({
                'id': participant.id,
                'username': participant.username,
                'full_name': participant.full_name,
                'profile_picture': participant.profile_picture_url,
                'is_admin': participant == chat.admin,
                'is_online': is_truly_online,
            })

        # Sort: Admin first, then online users, then alphabetically
        members.sort(key=lambda x: (
            not x['is_admin'], not x['is_online'], x['full_name'].lower()))

        return JsonResponse({
            'success': True,
            'group': {
                'id': chat.id,
                'name': chat.name,
                'description': chat.description or '',
                'is_public': chat.is_public,
                'max_participants': chat.max_participants,
                'participant_count': chat.participant_count,
                'invite_code': chat.invite_code,
                'invite_link': chat.invite_link,
                'created_at': chat.created_at.strftime('%B %d, %Y'),
                'is_admin': is_admin,
            },
            'members': members
        })

    except Exception as e:
        logger.error(f"Error getting group details: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get group details'})


@login_required
@require_POST
def update_group_settings(request, chat_id):
    """Update group settings (admin only)"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, chat_type='group')

        # Check if user is admin
        if chat.admin != request.user:
            return JsonResponse({'success': False, 'error': 'Only the group admin can update settings'}, status=403)

        data = json.loads(request.body)

        # Update fields if provided
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return JsonResponse({'success': False, 'error': 'Group name cannot be empty'})
            if len(name) > 100:
                return JsonResponse({'success': False, 'error': 'Group name is too long (max 100 characters)'})
            chat.name = name

        if 'description' in data:
            description = data['description'].strip()
            if len(description) > 500:
                return JsonResponse({'success': False, 'error': 'Description is too long (max 500 characters)'})
            chat.description = description

        if 'is_public' in data:
            chat.is_public = bool(data['is_public'])

        if 'max_participants' in data:
            max_participants = int(data['max_participants'])
            if max_participants < chat.participant_count:
                return JsonResponse({'success': False, 'error': f'Cannot set max lower than current member count ({chat.participant_count})'})
            if max_participants < 2 or max_participants > 500:
                return JsonResponse({'success': False, 'error': 'Max participants must be between 2 and 500'})
            chat.max_participants = max_participants

        chat.save()

        # Create system message for name change
        if 'name' in data:
            Message.objects.create(
                chat=chat,
                content=f'{request.user.full_name} changed the group name to "{chat.name}"',
                message_type='system'
            )

        return JsonResponse({
            'success': True,
            'message': 'Group settings updated successfully',
            'group': {
                'name': chat.name,
                'description': chat.description,
                'is_public': chat.is_public,
                'max_participants': chat.max_participants,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid request data'})
    except Exception as e:
        logger.error(f"Error updating group settings: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to update group settings'})


@login_required
@require_POST
def remove_group_member(request, chat_id):
    """Remove a member from the group (admin only)"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, chat_type='group')

        # Check if user is admin
        if chat.admin != request.user:
            return JsonResponse({'success': False, 'error': 'Only the group admin can remove members'}, status=403)

        data = json.loads(request.body)
        user_id = data.get('user_id')

        if not user_id:
            return JsonResponse({'success': False, 'error': 'User ID is required'})

        # Cannot remove yourself (admin) - use leave group instead
        if user_id == request.user.id:
            return JsonResponse({'success': False, 'error': 'Admin cannot remove themselves. Use leave group instead.'})

        # Get the member to remove
        member = get_object_or_404(CustomUser, id=user_id)

        # Check if member is in the group
        if not chat.participants.filter(id=user_id).exists():
            return JsonResponse({'success': False, 'error': 'User is not a member of this group'})

        # Remove member
        chat.participants.remove(member)

        # Create system message
        Message.objects.create(
            chat=chat,
            content=f'{member.full_name} was removed from the group by {request.user.full_name}',
            message_type='system'
        )

        return JsonResponse({
            'success': True,
            'message': f'{member.full_name} has been removed from the group',
            'removed_user_id': user_id
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid request data'})
    except Exception as e:
        logger.error(f"Error removing group member: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to remove member'})


@login_required
@require_POST
def leave_group(request, chat_id):
    """Leave a group chat"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, chat_type='group')

        # Check if user is a participant
        if not chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'success': False, 'error': 'You are not a member of this group'}, status=403)

        is_admin = chat.admin == request.user

        # If admin is leaving, transfer admin to another member or delete group
        if is_admin:
            other_members = chat.participants.exclude(id=request.user.id)
            if other_members.exists():
                # Transfer admin to the first other member
                new_admin = other_members.first()
                chat.admin = new_admin
                chat.save()

                # Create system message
                Message.objects.create(
                    chat=chat,
                    content=f'{request.user.full_name} left the group. {new_admin.full_name} is now the admin.',
                    message_type='system'
                )
            else:
                # No other members, delete the group
                chat.delete()
                return JsonResponse({
                    'success': True,
                    'message': 'You left and the group was deleted (no members remaining)',
                    'group_deleted': True
                })
        else:
            # Non-admin leaving
            Message.objects.create(
                chat=chat,
                content=f'{request.user.full_name} left the group',
                message_type='system'
            )

        # Remove user from participants
        chat.participants.remove(request.user)

        return JsonResponse({
            'success': True,
            'message': 'You have left the group',
            'group_deleted': False
        })

    except Exception as e:
        logger.error(f"Error leaving group: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to leave group'})


@login_required
@require_POST
def regenerate_invite_code(request, chat_id):
    """Regenerate the group invite code (admin only)"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, chat_type='group')

        # Check if user is admin
        if chat.admin != request.user:
            return JsonResponse({'success': False, 'error': 'Only the group admin can regenerate invite code'}, status=403)

        # Generate new invite code
        chat.invite_code = chat.generate_invite_code()
        chat.save()

        return JsonResponse({
            'success': True,
            'invite_code': chat.invite_code,
            'invite_link': chat.invite_link
        })

    except Exception as e:
        logger.error(f"Error regenerating invite code: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to regenerate invite code'})


def get_p2p_cache():
    """Get cache backend for P2P signals - uses Redis in production, fallback to default cache"""
    from django.core.cache import cache
    return cache


@login_required
@require_POST
def p2p_send_signal(request):
    """Send a WebRTC signaling message to another user using database storage"""
    try:
        data = json.loads(request.body)
        target_user_id = data.get('target_user_id')
        chat_id = data.get('chat_id')
        # Contains type, offer/answer/candidate, fileInfo
        signal_data = data.get('signal_data')

        if not all([chat_id, signal_data]):
            return JsonResponse({'success': False, 'error': 'Missing required fields'})

        # Verify user is in the chat
        chat = get_object_or_404(Chat, id=chat_id)
        if not chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'success': False, 'error': 'Not a participant of this chat'}, status=403)

        # Import P2PSignal model
        from chat.models import P2PSignal

        # Clean up old signals first
        P2PSignal.cleanup_old_signals()

        # If target_user_id is None, send to all other participants (for calls)
        if target_user_id is None:
            others = chat.participants.exclude(id=request.user.id)
            signal_count = 0
            for target_user in others:
                P2PSignal.objects.create(
                    chat=chat,
                    sender=request.user,
                    target_user=target_user,
                    signal_data=signal_data
                )
                signal_count += 1
            logger.info(
                f"[P2P_SEND] Signal stored: {signal_data.get('type', 'unknown')} from user {request.user.id} ({request.user.full_name}) to {signal_count} users in chat {chat_id}")
        else:
            # Verify target user is in the chat
            target_user = chat.participants.filter(id=target_user_id).first()
            if not target_user:
                return JsonResponse({'success': False, 'error': 'Target user not in chat'}, status=403)

            # Store signal in database
            P2PSignal.objects.create(
                chat=chat,
                sender=request.user,
                target_user=target_user,
                signal_data=signal_data
            )
            logger.info(
                f"[P2P_SEND] Signal stored: {signal_data.get('type', 'unknown')} from user {request.user.id} ({request.user.full_name}) to user {target_user_id} in chat {chat_id}")

        return JsonResponse({'success': True})

    except Exception as e:
        logger.error(f"Error in p2p_send_signal: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to send signal'})


@login_required
def p2p_get_signals(request, chat_id):
    """Poll for pending WebRTC signals from database"""
    try:
        chat = get_object_or_404(Chat, id=chat_id)

        # Verify user is in the chat
        if not chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'success': False, 'error': 'Not a participant of this chat'}, status=403)

        # Import P2PSignal model
        from chat.models import P2PSignal

        # Get unconsumed signals for this user in this chat
        # For call signals (webrtc.*), only get recent ones (last 30 seconds) to avoid stale signals
        from datetime import timedelta
        recent_cutoff = timezone.now() - timedelta(seconds=30)

        signals = P2PSignal.objects.filter(
            chat=chat,
            target_user=request.user,
            is_consumed=False
        ).select_related('sender')

        signals_data = []
        signal_ids = []
        call_signal_ids = []  # Track call signals separately

        for signal in signals:
            signal_type = signal.signal_data.get(
                'type', '') if isinstance(signal.signal_data, dict) else ''
            is_call_signal = signal_type.startswith('webrtc.')

            # For call signals, only include recent ones
            if is_call_signal and signal.created_at < recent_cutoff:
                continue

            signals_data.append({
                'id': signal.id,  # Add signal ID for deduplication
                'sender_id': signal.sender.id,
                'sender_name': signal.sender.full_name,
                'sender_avatar': signal.sender.profile_picture_url,
                'signal': signal.signal_data,
                'timestamp': signal.created_at.isoformat()
            })
            signal_ids.append(signal.id)
            if is_call_signal:
                call_signal_ids.append(signal.id)

        # Mark signals as consumed (but keep call signals available for a bit longer)
        if signal_ids:
            # Mark non-call signals as consumed immediately
            non_call_ids = [
                sid for sid in signal_ids if sid not in call_signal_ids]
            if non_call_ids:
                P2PSignal.objects.filter(
                    id__in=non_call_ids).update(is_consumed=True)

            # For call signals, mark as consumed but keep them for a short window
            # This allows User B to receive them even if they arrive late
            if call_signal_ids:
                # Mark as consumed but don't delete yet - they'll be cleaned up by cleanup_old_signals
                P2PSignal.objects.filter(
                    id__in=call_signal_ids).update(is_consumed=True)
                logger.info(
                    f"[P2P_GET] Retrieved {len(call_signal_ids)} call signals for user {request.user.id} ({request.user.full_name}) in chat {chat_id}")

            logger.info(
                f"[P2P_GET] Total signals consumed by user {request.user.id}: {len(signal_ids)} ({len(call_signal_ids)} call signals)")

        return JsonResponse({
            'success': True,
            'signals': signals_data
        })

    except Exception as e:
        logger.error(f"Error in p2p_get_signals: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get signals'})


@login_required
@require_POST
def send_call_notification(request):
    """Send call notification to other participants via HTTP (fallback if WebSocket fails)"""
    try:
        data = json.loads(request.body)
        chat_id = data.get('chat_id')
        audio_only = data.get('audio_only', False)

        if not chat_id:
            return JsonResponse({'success': False, 'error': 'Missing chat_id'})

        chat = get_object_or_404(Chat, id=chat_id)
        if not chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'success': False, 'error': 'Not a participant'}, status=403)

        # Get caller details
        caller_name = request.user.full_name
        caller_avatar = request.user.profile_picture_url

        # Get other participants
        others = chat.participants.exclude(id=request.user.id)

        # Send notification via channel layer (NotifyConsumer)
        channel_layer = get_channel_layer()
        for other_user in others:
            async_to_sync(channel_layer.group_send)(
                f'user_notify_{other_user.id}',
                {
                    'type': 'notify.call',
                    'from_user_id': request.user.id,
                    'chat_id': chat_id,
                    'audio_only': audio_only,
                    'from_full_name': caller_name,
                    'from_avatar': caller_avatar,
                }
            )

        logger.info(
            f"Call notification sent via HTTP for chat {chat_id} to {others.count()} users")
        return JsonResponse({'success': True, 'notified': others.count()})

    except Exception as e:
        logger.error(f"Error sending call notification: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_chat_participants_for_p2p(request, chat_id):
    """Get list of chat participants for P2P file sharing"""
    try:
        chat = get_object_or_404(Chat, id=chat_id)

        # Verify user is in the chat
        if not chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'success': False, 'error': 'Not a participant of this chat'}, status=403)

        # Update the requesting user's online status (heartbeat)
        request.user.last_seen = timezone.now()
        request.user.is_online = True
        request.user.save(update_fields=['last_seen', 'is_online'])

        participants = []
        for p in chat.participants.exclude(id=request.user.id):
            # Refresh from database to get latest status
            p.refresh_from_db()
            # Check if truly online
            is_online = p.is_online and p.last_seen and (
                timezone.now() - p.last_seen).total_seconds() < 15
            participants.append({
                'id': p.id,
                'username': p.username,
                'full_name': p.full_name,
                'profile_picture': p.profile_picture_url,
                'is_online': is_online
            })

        return JsonResponse({
            'success': True,
            'chat_type': chat.chat_type,
            'participants': participants
        })

    except Exception as e:
        logger.error(f"Error getting participants for P2P: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get participants'})
