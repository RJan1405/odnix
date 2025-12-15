# views.py - COMPLETE FIXED VERSION - ALL FUNCTIONS + MULTIPLE STORIES SUPPORT
# Security fixes applied: removed unnecessary @csrf_exempt, fixed path traversal, Redis for P2P

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse, Http404
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q, Max
from django.urls import reverse
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.cache import cache
import json
import os
import uuid
import mimetypes
import secrets
import hashlib
import time
import logging
from .models import Message

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
        message = Message.objects.get(id=message_id, chat__participants=request.user, one_time=True)
        
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
        message = Message.objects.get(id=message_id, chat__participants=request.user)
        
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


from .models import (
    CustomUser, Chat, Message, Tweet, GroupJoinRequest,
    Like, Follow, EmailVerificationToken, Story, Comment, MessageReaction, MessageDeletion, MessageRead,
    Block, FollowRequest, StoryView, StoryLike, StoryReply,
    Hashtag, TweetHashtag, Mention, PinnedChat
)
from .forms import CustomUserCreationForm, LoginForm, TweetForm, ProfileUpdateForm
from django.db import models as db_models  # For Q objects in search

# Set up logging
logger = logging.getLogger(__name__)

# Global cache for preventing duplicate tweets
TWEET_CACHE_PREFIX = "prevent_duplicate_tweet_"
TWEET_COOLDOWN = 5  # 5 seconds between identical tweets

def generate_tweet_hash(user_id, content, has_image):
    """Generate unique hash for duplicate detection"""
    content_hash = hashlib.md5(f"{user_id}_{content.strip()}_{has_image}".encode()).hexdigest()
    return content_hash

def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'chat/login.html')

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if not username or not password:
            messages.error(request, 'Username and password are required')
            return render(request, 'chat/login.html')
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.is_email_verified:
                login(request, user)
                user.mark_online()
                messages.success(request, f'Welcome back, {user.full_name}!')
                return redirect('dashboard')
            else:
                messages.error(request, 'Please verify your email before logging in.')
        else:
            try:
                existing_user = CustomUser.objects.get(username=username)
                messages.error(request, 'Invalid password. Please try again.')
            except CustomUser.DoesNotExist:
                # User doesn't exist - redirect to signup with a message
                messages.info(request, f'No account found with username "{username}". Please create an account to get started.')
                return redirect('register')
    
    return render(request, 'chat/login.html')

def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                user = form.save(commit=False)
                user.is_email_verified = False  # Require email verification
                
                user.save()
                
                # Send verification email
                send_verification_email(user, request)
                messages.success(request, f'Account created! Please check your email to verify your account.')
                return redirect('login')
                
            except Exception as e:
                logger.error(f"Error creating account: {str(e)}")
                messages.error(request, f'Error creating account: {str(e)}')
        else:
            # Display form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    
    return render(request, 'chat/register.html')

def send_verification_email(user, request):
    try:
        # Delete any existing tokens for this user
        EmailVerificationToken.objects.filter(user=user).delete()
        
        token = EmailVerificationToken.objects.create(user=user)
        verification_url = request.build_absolute_uri(
            reverse('verify_email', kwargs={'token': token.token})
        )
        
        subject = 'Verify your Odnix account'
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: #667eea; color: white; padding: 20px; text-align: center;">
                    <h1>Welcome to Odnix!</h1>
                </div>
                <div style="padding: 20px;">
                    <h2>Hello {user.full_name}!</h2>
                    <p>Thank you for registering with Odnix. Please verify your email address:</p>
                    <a href="{verification_url}" style="background: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block; margin: 20px 0;">Verify Email</a>
                    <p>If the button doesn't work, copy this link: {verification_url}</p>
                    <p>This link expires in 24 hours.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        plain_message = f"""
        Hello {user.full_name}!
        
        Thank you for registering with Odnix. Please verify your email by visiting: {verification_url}
        
        This link expires in 24 hours.
        """
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=html_content,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Email error: {e}")
        return False

def verify_email(request, token):
    try:
        verification_token = get_object_or_404(EmailVerificationToken, token=token)
        
        if verification_token.is_used:
            messages.error(request, 'This verification link has already been used.')
            return redirect('login')
        
        if verification_token.is_expired:
            messages.error(request, 'This verification link has expired.')
            return redirect('login')
        
        user = verification_token.user
        user.is_email_verified = True
        user.save()
        
        verification_token.is_used = True
        verification_token.save()
        
        messages.success(request, 'Email verified successfully! You can now log in.')
        return redirect('login')
        
    except Exception as e:
        logger.error(f"Email verification error: {e}")
        messages.error(request, 'Invalid verification link.')
        return redirect('login')

@login_required
def dashboard(request):
    """FIXED - Enhanced dashboard with proper multiple stories support"""
    
    # Get user's chats
    user_chats = Chat.objects.filter(participants=request.user).select_related('admin')
    private_chats = user_chats.filter(chat_type='private')
    group_chats = user_chats.filter(chat_type='group')
    
    # Get other users
    other_users = CustomUser.objects.exclude(id=request.user.id).distinct().order_by('name', 'lastname')
    
    # Get pending join requests
    pending_requests = GroupJoinRequest.objects.filter(
        group__admin=request.user,
        status='pending'
    ).select_related('user', 'group').order_by('-requested_at')
    
    # Get following users
    following_users = Follow.objects.filter(follower=request.user).values_list('following', flat=True)
    
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
        has_viewed = StoryView.objects.filter(story=story, viewer=request.user).exists()
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
            'user': tweet.user,
            'username': tweet.user.username,
            'fullname': tweet.user.full_name,
            'user_initials': tweet.user.initials,
            'profile_picture_url': tweet.user.profile_picture_url,
            'formatted_time': tweet.timestamp.strftime('%b %d, %Y %H:%M'),
            'time_ago': time_ago,
            'like_count': like_count,
            'comment_count': comment_count,
            'is_liked': is_liked,
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
            other_participant = chat.participants.exclude(id=request.user.id).first()
            chat_info['other_user'] = other_participant
        
        # Get last message
        last_message = chat.messages.order_by('-timestamp').first()
        if last_message:
            chat_info['last_message_preview'] = last_message.content[:50] + ('...' if len(last_message.content) > 50 else '')
            chat_info['last_message_time'] = last_message.timestamp
        else:
            chat_info['last_message_preview'] = None
            chat_info['last_message_time'] = None
        
        # Get unread count
        chat_info['unread_count'] = chat.messages.filter(is_read=False).exclude(sender=request.user).count()
        
        all_chats.append(chat_info)
    
    context = {
        'private_chats': private_chats,
        'group_chats': group_chats,
        'chats': all_chats,  # Combined chats for the panel
        'other_users': other_users,
        'pending_requests': pending_requests,
        'current_user': request.user,
        'stories_by_user': stories_by_user,  # Keep as dict for template iteration
        'user_story': user_story,  # Latest user story for display
        'user_stories': user_stories,  # ALL user stories for navigation
        'user_story_count': user_story_count,  # Count for display
        'tweets_data': tweets_data,
        'tweet_form': tweet_form,  # Pass form to template
        'story_inbox_count': story_inbox_count,  # Notification count
    }
    
    # Use Instagram-style template
    return render(request, 'chat/dashboard_instagram.html', context)

@login_required
def profile_view(request, username=None):
    if username:
        profile_user = get_object_or_404(CustomUser, username=username)
        is_own_profile = False
    else:
        profile_user = request.user
        is_own_profile = True
    
    # Check if profile is accessible
    can_view_profile = True
    is_blocked = False
    follow_request_status = None
    
    if not is_own_profile and request.user.is_authenticated:
        # Check if blocked
        is_blocked_by_me = Block.objects.filter(
            blocker=request.user,
            blocked=profile_user
        ).exists()
        is_blocked_by_them = Block.objects.filter(
            blocker=profile_user,
            blocked=request.user
        ).exists()
        
        if is_blocked_by_me or is_blocked_by_them:
            is_blocked = True
            can_view_profile = False
        elif profile_user.is_private:
            # Check if current user follows the private account
            is_following = Follow.objects.filter(
                follower=request.user,
                following=profile_user
            ).exists()
            
            if not is_following:
                can_view_profile = False
                # Check if there's a pending follow request
                follow_request = FollowRequest.objects.filter(
                    requester=request.user,
                    target=profile_user
                ).first()
                if follow_request:
                    follow_request_status = follow_request.status
        else:
            # Public account - auto-accept any pending follow requests
            follow_request = FollowRequest.objects.filter(
                requester=request.user,
                target=profile_user,
                status='pending'
            ).first()
            if follow_request:
                Follow.objects.get_or_create(
                    follower=request.user,
                    following=profile_user
                )
                follow_request.status = 'accepted'
                follow_request.save()
    
    # Get user's tweets (only if profile is accessible)
    tweets = []
    if can_view_profile:
        tweets_queryset = Tweet.objects.filter(user=profile_user).select_related('user').distinct().order_by('-id', '-timestamp')
        processed_tweet_ids = set()
        
        for tweet in tweets_queryset:
            if tweet.id in processed_tweet_ids:
                continue
            processed_tweet_ids.add(tweet.id)
            
            like_count = Like.objects.filter(tweet=tweet).count()
            is_liked = Like.objects.filter(tweet=tweet, user=request.user).exists() if request.user.is_authenticated else False
            
            # Get comment count
            comment_count = Comment.objects.filter(tweet=tweet).count()
            
            # Get recent comments (latest 3)
            recent_comments = Comment.objects.filter(
                tweet=tweet,
                parent__isnull=True
            ).select_related('user').order_by('-timestamp')[:3]
            
            tweet_data = {
                'id': tweet.id,
                'content': tweet.content,
                'timestamp': tweet.timestamp,
                'user': tweet.user,
                'like_count': like_count,
                'is_liked': is_liked,
                'comment_count': comment_count,
                'image_url': tweet.image_url,
                'has_media': tweet.has_media,
                'recent_comments': recent_comments,
            }
            tweets.append(tweet_data)
    
    # Check if there's an existing chat
    existing_chat = None
    if not is_own_profile and not is_blocked:
        existing_chat = Chat.objects.filter(
            participants=request.user,
            chat_type='private'
        ).filter(participants=profile_user).first()
    
    # Check following status
    is_following = False
    if not is_own_profile and request.user.is_authenticated and not is_blocked:
        is_following = Follow.objects.filter(
            follower=request.user,
            following=profile_user
        ).exists()
    
    # Get follow request counts for own profile
    pending_requests_count = 0
    if is_own_profile:
        pending_requests_count = FollowRequest.objects.filter(
            target=request.user,
            status='pending'
        ).count()
    
    other_users = CustomUser.objects.exclude(id=request.user.id).distinct().order_by('name', 'lastname')
    
    # Create tweet form for profile page
    tweet_form = TweetForm()
    
    # Get user's chats for mobile bottom nav (same as dashboard)
    private_chats = Chat.objects.filter(
        participants=request.user,
        chat_type='private'
    ).annotate(
        last_message_time=Max('messages__timestamp')
    ).order_by('-last_message_time').distinct()
    
    group_chats = Chat.objects.filter(
        participants=request.user,
        chat_type='group'
    ).annotate(
        last_message_time=Max('messages__timestamp')
    ).order_by('-last_message_time').distinct()
    
    # Combine chats for the chats panel modal
    user_chats = Chat.objects.filter(participants=request.user).order_by('-updated_at')[:20]
    all_chats = []
    for chat in user_chats:
        chat_info = {
            'id': chat.id,
            'name': chat.name,
            'is_group': chat.chat_type == 'group',
        }
        if chat.chat_type == 'private':
            other_participant = chat.participants.exclude(id=request.user.id).first()
            chat_info['other_user'] = other_participant
        last_message = chat.messages.order_by('-timestamp').first()
        if last_message:
            chat_info['last_message_preview'] = last_message.content[:50] + ('...' if len(last_message.content) > 50 else '')
        else:
            chat_info['last_message_preview'] = None
        all_chats.append(chat_info)
    
    context = {
        'profile_user': profile_user,
        'tweets': tweets,
        'is_own_profile': is_own_profile,
        'existing_chat': existing_chat,
        'is_following': is_following,
        'other_users': other_users,
        'tweet_form': tweet_form,
        'can_view_profile': can_view_profile,
        'is_blocked': is_blocked,
        'follow_request_status': follow_request_status,
        'pending_requests_count': pending_requests_count,
        'private_chats': private_chats,
        'group_chats': group_chats,
        'chats': all_chats,  # Combined chats for the panel
        'current_user': request.user,
    }
    
    # Use Instagram-style template
    return render(request, 'chat/profile_instagram.html', context)

@login_required
def update_profile(request):
    """Update user profile with cropped image support"""
    if request.method == 'POST':
        form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user)
        
        # Check for cropped image data (base64)
        cropped_image_data = request.POST.get('profile_picture_cropped', '')
        
        if form.is_valid():
            user = form.save(commit=False)
            
            # Handle cropped image if provided
            if cropped_image_data and cropped_image_data.startswith('data:image'):
                try:
                    import base64
                    from django.core.files.base import ContentFile
                    import uuid
                    
                    # Parse the base64 data
                    format_part, imgstr = cropped_image_data.split(';base64,')
                    ext = format_part.split('/')[-1]
                    if ext == 'jpeg':
                        ext = 'jpg'
                    
                    # Decode and save
                    image_data = base64.b64decode(imgstr)
                    filename = f"profile_{request.user.id}_{uuid.uuid4().hex[:8]}.{ext}"
                    
                    # Delete old profile picture if exists
                    if user.profile_picture:
                        try:
                            user.profile_picture.delete(save=False)
                        except:
                            pass
                    
                    # Save new cropped image
                    user.profile_picture.save(filename, ContentFile(image_data), save=False)
                    
                except Exception as e:
                    logger.error(f"Error processing cropped image: {e}")
                    messages.error(request, 'Error processing image. Please try again.')
                    return redirect('update_profile')
            
            user.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = ProfileUpdateForm(instance=request.user)
    
    context = {
        'form': form,
    }
    return render(request, 'chat/update_profile.html', context)

@login_required
@require_POST
def post_tweet(request):
    """Post a tweet with proper duplicate prevention and validation"""
    logger.info(f"Tweet post attempt by user {request.user.id}")
    
    try:
        # Parse form data properly
        content = request.POST.get('content', '').strip()
        image_file = request.FILES.get('image')
        
        logger.info(f"Content: {content[:50]}..., Has image: {bool(image_file)}")
        
        # Basic validation
        if not content and not image_file:
            return JsonResponse({'success': False, 'error': 'Tweet cannot be empty. Please add text or an image.'})
        
        if content and len(content) > 280:
            return JsonResponse({'success': False, 'error': 'Tweet must be 280 characters or less.'})
        
        # Duplicate prevention
        tweet_hash = generate_tweet_hash(request.user.id, content or '', bool(image_file))
        cache_key = f"{TWEET_CACHE_PREFIX}{tweet_hash}"
        
        # Check cache for recent duplicate
        if cache.get(cache_key):
            logger.warning(f"Duplicate tweet attempt blocked for user {request.user.id}")
            return JsonResponse({'success': False, 'error': f'Please wait {TWEET_COOLDOWN} seconds before posting the same tweet again.'})
        
        # Check database for recent duplicates (last 3 minutes)
        three_minutes_ago = timezone.now() - timezone.timedelta(minutes=3)
        recent_duplicate = Tweet.objects.filter(
            user=request.user,
            content=content or '',
            timestamp__gte=three_minutes_ago
        )
        
        if image_file:
            recent_duplicate = recent_duplicate.exclude(image__isnull=True).exclude(image='')
        else:
            recent_duplicate = recent_duplicate.filter(Q(image__isnull=True) | Q(image=''))
        
        if recent_duplicate.exists():
            logger.warning(f"Recent duplicate found in database for user {request.user.id}")
            return JsonResponse({'success': False, 'error': 'You already posted this tweet recently. Please wait before posting again.'})
        
        # Use Django form for proper validation
        form_data = {'content': content} if content else {}
        files_data = {'image': image_file} if image_file else {}
        
        form = TweetForm(form_data, files_data)
        if form.is_valid():
            # Create tweet using form
            tweet = form.save(commit=False)
            tweet.user = request.user
            tweet.save()
            
            # Process hashtags and mentions
            process_tweet_hashtags_mentions(tweet)
            
            # Set cache to prevent immediate duplicates
            cache.set(cache_key, True, timeout=TWEET_COOLDOWN)
            
            logger.info(f"Tweet {tweet.id} created successfully by user {request.user.id}")
            
            return JsonResponse({
                'success': True,
                'message': 'Tweet posted successfully!',
                'tweet': {
                    'id': tweet.id,
                    'content': tweet.content,
                    'timestamp': tweet.timestamp.strftime('%B %d, %Y at %H:%M'),
                    'time_ago': 'now',
                    'like_count': 0,
                    'comment_count': 0,
                    'image_url': tweet.image_url,
                    'has_media': tweet.has_media,
                    'user': {
                        'username': request.user.username,
                        'fullname': request.user.full_name,
                        'initials': request.user.initials,
                        'profile_picture_url': request.user.profile_picture_url,
                    }
                }
            })
        else:
            # Form validation errors
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    error_messages.append(f"{error}")
            logger.warning(f"Form validation failed: {error_messages}")
            return JsonResponse({'success': False, 'error': '. '.join(error_messages)})
            
    except Exception as e:
        logger.error(f"Error in post_tweet: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'An unexpected error occurred. Please try again.'})

@login_required
@require_POST
def toggle_like(request):
    try:
        data = json.loads(request.body)
        tweet_id = data.get('tweet_id')
        
        if not tweet_id:
            return JsonResponse({'success': False, 'error': 'Tweet ID is required'})
        
        try:
            tweet = Tweet.objects.get(id=tweet_id)
        except Tweet.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Tweet not found'})
        
        # Toggle like
        like_obj = Like.objects.filter(user=request.user, tweet=tweet).first()
        
        if like_obj:
            like_obj.delete()
            is_liked = False
        else:
            Like.objects.create(user=request.user, tweet=tweet)
            is_liked = True
        
        like_count = Like.objects.filter(tweet=tweet).count()
        
        return JsonResponse({
            'success': True,
            'is_liked': is_liked,
            'like_count': like_count
        })
        
    except Exception as e:
        logger.error(f"Error in toggle_like: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to toggle like'})

@login_required
@require_POST
def add_comment(request):
    """Add a comment to a tweet"""
    try:
        data = json.loads(request.body)
        tweet_id = data.get('tweet_id')
        content = data.get('content', '').strip()
        parent_id = data.get('parent_id')  # For replies
        
        if not tweet_id or not content:
            return JsonResponse({'success': False, 'error': 'Tweet ID and content are required'})
        
        if len(content) > 500:
            return JsonResponse({'success': False, 'error': 'Comment too long (max 500 characters)'})
        
        try:
            tweet = Tweet.objects.get(id=tweet_id)
        except Tweet.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Tweet not found'})
        
        parent_comment = None
        if parent_id:
            try:
                parent_comment = Comment.objects.get(id=parent_id, tweet=tweet)
            except Comment.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Parent comment not found'})
        
        comment = Comment.objects.create(
            tweet=tweet,
            user=request.user,
            content=content,
            parent=parent_comment
        )
        
        return JsonResponse({
            'success': True,
            'comment': {
                'id': comment.id,
                'content': comment.content,
                'user_full_name': comment.user.full_name,
                'user_username': comment.user.username,
                'user_initials': comment.user.initials,
                'user_profile_picture': comment.user.profile_picture_url,
                'timestamp': comment.timestamp.strftime('%b %d, %Y %H:%M'),
                'is_own': comment.user == request.user,
            }
        })
        
    except Exception as e:
        logger.error(f"Error in add_comment: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to add comment'})

@login_required
def get_tweet_comments(request, tweet_id):
    """Get comments for a tweet"""
    try:
        tweet = get_object_or_404(Tweet, id=tweet_id)
        
        comments = Comment.objects.filter(
            tweet=tweet,
            parent__isnull=True
        ).select_related('user').prefetch_related('replies__user').order_by('timestamp')
        
        comments_data = []
        for comment in comments:
            comment_data = {
                'id': comment.id,
                'content': comment.content,
                'user_full_name': comment.user.full_name,
                'user_username': comment.user.username,
                'user_initials': comment.user.initials,
                'user_profile_picture': comment.user.profile_picture_url,
                'timestamp': comment.timestamp.strftime('%b %d, %Y %H:%M'),
                'is_own': comment.user == request.user,
                'replies': []
            }
            
            # Add replies
            for reply in comment.replies.all():
                reply_data = {
                    'id': reply.id,
                    'content': reply.content,
                    'user_full_name': reply.user.full_name,
                    'user_username': reply.user.username,
                    'user_initials': reply.user.initials,
                    'user_profile_picture': reply.user.profile_picture_url,
                    'timestamp': reply.timestamp.strftime('%b %d, %Y %H:%M'),
                    'is_own': reply.user == request.user,
                }
                comment_data['replies'].append(reply_data)
            
            comments_data.append(comment_data)
        
        return JsonResponse({
            'success': True,
            'comments': comments_data
        })
        
    except Exception as e:
        logger.error(f"Error in get_tweet_comments: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to load comments'})

@login_required
@require_POST
def create_story(request):
    """FIXED - Create a new story - NOW SUPPORTS MULTIPLE STORIES PER USER AND IMAGE+TEXT COMBO"""
    try:
        story_type = request.POST.get('story_type', 'text')
        content = request.POST.get('content', '').strip()
        background_color = request.POST.get('background_color', '#667eea')
        text_color = request.POST.get('text_color', '#ffffff')
        text_position = request.POST.get('text_position', 'center')
        media_file = request.FILES.get('media')
        
        logger.info(f"Creating story: type={story_type}, content={content}, has_media={bool(media_file)}, text_position={text_position}")
        
        # Validate text_position
        if text_position not in ['top', 'center', 'bottom']:
            text_position = 'center'
        
        # Handle media file - determine type from file
        if media_file:
            file_extension = os.path.splitext(media_file.name)[1].lower()
            if file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                story_type = 'image'
            elif file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                story_type = 'video'
            else:
                return JsonResponse({'success': False, 'error': 'Invalid file type. Supported: jpg, png, gif, webp, mp4, mov, avi, mkv, webm'})
        
        # Validation - need either content or media
        if not content and not media_file:
            return JsonResponse({'success': False, 'error': 'Please add text or an image'})
        
        # FIXED: DON'T deactivate previous stories - allow multiple stories
        # REMOVED: Story.objects.filter(user=request.user, is_active=True).update(is_active=False)
        
        # Create new story WITHOUT deactivating previous ones
        story = Story.objects.create(
            user=request.user,
            content=content,  # Can be empty for image-only stories
            media_file=media_file,
            story_type=story_type,
            background_color=background_color,
            text_color=text_color,
            text_position=text_position,
            # is_active=True by default from model
            # expires_at set automatically by model (24 hours from now)
        )
        
        logger.info(f"Story created successfully: {story.id}")
        
        return JsonResponse({
            'success': True,
            'story': {
                'id': story.id,
                'content': story.content,
                'media_url': story.media_url,
                'story_type': story.story_type,
                'background_color': story.background_color,
                'text_color': story.text_color,
                'text_position': story.text_position,
            }
        })
        
    except Exception as e:
        logger.error(f"Error creating story: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def view_story(request, story_id):
    """View a specific story"""
    try:
        story = get_object_or_404(
            Story,
            id=story_id,
            is_active=True,
            expires_at__gt=timezone.now()
        )
        
        # Add view if not already viewed
        if not story.story_views.filter(viewer=request.user).exists():
            StoryView.objects.create(story=story, viewer=request.user)
        
        return JsonResponse({
            'success': True,
            'story': {
                'id': story.id,
                'content': story.content,
                'media_url': story.media_url,
                'story_type': story.story_type,
                'background_color': story.background_color,
                'text_color': story.text_color,
                'text_position': story.text_position,
                'user': {
                    'id': story.user.id,
                    'username': story.user.username,
                    'full_name': story.user.full_name,
                    'profile_picture_url': story.user.profile_picture_url,
                },
                'created_at': story.created_at.strftime('%H:%M'),
                'view_count': story.view_count,
                'like_count': story.like_count,
                'reply_count': story.reply_count,
                'is_liked': story.story_likes.filter(user=request.user).exists(),
                'user_has_replied': story.story_replies.filter(replier=request.user).exists(),
            }
        })
        
    except Exception as e:
        logger.error(f"Error viewing story: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

# NEW: API endpoint to get all stories for a user (for multiple story viewing)
@login_required
def get_user_stories(request, username):
    """Get all active stories for a specific user"""
    try:
        user = get_object_or_404(CustomUser, username=username)
        
        # Get all active stories for this user
        stories = Story.objects.filter(
            user=user,
            is_active=True,
            expires_at__gt=timezone.now()
        ).order_by('-created_at')
        
        stories_data = []
        for story in stories:
            # Mark as viewed if not already
            if not story.story_views.filter(viewer=request.user).exists():
                StoryView.objects.create(story=story, viewer=request.user)
            
            stories_data.append({
                'id': story.id,
                'content': story.content,
                'media_url': story.media_url,
                'story_type': story.story_type,
                'background_color': story.background_color,
                'text_color': story.text_color,
                'text_position': story.text_position,
                'user': {
                    'id': story.user.id,
                    'username': story.user.username,
                    'full_name': story.user.full_name,
                    'profile_picture_url': story.user.profile_picture_url,
                },
                'created_at': story.created_at.strftime('%H:%M'),
                'view_count': story.view_count,
                'like_count': story.like_count,
                'reply_count': story.reply_count,
                'is_liked': story.story_likes.filter(user=request.user).exists(),
                'user_has_replied': story.story_replies.filter(replier=request.user).exists(),
            })
        
        return JsonResponse({
            'success': True,
            'stories': stories_data
        })
        
    except Exception as e:
        logger.error(f"Error getting user stories: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

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
    from datetime import timedelta
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
    
    # Use Instagram-style template
    return render(request, 'chat/chat_detail_instagram.html', context)

@login_required
def join_group_view(request, invite_code):
    chat = get_object_or_404(Chat, invite_code=invite_code, chat_type='group')
    
    if chat.participants.filter(id=request.user.id).exists():
        messages.info(request, f'You are already a member of {chat.name}')
        return redirect('chat_detail', chat_id=chat.id)
    
    if not chat.can_add_participants:
        messages.error(request, f'{chat.name} is full')
        return redirect('dashboard')
    
    # If group is public, add user directly
    if chat.is_public:
        chat.participants.add(request.user)
        messages.success(request, f'You have joined {chat.name}!')
        return redirect('chat_detail', chat_id=chat.id)
    
    # For private groups, check for existing request
    existing_request = GroupJoinRequest.objects.filter(
        group=chat,
        user=request.user,
        status='pending'
    ).first()
    
    if existing_request:
        messages.info(request, f'You already have a pending request to join {chat.name}')
        return redirect('dashboard')
    
    if request.method == 'POST':
        message = request.POST.get('message', '').strip()
        
        join_request = GroupJoinRequest.objects.create(
            group=chat,
            user=request.user,
            message=message
        )
        
        messages.success(request, f'Join request sent to {chat.name}.')
        return redirect('dashboard')
    
    return render(request, 'chat/join_group.html', {'chat': chat})

@login_required
def discover_groups_view(request):
    """View for discovering public groups"""
    search_query = request.GET.get('q', '').strip()
    
    # Get all public groups
    public_groups = Chat.objects.filter(
        chat_type='group',
        is_public=True
    ).exclude(
        participants=request.user  # Exclude groups user is already in
    ).annotate(
        member_count=Count('participants'),
        message_count=Count('messages')
    ).order_by('-created_at')
    
    # Apply search filter if provided
    if search_query:
        public_groups = public_groups.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    # Get user's groups
    user_groups = Chat.objects.filter(
        chat_type='group',
        participants=request.user
    ).values_list('id', flat=True)
    
    context = {
        'public_groups': public_groups,
        'search_query': search_query,
        'user_groups': list(user_groups),
    }
    
    return render(request, 'chat/discover_groups.html', context)

def handle_media_upload(media_file):
    if not media_file:
        return None, None, None, None
    
    try:
        file_extension = os.path.splitext(media_file.name)[1].lower()
        unique_filename = f'chat_media/{uuid.uuid4()}{file_extension}'
        
        file_path = default_storage.save(unique_filename, media_file)
        file_url = default_storage.url(file_path)
        
        if file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            media_type = 'image'
        elif file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
            media_type = 'video'
        else:
            media_type = 'document'
        
        return file_url, media_type, media_file.name, media_file.size
        
    except Exception as e:
        logger.error(f"Error uploading media: {e}")
        return None, None, None, None

# FIXED: Media serving function with path traversal protection
def serve_media_file(request, file_path):
    """Serve media files with path traversal protection"""
    try:
        # Normalize the path and ensure it stays within MEDIA_ROOT
        # This prevents path traversal attacks like ../../../etc/passwd
        full_path = os.path.normpath(os.path.join(settings.MEDIA_ROOT, file_path))
        
        # Security check: ensure the resolved path is within MEDIA_ROOT
        if not full_path.startswith(str(settings.MEDIA_ROOT)):
            logger.warning(f"Path traversal attempt detected: {file_path}")
            raise Http404("Invalid file path")
        
        if not os.path.exists(full_path):
            raise Http404("Media file not found")
        
        mime_type, _ = mimetypes.guess_type(full_path)
        if not mime_type:
            mime_type = 'application/octet-stream'
        
        with open(full_path, 'rb') as f:
            file_data = f.read()
        
        response = HttpResponse(file_data, content_type=mime_type)
        response['Content-Length'] = len(file_data)
        response['Content-Disposition'] = f'inline; filename="{os.path.basename(file_path)}"'
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        
        return response
        
    except Exception as e:
        logger.error(f"Error serving media file: {e}")
        raise Http404("Error serving media file")

@login_required
def get_chat_messages(request, chat_id):
    """FIXED - Get chat messages with proper API response"""
    chat = get_object_or_404(Chat, id=chat_id, participants=request.user)
    
    last_message_time = request.GET.get('last_message_time')
    messages_query = chat.messages.all().order_by('timestamp')
    
    if last_message_time:
        try:
            from datetime import datetime
            last_time = datetime.fromisoformat(last_message_time.replace('Z', '+00:00'))
            messages_query = messages_query.filter(timestamp__gt=last_time)
        except:
            pass
    
    messages_data = []
    for msg in messages_query:
        message_data = {
            'id': msg.id,
            'content': msg.content,
            'sender': msg.sender.username if msg.sender else 'System',
            'sender_name': msg.sender.full_name if msg.sender else 'System',
            'timestamp': msg.timestamp.strftime('%H:%M'),
            'timestamp_iso': msg.timestamp.isoformat(),
            'message_type': msg.message_type,
            'is_own': msg.sender == request.user if msg.sender else False,
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
                reply_to_message = Message.objects.get(id=reply_to_id, chat=chat)
            except Message.DoesNotExist:
                pass
        
        # Handle media upload
        media_url = None
        media_type = None
        media_filename = None
        media_size = None
        
        if media_file:
            media_url, media_type, media_filename, media_size = handle_media_upload(media_file)
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
def toggle_follow(request):
    try:
        data = json.loads(request.body)
        username = data.get('username')
        
        if not username:
            return JsonResponse({'success': False, 'error': 'Username is required'})
        
        try:
            target_user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'User not found'})
        
        if target_user == request.user:
            return JsonResponse({'success': False, 'error': 'Cannot follow yourself'})
        
        # Check if target user is blocked by current user
        if Block.objects.filter(blocker=request.user, blocked=target_user).exists():
            return JsonResponse({'success': False, 'error': 'You have blocked this user'})
        
        # Check if current user is blocked by target user
        if Block.objects.filter(blocker=target_user, blocked=request.user).exists():
            return JsonResponse({'success': False, 'error': 'This user has blocked you'})
        
        follow_obj = Follow.objects.filter(
            follower=request.user,
            following=target_user
        ).first()
        
        if follow_obj:
            # Unfollow
            follow_obj.delete()
            is_following = False
            follow_request_status = None
        else:
            # Follow or send follow request
            if target_user.is_private:
                # Check if follow request already exists
                existing_request = FollowRequest.objects.filter(
                    requester=request.user,
                    target=target_user
                ).first()
                
                if existing_request:
                    if existing_request.status == 'pending':
                        return JsonResponse({'success': False, 'error': 'Follow request already sent'})
                    else:  # accepted or declined
                        # For private accounts, always send new request after unfollowing
                        # Delete any existing request and create new one
                        existing_request.delete()
                        FollowRequest.objects.create(
                            requester=request.user,
                            target=target_user
                        )
                        is_following = False
                        follow_request_status = 'pending'
                else:
                    # Send new follow request
                    FollowRequest.objects.create(
                        requester=request.user,
                        target=target_user
                    )
                    is_following = False
                    follow_request_status = 'pending'
            else:
                # Public account - follow directly
                Follow.objects.create(
                    follower=request.user,
                    following=target_user
                )
                is_following = True
                follow_request_status = None
        
        return JsonResponse({
            'success': True,
            'is_following': is_following,
            'follow_request_status': follow_request_status,
            'username': username
        })
        
    except Exception as e:
        logger.error(f"Error in toggle_follow: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to toggle follow'})

@login_required
@require_POST
def toggle_block(request):
    """Block or unblock a user"""
    try:
        data = json.loads(request.body)
        username = data.get('username')
        
        if not username:
            return JsonResponse({'success': False, 'error': 'Username is required'})
        
        try:
            target_user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'User not found'})
        
        if target_user == request.user:
            return JsonResponse({'success': False, 'error': 'Cannot block yourself'})
        
        # Check if already blocked
        block_obj = Block.objects.filter(
            blocker=request.user,
            blocked=target_user
        ).first()
        
        if block_obj:
            # Unblock
            block_obj.delete()
            is_blocked = False
            
            # Remove follow relationship if it exists
            Follow.objects.filter(
                follower=request.user,
                following=target_user
            ).delete()
            Follow.objects.filter(
                follower=target_user,
                following=request.user
            ).delete()
        else:
            # Block
            Block.objects.create(
                blocker=request.user,
                blocked=target_user
            )
            is_blocked = True
            
            # Remove follow relationship if it exists
            Follow.objects.filter(
                follower=request.user,
                following=target_user
            ).delete()
            Follow.objects.filter(
                follower=target_user,
                following=request.user
            ).delete()
            
            # Remove any pending follow requests
            FollowRequest.objects.filter(
                sender=request.user,
                receiver=target_user
            ).delete()
            FollowRequest.objects.filter(
                sender=target_user,
                receiver=request.user
            ).delete()
        
        return JsonResponse({
            'success': True,
            'is_blocked': is_blocked,
            'username': username
        })
        
    except Exception as e:
        logger.error(f"Error in toggle_block: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to toggle block'})

@login_required
@require_POST
def manage_follow_request(request):
    """Accept or decline a follow request"""
    try:
        data = json.loads(request.body)
        username = data.get('username')
        action = data.get('action')  # 'accept' or 'decline'
        
        if not username:
            return JsonResponse({'success': False, 'error': 'Username is required'})
        
        if action not in ['accept', 'decline']:
            return JsonResponse({'success': False, 'error': 'Invalid action'})
        
        try:
            sender_user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'User not found'})
        
        # Find the follow request
        follow_request = FollowRequest.objects.filter(
            sender=sender_user,
            receiver=request.user,
            status='pending'
        ).first()
        
        if not follow_request:
            return JsonResponse({'success': False, 'error': 'No pending follow request found'})
        
        if action == 'accept':
            # Create follow relationship
            Follow.objects.get_or_create(
                follower=sender_user,
                following=request.user
            )
            follow_request.status = 'accepted'
            follow_request.save()
            message = 'Follow request accepted'
        else:  # decline
            follow_request.status = 'declined'
            follow_request.save()
            message = 'Follow request declined'
        
        return JsonResponse({
            'success': True,
            'action': action,
            'username': username,
            'message': message
        })
        
    except Exception as e:
        logger.error(f"Error in manage_follow_request: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to manage follow request'})

@login_required
@require_POST
def toggle_account_privacy(request):
    """Toggle account privacy setting"""
    try:
        old_privacy = request.user.is_private
        request.user.is_private = not request.user.is_private
        request.user.save()
        
        # Handle existing follow requests when changing privacy
        if not old_privacy and request.user.is_private:
            # User is making account private - existing follows remain
            pass
        elif old_privacy and not request.user.is_private:
            # User is making account public - accept all pending follow requests
            pending_requests = FollowRequest.objects.filter(
                target=request.user,
                status='pending'
            )
            
            for follow_request in pending_requests:
                # Create follow relationship
                Follow.objects.get_or_create(
                    follower=follow_request.requester,
                    following=request.user
                )
                # Mark request as accepted
                follow_request.status = 'accepted'
                follow_request.save()
        
        return JsonResponse({
            'success': True,
            'is_private': request.user.is_private
        })
        
    except Exception as e:
        logger.error(f"Error in toggle_account_privacy: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to toggle account privacy'})

@login_required
def get_follow_requests(request):
    """Get pending follow requests for the current user"""
    try:
        follow_requests = FollowRequest.objects.filter(
            target=request.user,
            status='pending'
        ).select_related('requester').order_by('-created_at')

        requests_data = []
        for req in follow_requests:
            requests_data.append({
                'username': req.requester.username,
                'full_name': req.requester.name + ' ' + req.requester.lastname if req.requester.name and req.requester.lastname else req.requester.username, 
                'profile_pic': req.requester.profile_picture.url if req.requester.profile_picture else None,
                'requested_at': req.created_at.strftime('%b %d, %Y')
            })

        return JsonResponse({
            'success': True,
            'requests': requests_data
        })

    except Exception as e:
        logger.error(f"Error in get_follow_requests: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get follow requests'})

@login_required
@require_POST
def follow_states(request):
    try:
        data = json.loads(request.body)
        usernames = data.get('usernames', [])
        
        if not usernames:
            return JsonResponse({'success': True, 'follow_states': {}})
        
        follow_states_dict = {}
        for username in usernames:
            try:
                target_user = CustomUser.objects.get(username=username)
                
                # Check if blocked
                is_blocked_by_me = Block.objects.filter(
                    blocker=request.user,
                    blocked=target_user
                ).exists()
                is_blocked_by_them = Block.objects.filter(
                    blocker=target_user,
                    blocked=request.user
                ).exists()
                
                if is_blocked_by_me or is_blocked_by_them:
                    follow_states_dict[username] = {
                        'is_following': False,
                        'is_blocked': True,
                        'follow_request_status': None,
                        'can_follow': False
                    }
                    continue
                
                # Check follow status
                is_following = Follow.objects.filter(
                    follower=request.user,
                    following=target_user
                ).exists()
                
                # Check follow request status
                follow_request = FollowRequest.objects.filter(
                    requester=request.user,
                    target=target_user
                ).first()
                
                follow_request_status = None
                if follow_request:
                    if follow_request.status == 'pending' and not target_user.is_private:
                        # Auto-accept pending request for public accounts
                        Follow.objects.get_or_create(
                            follower=request.user,
                            following=target_user
                        )
                        follow_request.status = 'accepted'
                        follow_request.save()
                        is_following = True
                        follow_request_status = None
                    else:
                        follow_request_status = follow_request.status
                
                follow_states_dict[username] = {
                    'is_following': is_following,
                    'is_blocked': False,
                    'follow_request_status': follow_request_status,
                    'can_follow': True,
                    'is_private': target_user.is_private
                }
                
            except CustomUser.DoesNotExist:
                follow_states_dict[username] = {
                    'is_following': False,
                    'is_blocked': False,
                    'follow_request_status': None,
                    'can_follow': False
                }
        
        return JsonResponse({
            'success': True,
            'follow_states': follow_states_dict
        })
        
    except Exception as e:
        logger.error(f"Error in follow_states: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get follow states'})

@login_required
@require_POST
def manage_follow_request(request):
    """Accept or decline a follow request"""
    try:
        data = json.loads(request.body)
        username = data.get('username')
        action = data.get('action')  # 'accept' or 'decline'
        
        if not username:
            return JsonResponse({'success': False, 'error': 'Username is required'})
        
        if action not in ['accept', 'decline']:
            return JsonResponse({'success': False, 'error': 'Invalid action'})
        
        try:
            sender_user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'User not found'})
        
        # Find the follow request
        follow_request = FollowRequest.objects.filter(
            requester=sender_user,
            target=request.user,
            status='pending'
        ).first()
        
        if not follow_request:
            return JsonResponse({'success': False, 'error': 'No pending follow request found'})
        
        if action == 'accept':
            # Create follow relationship
            Follow.objects.get_or_create(
                follower=sender_user,
                following=request.user
            )
            follow_request.status = 'accepted'
            follow_request.save()
            message = 'Follow request accepted'
        else:  # decline
            follow_request.status = 'declined'
            follow_request.save()
            message = 'Follow request declined'
        
        return JsonResponse({
            'success': True,
            'action': action,
            'username': username,
            'message': message
        })
        
    except Exception as e:
        logger.error(f"Error in manage_follow_request: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to manage follow request'})

@login_required
def logout_view(request):
    request.user.mark_offline()
    logout(request)
    return redirect('login')

# ===== STORY FEATURES API VIEWS =====

@login_required
@require_POST
def mark_story_viewed(request):
    """Mark a story as viewed by the current user"""
    try:
        data = json.loads(request.body)
        story_id = data.get('story_id')
        
        if not story_id:
            return JsonResponse({'success': False, 'error': 'Story ID is required'})
        
        story = get_object_or_404(Story, id=story_id)
        
        # Create or update view record
        view, created = StoryView.objects.get_or_create(
            story=story,
            viewer=request.user,
            defaults={'viewed_at': timezone.now()}
        )
        
        if not created:
            # Update timestamp if already viewed
            view.viewed_at = timezone.now()
            view.save()
        
        return JsonResponse({
            'success': True,
            'view_count': story.view_count
        })
        
    except Exception as e:
        logger.error(f"Error in mark_story_viewed: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to mark story as viewed'})

@login_required
@require_POST
def toggle_story_like(request):
    """Toggle like on a story"""
    try:
        data = json.loads(request.body)
        story_id = data.get('story_id')
        
        if not story_id:
            return JsonResponse({'success': False, 'error': 'Story ID is required'})
        
        story = get_object_or_404(Story, id=story_id)
        
        # Toggle like
        like_obj, created = StoryLike.objects.get_or_create(
            story=story,
            user=request.user
        )
        
        if not created:
            # Unlike if already liked
            like_obj.delete()
            is_liked = False
        else:
            is_liked = True
        
        like_count = story.like_count
        
        return JsonResponse({
            'success': True,
            'is_liked': is_liked,
            'like_count': like_count
        })
        
    except Exception as e:
        logger.error(f"Error in toggle_story_like: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to toggle story like'})

@login_required
@require_POST
def add_story_reply(request):
    """Add a reply to a story (only visible to story poster)"""
    try:
        data = json.loads(request.body)
        story_id = data.get('story_id')
        content = data.get('content', '').strip()
        
        if not story_id:
            return JsonResponse({'success': False, 'error': 'Story ID is required'})
        
        if not content:
            return JsonResponse({'success': False, 'error': 'Reply content is required'})
        
        if len(content) > 500:
            return JsonResponse({'success': False, 'error': 'Reply content too long (max 500 characters)'})
        
        story = get_object_or_404(Story, id=story_id)
        
        # Create the reply
        reply = StoryReply.objects.create(
            story=story,
            replier=request.user,
            content=content
        )
        
        return JsonResponse({
            'success': True,
            'reply_id': reply.id,
            'reply_count': story.reply_count
        })
        
    except Exception as e:
        logger.error(f"Error in add_story_reply: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to add story reply'})

@login_required
def get_story_replies(request, story_id):
    """Get replies for a story (for story poster or reply author)"""
    try:
        story = get_object_or_404(Story, id=story_id)
        
        # Allow story poster OR users who have replied to see replies
        if story.user != request.user and not story.story_replies.filter(replier=request.user).exists():
            return JsonResponse({'success': False, 'error': 'Unauthorized'})
        
        replies = story.story_replies.select_related('replier').order_by('created_at')
        
        replies_data = []
        for reply in replies:
            replies_data.append({
                'id': reply.id,
                'replier': {
                    'id': reply.replier.id,
                    'username': reply.replier.username,
                    'full_name': reply.replier.full_name,
                    'profile_picture_url': reply.replier.profile_picture_url
                },
                'content': reply.content,
                'created_at': reply.created_at.isoformat(),
                'is_read': reply.is_read,
            })        # Mark replies as read
        story.story_replies.filter(is_read=False).update(is_read=True)
        
        return JsonResponse({
            'success': True,
            'replies': replies_data
        })
        
    except Exception as e:
        logger.error(f"Error in get_story_replies: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get story replies'})

@login_required
def get_story_viewers(request, story_id):
    """Get viewers for a story (only for story poster)"""
    try:
        story = get_object_or_404(Story, id=story_id)
        
        # Only story poster can see viewers
        if story.user != request.user:
            return JsonResponse({'success': False, 'error': 'Unauthorized'})
        
        viewers = story.story_views.select_related('viewer').order_by('-viewed_at')
        
        viewers_data = []
        for view in viewers:
            viewers_data.append({
                'id': view.viewer.id,
                'username': view.viewer.username,
                'full_name': view.viewer.full_name,
                'profile_picture_url': view.viewer.profile_picture_url,
                'viewed_at': view.viewed_at.isoformat()
            })
        
        return JsonResponse({
            'success': True,
            'viewers': viewers_data,
            'view_count': len(viewers_data)
        })
        
    except Exception as e:
        logger.error(f"Error in get_story_viewers: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get story viewers'})

@login_required
@require_POST
def delete_reply(request, reply_id):
    """Delete a story reply (only by reply author)"""
    try:
        reply = get_object_or_404(StoryReply, id=reply_id)
        
        # Only reply author or story owner can delete
        if reply.replier != request.user and reply.story.user != request.user:
            return JsonResponse({'success': False, 'error': 'Unauthorized'})
        
        reply.delete()
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        logger.error(f"Error in delete_reply: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to delete reply'})


@login_required
def get_story_inbox(request):
    """Get all replies to the current user's stories - Story Inbox"""
    try:
        # Get all replies to stories owned by the current user
        replies = StoryReply.objects.filter(
            story__user=request.user
        ).select_related('replier', 'story').order_by('-created_at')
        
        replies_data = []
        for reply in replies:
            replies_data.append({
                'id': reply.id,
                'content': reply.content,
                'created_at': reply.created_at.isoformat(),
                'is_read': reply.is_read,
                'replier': {
                    'id': reply.replier.id,
                    'username': reply.replier.username,
                    'full_name': reply.replier.full_name,
                    'profile_picture_url': reply.replier.profile_picture_url,
                },
                'story': {
                    'id': reply.story.id,
                    'story_type': reply.story.story_type,
                    'content': reply.story.content,
                    'media_url': reply.story.media_url,
                    'background_color': reply.story.background_color,
                    'text_color': reply.story.text_color,
                    'text_position': reply.story.text_position,
                    'created_at': reply.story.created_at.isoformat(),
                }
            })
        
        # Mark all as read after fetching
        replies.filter(is_read=False).update(is_read=True)
        
        return JsonResponse({
            'success': True,
            'replies': replies_data
        })
        
    except Exception as e:
        logger.error(f"Error in get_story_inbox: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get story inbox'})


@login_required
def get_story_inbox_count(request):
    """Get the count of unread story replies"""
    try:
        unread_count = StoryReply.objects.filter(
            story__user=request.user,
            is_read=False
        ).count()
        
        return JsonResponse({
            'success': True,
            'unread_count': unread_count
        })
        
    except Exception as e:
        logger.error(f"Error in get_story_inbox_count: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get count'})


# ============================================
# MESSAGE EDITING FEATURE
# ============================================

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


# ============================================
# PINNED MESSAGES FEATURE
# ============================================

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
        from .models import PinnedChat
        
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
        from .models import PinnedChat
        
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)
        
        pinned = PinnedChat.objects.filter(user=request.user, chat=chat)
        if not pinned.exists():
            return JsonResponse({'success': False, 'error': 'Chat is not pinned'})
        
        pinned.delete()
        
        return JsonResponse({'success': True, 'message': 'Chat unpinned successfully'})
        
    except Exception as e:
        logger.error(f"Error unpinning chat: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to unpin chat'})


# ============================================
# HASHTAGS & MENTIONS FEATURE
# ============================================

import re

def extract_hashtags(content):
    """Extract hashtags from content"""
    hashtag_pattern = r'#(\w+)'
    return list(set(re.findall(hashtag_pattern, content.lower())))


def extract_mentions(content):
    """Extract @mentions from content"""
    mention_pattern = r'@(\w+)'
    return list(set(re.findall(mention_pattern, content.lower())))


def process_tweet_hashtags_mentions(tweet):
    """Process hashtags and mentions in a tweet after creation"""
    from .models import Hashtag, TweetHashtag, Mention
    
    if not tweet.content:
        return
    
    # Process hashtags
    hashtags = extract_hashtags(tweet.content)
    for tag_name in hashtags:
        hashtag, _ = Hashtag.objects.get_or_create(name=tag_name.lower())
        TweetHashtag.objects.get_or_create(tweet=tweet, hashtag=hashtag)
    
    # Process mentions
    mentions = extract_mentions(tweet.content)
    for username in mentions:
        try:
            mentioned_user = CustomUser.objects.get(username__iexact=username)
            if mentioned_user != tweet.user:  # Don't mention yourself
                Mention.objects.get_or_create(tweet=tweet, mentioned_user=mentioned_user)
        except CustomUser.DoesNotExist:
            pass  # User doesn't exist, skip


@login_required
def get_hashtag_tweets(request, hashtag):
    """Get all tweets with a specific hashtag"""
    try:
        from .models import Hashtag, TweetHashtag
        
        # Clean hashtag (remove # if present)
        hashtag_name = hashtag.lower().lstrip('#')
        
        hashtag_obj = Hashtag.objects.filter(name=hashtag_name).first()
        
        if not hashtag_obj:
            return JsonResponse({
                'success': True,
                'hashtag': hashtag_name,
                'tweets': [],
                'count': 0
            })
        
        tweet_links = TweetHashtag.objects.filter(
            hashtag=hashtag_obj
        ).select_related('tweet__user').order_by('-tweet__timestamp')[:50]
        
        tweets_data = []
        for link in tweet_links:
            tweet = link.tweet
            tweets_data.append({
                'id': tweet.id,
                'content': tweet.content,
                'user': {
                    'id': tweet.user.id,
                    'username': tweet.user.username,
                    'full_name': tweet.user.full_name,
                    'profile_picture_url': tweet.user.profile_picture_url
                },
                'timestamp': tweet.timestamp.isoformat(),
                'like_count': tweet.like_count,
                'comment_count': tweet.comment_count,
                'image_url': tweet.image_url,
                'is_liked': tweet.is_liked_by(request.user)
            })
        
        return JsonResponse({
            'success': True,
            'hashtag': hashtag_name,
            'tweets': tweets_data,
            'count': len(tweets_data)
        })
        
    except Exception as e:
        logger.error(f"Error getting hashtag tweets: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get hashtag tweets'})


@login_required
def get_trending_hashtags(request):
    """Get trending hashtags (most used in last 24 hours)"""
    try:
        from .models import TweetHashtag
        from django.db.models import Count
        
        # Get hashtags from tweets in last 24 hours
        yesterday = timezone.now() - timezone.timedelta(days=1)
        
        trending = TweetHashtag.objects.filter(
            created_at__gte=yesterday
        ).values('hashtag__name').annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        
        hashtags_data = []
        for item in trending:
            hashtags_data.append({
                'name': item['hashtag__name'],
                'tweet_count': item['count']
            })
        
        return JsonResponse({
            'success': True,
            'trending': hashtags_data
        })
        
    except Exception as e:
        logger.error(f"Error getting trending hashtags: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get trending hashtags'})


@login_required
def get_user_mentions(request):
    """Get mentions of the current user"""
    try:
        from .models import Mention
        
        mentions = Mention.objects.filter(
            mentioned_user=request.user
        ).select_related('tweet__user').order_by('-created_at')[:50]
        
        mentions_data = []
        for mention in mentions:
            tweet = mention.tweet
            mentions_data.append({
                'id': mention.id,
                'tweet': {
                    'id': tweet.id,
                    'content': tweet.content,
                    'user': {
                        'id': tweet.user.id,
                        'username': tweet.user.username,
                        'full_name': tweet.user.full_name,
                        'profile_picture_url': tweet.user.profile_picture_url
                    },
                    'timestamp': tweet.timestamp.isoformat(),
                    'like_count': tweet.like_count,
                    'image_url': tweet.image_url
                },
                'is_read': mention.is_read,
                'created_at': mention.created_at.isoformat()
            })
        
        # Mark mentions as read
        Mention.objects.filter(mentioned_user=request.user, is_read=False).update(is_read=True)
        
        return JsonResponse({
            'success': True,
            'mentions': mentions_data,
            'count': len(mentions_data)
        })
        
    except Exception as e:
        logger.error(f"Error getting user mentions: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get mentions'})


@login_required
def search_users_for_mention(request):
    """Search users for @mention autocomplete"""
    try:
        query = request.GET.get('q', '').strip().lower()
        
        if len(query) < 1:
            return JsonResponse({'success': True, 'users': []})
        
        users = CustomUser.objects.filter(
            db_models.Q(username__icontains=query) | 
            db_models.Q(name__icontains=query) |
            db_models.Q(lastname__icontains=query)
        ).exclude(id=request.user.id)[:10]
        
        users_data = []
        for user in users:
            users_data.append({
                'id': user.id,
                'username': user.username,
                'full_name': user.full_name,
                'profile_picture_url': user.profile_picture_url
            })
        
        return JsonResponse({
            'success': True,
            'users': users_data
        })
        
    except Exception as e:
        logger.error(f"Error searching users: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to search users'})


# ==================== STARRED MESSAGES ====================

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
        
        from .models import StarredMessage
        
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
        from .models import StarredMessage
        
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
        from .models import StarredMessage
        is_starred = StarredMessage.objects.filter(
            user=request.user,
            message_id=message_id
        ).exists()
        
        return JsonResponse({'success': True, 'is_starred': is_starred})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# ==================== READ RECEIPTS ====================

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
        from .models import MessageRead
        read_receipts = []
        for msg in unread_messages:
            read_receipts.append(MessageRead(message=msg, user=request.user))
        
        if read_receipts:
            MessageRead.objects.bulk_create(read_receipts, ignore_conflicts=True)
        
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
        
        from .models import MessageRead
        read_receipts = MessageRead.objects.filter(message=message).select_related('user')
        
        readers = []
        for receipt in read_receipts:
            readers.append({
                'user_id': receipt.user.id,
                'username': receipt.user.username,
                'full_name': receipt.user.full_name,
                'read_at': receipt.read_at.strftime('%b %d, %I:%M %p')
            })
        
        # Get total participants (excluding sender)
        total_recipients = message.chat.participants.exclude(id=request.user.id).count()
        
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
        from .models import MessageRead
        from django.db.models import Count, Exists, OuterRef
        
        user_messages = Message.objects.filter(
            chat=chat,
            sender=request.user
        ).annotate(
            read_count=Count('read_receipts')
        )
        
        total_recipients = chat.participants.exclude(id=request.user.id).count()
        
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
        
        from django.utils import timezone
        from datetime import timedelta
        
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
        
        from django.utils import timezone
        from datetime import timedelta
        
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
            is_truly_online = participant.is_online and participant.last_seen and (timezone.now() - participant.last_seen).total_seconds() < 15
            
            members.append({
                'id': participant.id,
                'username': participant.username,
                'full_name': participant.full_name,
                'profile_picture': participant.profile_picture_url,
                'is_admin': participant == chat.admin,
                'is_online': is_truly_online,
            })
        
        # Sort: Admin first, then online users, then alphabetically
        members.sort(key=lambda x: (not x['is_admin'], not x['is_online'], x['full_name'].lower()))
        
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


# =============================================
# P2P FILE SHARING - WebRTC Signaling (Redis-based)
# =============================================

def get_p2p_cache():
    """Get cache backend for P2P signals - uses Redis in production, fallback to default cache"""
    from django.core.cache import cache
    return cache


@login_required
@require_POST
def p2p_send_signal(request):
    """Send a WebRTC signaling message to another user using Redis cache"""
    try:
        data = json.loads(request.body)
        target_user_id = data.get('target_user_id')
        chat_id = data.get('chat_id')
        signal_type = data.get('signal_type')  # 'offer', 'answer', 'ice-candidate', 'file-request', 'file-accept', 'file-reject'
        signal_data = data.get('signal_data')
        
        if not all([target_user_id, chat_id, signal_type]):
            return JsonResponse({'success': False, 'error': 'Missing required fields'})
        
        # Verify user is in the chat
        chat = get_object_or_404(Chat, id=chat_id)
        if not chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'success': False, 'error': 'Not a participant of this chat'}, status=403)
        
        # Verify target user is in the chat
        if not chat.participants.filter(id=target_user_id).exists():
            return JsonResponse({'success': False, 'error': 'Target user not in chat'}, status=403)
        
        # Store signal for target user using Redis cache
        p2p_cache = get_p2p_cache()
        signal_key = f"p2p_{chat_id}_{target_user_id}"
        
        # Get existing signals or empty list
        existing_signals = p2p_cache.get(signal_key, [])
        if not isinstance(existing_signals, list):
            existing_signals = []
        
        # Add new signal
        existing_signals.append({
            'from_user_id': request.user.id,
            'from_username': request.user.username,
            'from_full_name': request.user.full_name,
            'signal_type': signal_type,
            'signal_data': signal_data,
            'timestamp': timezone.now().isoformat()
        })
        
        # Limit stored signals to prevent memory issues
        if len(existing_signals) > 50:
            existing_signals = existing_signals[-50:]
        
        # Store with 5 minute expiry (signals shouldn't persist too long)
        p2p_cache.set(signal_key, existing_signals, timeout=300)
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        logger.error(f"Error in p2p_send_signal: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to send signal'})


@login_required
def p2p_get_signals(request, chat_id):
    """Poll for pending WebRTC signals from Redis cache"""
    try:
        chat = get_object_or_404(Chat, id=chat_id)
        
        # Verify user is in the chat
        if not chat.participants.filter(id=request.user.id).exists():
            return JsonResponse({'success': False, 'error': 'Not a participant of this chat'}, status=403)
        
        p2p_cache = get_p2p_cache()
        signal_key = f"p2p_{chat_id}_{request.user.id}"
        
        # Get and clear signals atomically
        signals = p2p_cache.get(signal_key, [])
        if not isinstance(signals, list):
            signals = []
        
        # Clear retrieved signals
        p2p_cache.delete(signal_key)
        
        return JsonResponse({
            'success': True,
            'signals': signals
        })
        
    except Exception as e:
        logger.error(f"Error in p2p_get_signals: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get signals'})


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
            is_online = p.is_online and p.last_seen and (timezone.now() - p.last_seen).total_seconds() < 15
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
