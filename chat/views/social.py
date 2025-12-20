from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q, Max
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
import json
import hashlib
import logging
import re
from django.db import models as db_models

from chat.models import (
    CustomUser, Chat, Tweet, Comment, Like, Follow, Block, FollowRequest,
    Hashtag, TweetHashtag, Mention, StoryReply, StoryLike, Story,
    SavedPost, PostReport, Reel, ReelLike, ReelComment, ReelReport
)
from chat.forms import TweetForm, ProfileUpdateForm

logger = logging.getLogger(__name__)

# Global cache for preventing duplicate tweets
TWEET_CACHE_PREFIX = "prevent_duplicate_tweet_"
TWEET_COOLDOWN = 5  # 5 seconds between identical tweets


def generate_tweet_hash(user_id, content, has_image):
    """Generate unique hash for duplicate detection"""
    content_hash = hashlib.md5(
        f"{user_id}_{content.strip()}_{has_image}".encode()).hexdigest()
    return content_hash


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
        tweets_queryset = Tweet.objects.filter(user=profile_user).select_related(
            'user').distinct().order_by('-id', '-timestamp')
        processed_tweet_ids = set()

        for tweet in tweets_queryset:
            if tweet.id in processed_tweet_ids:
                continue
            processed_tweet_ids.add(tweet.id)

            like_count = Like.objects.filter(tweet=tweet).count()
            is_liked = Like.objects.filter(tweet=tweet, user=request.user).exists(
            ) if request.user.is_authenticated else False

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

    other_users = CustomUser.objects.exclude(
        id=request.user.id).distinct().order_by('name', 'lastname')

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
    user_chats = Chat.objects.filter(
        participants=request.user).order_by('-updated_at')[:20]
    all_chats = []
    for chat in user_chats:
        chat_info = {
            'id': chat.id,
            'name': chat.name,
            'is_group': chat.chat_type == 'group',
        }
        if chat.chat_type == 'private':
            other_participant = chat.participants.exclude(
                id=request.user.id).first()
            chat_info['other_user'] = other_participant
        last_message = chat.messages.order_by('-timestamp').first()
        if last_message:
            chat_info['last_message_preview'] = last_message.content[:50] + \
                ('...' if len(last_message.content) > 50 else '')
        else:
            chat_info['last_message_preview'] = None
        all_chats.append(chat_info)

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

    # Get user's active stories for highlights section
    user_stories = []
    if can_view_profile:
        from django.utils import timezone
        stories = Story.objects.filter(
            user=profile_user,
            is_active=True,
            expires_at__gt=timezone.now()
        ).order_by('-created_at')[:10]  # Get up to 10 recent stories

        for story in stories:
            user_stories.append({
                'id': story.id,
                'content': story.content,
                'media_url': story.media_url,
                'story_type': story.story_type,
                'background_color': story.background_color,
                'text_color': story.text_color,
                'created_at': story.created_at,
                'view_count': story.view_count,
            })

    # Get saved posts (only for own profile)
    saved_posts = []
    if is_own_profile:
        saved_items = SavedPost.objects.filter(user=request.user).select_related(
            'tweet', 'tweet__user').order_by('-created_at')
        for saved in saved_items:
            tweet = saved.tweet
            like_count = Like.objects.filter(tweet=tweet).count()
            is_liked = Like.objects.filter(
                tweet=tweet, user=request.user).exists()
            comment_count = Comment.objects.filter(tweet=tweet).count()

            saved_posts.append({
                'id': tweet.id,
                'content': tweet.content,
                'timestamp': tweet.timestamp,
                'user': tweet.user,
                'like_count': like_count,
                'is_liked': is_liked,
                'comment_count': comment_count,
                'image_url': tweet.image_url,
                'has_media': tweet.has_media,
                'saved_at': saved.created_at,
            })

    # Get Reels if profile is viewable
    reels = []
    if can_view_profile:
        reels = Reel.objects.filter(user=profile_user).order_by('-created_at')

    context = {
        'profile_user': profile_user,
        'tweets': tweets,
        'reels': reels,
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
        'unread_message_count': unread_message_count,
        'story_inbox_count': story_inbox_count,
        'user_stories': user_stories,  # Add stories for highlights
        'saved_posts': saved_posts,  # Add saved posts for own profile
    }

    # Use Instagram-style template
    return render(request, 'chat/profile_instagram.html', context)


@login_required
def update_profile(request):
    """Update user profile with cropped image support"""
    if request.method == 'POST':
        form = ProfileUpdateForm(
            request.POST, request.FILES, instance=request.user)

        # Check for cropped image data (base64)
        cropped_image_data = request.POST.get('profile_picture_cropped', '')

        # Capture old profile picture path safely
        old_profile_pic_path = None
        if request.user.profile_picture:
            try:
                old_profile_pic_path = request.user.profile_picture.path
            except:
                pass

        if form.is_valid():
            user = form.save(commit=False)

            # Handle cropped image if provided
            if cropped_image_data and cropped_image_data.startswith('data:image'):
                try:
                    import base64
                    import os
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

                    # Delete old profile picture if exists on disk
                    if old_profile_pic_path and os.path.exists(old_profile_pic_path):
                        try:
                            os.remove(old_profile_pic_path)
                        except Exception as e:
                            logger.warning(
                                f"Failed to delete old profile pic: {e}")

                    # Save new cropped image
                    # Compress before saving
                    try:
                        from PIL import Image
                        from io import BytesIO

                        img = Image.open(ContentFile(image_data))

                        # Resize if > 900px (Aggressive optimization)
                        if img.width > 900:
                            img.thumbnail(
                                (900, 900), Image.Resampling.LANCZOS)

                        # Re-compress as WebP
                        out_io = BytesIO()

                        if img.mode != 'RGB':
                            img = img.convert('RGB')

                        # Save as WebP with 70% quality
                        # This typically yields files < 100KB
                        img.save(out_io, format='WEBP',
                                 quality=70, optimize=True)

                        # Change filename extension to .webp
                        filename_base = filename.rsplit('.', 1)[0]
                        filename = f"{filename_base}.webp"

                        user.profile_picture.save(
                            filename, ContentFile(out_io.getvalue()), save=False)
                    except Exception as e:
                        logger.error(f"Profile pic compression failed: {e}")
                        # Fallback to uncompressed
                        user.profile_picture.save(
                            filename, ContentFile(image_data), save=False)

                except Exception as e:
                    logger.error(f"Error processing cropped image: {e}")
                    messages.error(
                        request, 'Error processing image. Please try again.')
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
    # Use Instagram-style template
    return render(request, 'chat/update_profile_instagram.html', context)


@login_required
@require_POST
def post_tweet(request):
    """Post a tweet with proper duplicate prevention and validation"""
    logger.info(f"Tweet post attempt by user {request.user.id}")

    try:
        # Parse form data properly
        content = request.POST.get('content', '').strip()
        image_file = request.FILES.get('image')

        logger.info(
            f"Content: {content[:50]}..., Has image: {bool(image_file)}")

        # Basic validation
        if not content and not image_file:
            return JsonResponse({'success': False, 'error': 'Tweet cannot be empty. Please add text or an image.'})

        if content and len(content) > 280:
            return JsonResponse({'success': False, 'error': 'Tweet must be 280 characters or less.'})

        # Duplicate prevention
        tweet_hash = generate_tweet_hash(
            request.user.id, content or '', bool(image_file))
        cache_key = f"{TWEET_CACHE_PREFIX}{tweet_hash}"

        # Check cache for recent duplicate
        if cache.get(cache_key):
            logger.warning(
                f"Duplicate tweet attempt blocked for user {request.user.id}")
            return JsonResponse({'success': False, 'error': f'Please wait {TWEET_COOLDOWN} seconds before posting the same tweet again.'})

        # Check database for recent duplicates (last 3 minutes)
        three_minutes_ago = timezone.now() - timezone.timedelta(minutes=3)
        recent_duplicate = Tweet.objects.filter(
            user=request.user,
            content=content or '',
            timestamp__gte=three_minutes_ago
        )

        if image_file:
            recent_duplicate = recent_duplicate.exclude(
                image__isnull=True).exclude(image='')
        else:
            recent_duplicate = recent_duplicate.filter(
                Q(image__isnull=True) | Q(image=''))

        if recent_duplicate.exists():
            logger.warning(
                f"Recent duplicate found in database for user {request.user.id}")
            return JsonResponse({'success': False, 'error': 'You already posted this tweet recently. Please wait before posting again.'})

        # Use Django form for proper validation
        form_data = {'content': content} if content else {}
        files_data = {'image': image_file} if image_file else {}

        form = TweetForm(form_data, files_data)
        if form.is_valid():
            # Create tweet using form
            tweet = form.save(commit=False)

            # Compress image if present
            if image_file:
                try:
                    from PIL import Image, ImageOps
                    from io import BytesIO
                    from django.core.files.base import ContentFile
                    import os

                    # Open image
                    img = Image.open(image_file)
                    img = ImageOps.exif_transpose(img)

                    # Resize if > 900px (Aggressive optimization for 100KB target)
                    if img.width > 900 or img.height > 900:
                        img.thumbnail((900, 900), Image.Resampling.LANCZOS)

                    # Compress - Force WebP for maximum storage efficiency
                    output_io = BytesIO()

                    if img.mode != 'RGB':
                        img = img.convert('RGB')

                    # Save as WebP with 70% quality
                    img.save(output_io, format='WEBP',
                             quality=70, optimize=True)

                    # Update the file in the model instance with .webp extension
                    original_name = os.path.splitext(image_file.name)[0]
                    new_filename = f"{original_name}_opt.webp"

                    if output_io.tell() > 0:
                        tweet.image = ContentFile(
                            output_io.getvalue(), name=new_filename)
                except Exception as e:
                    logger.error(f"Tweet image compression failed: {e}")
                    # If compression fails, it will just use the original file from form.save logic (managed by Django)

            tweet.user = request.user
            tweet.save()

            # Process hashtags and mentions
            process_tweet_hashtags_mentions(tweet)

            # Set cache to prevent immediate duplicates
            cache.set(cache_key, True, timeout=TWEET_COOLDOWN)

            logger.info(
                f"Tweet {tweet.id} created successfully by user {request.user.id}")

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
def toggle_save_post(request):
    """Toggle save/bookmark a post"""
    try:
        data = json.loads(request.body)
        tweet_id = data.get('tweet_id')

        if not tweet_id:
            return JsonResponse({'success': False, 'error': 'Tweet ID is required'})

        try:
            tweet = Tweet.objects.get(id=tweet_id)
        except Tweet.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Post not found'})

        # Toggle save
        saved_obj = SavedPost.objects.filter(
            user=request.user, tweet=tweet).first()

        if saved_obj:
            saved_obj.delete()
            is_saved = False
            message = 'Post removed from saved'
        else:
            SavedPost.objects.create(user=request.user, tweet=tweet)
            is_saved = True
            message = 'Post saved'

        return JsonResponse({
            'success': True,
            'is_saved': is_saved,
            'message': message
        })

    except Exception as e:
        logger.error(f"Error in toggle_save_post: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to save post'})


@login_required
@require_POST
def delete_post(request):
    """Delete a user's own post"""
    try:
        data = json.loads(request.body)
        tweet_id = data.get('tweet_id')

        if not tweet_id:
            return JsonResponse({'success': False, 'error': 'Tweet ID is required'})

        try:
            tweet = Tweet.objects.get(id=tweet_id)
        except Tweet.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Post not found'})

        # Only allow owner to delete
        if tweet.user != request.user:
            return JsonResponse({'success': False, 'error': 'You can only delete your own posts'})

        # Delete the image file if it exists
        if tweet.image:
            try:
                tweet.image.delete(save=False)
            except Exception:
                pass

        tweet.delete()

        return JsonResponse({
            'success': True,
            'message': 'Post deleted successfully'
        })

    except Exception as e:
        logger.error(f"Error in delete_post: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to delete post'})


@login_required
@require_POST
def report_post(request):
    """Report a post for inappropriate content"""
    try:
        data = json.loads(request.body)
        tweet_id = data.get('tweet_id')
        reason = data.get('reason')
        description = data.get('description', '').strip()

        if not tweet_id or not reason:
            return JsonResponse({'success': False, 'error': 'Tweet ID and reason are required'})

        valid_reasons = ['spam', 'inappropriate', 'harassment',
                         'violence', 'hate_speech', 'false_info', 'copyright', 'other']
        if reason not in valid_reasons:
            return JsonResponse({'success': False, 'error': 'Invalid report reason'})

        try:
            tweet = Tweet.objects.get(id=tweet_id)
        except Tweet.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Post not found'})

        # Can't report your own posts
        if tweet.user == request.user:
            return JsonResponse({'success': False, 'error': 'You cannot report your own post'})

        # Check if already reported by this user
        existing_report = PostReport.objects.filter(
            reporter=request.user, tweet=tweet).first()
        if existing_report:
            return JsonResponse({'success': False, 'error': 'You have already reported this post'})

        PostReport.objects.create(
            reporter=request.user,
            tweet=tweet,
            reason=reason,
            description=description
        )

        return JsonResponse({
            'success': True,
            'message': 'Thank you for your report. We will review it shortly.'
        })

    except Exception as e:
        logger.error(f"Error in report_post: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to report post'})


@login_required
def get_saved_posts(request):
    """Get all saved posts for the current user"""
    try:
        saved = SavedPost.objects.filter(
            user=request.user).select_related('tweet', 'tweet__user')

        posts = []
        for saved_post in saved:
            tweet = saved_post.tweet
            posts.append({
                'id': tweet.id,
                'content': tweet.content,
                'image_url': tweet.image_url,
                'user_username': tweet.user.username,
                'user_full_name': tweet.user.full_name,
                'user_profile_picture': tweet.user.profile_picture_url,
                'like_count': tweet.like_count,
                'comment_count': tweet.comment_count,
                'timestamp': tweet.timestamp.strftime('%b %d, %Y'),
                'saved_at': saved_post.created_at.strftime('%b %d, %Y'),
            })

        return JsonResponse({
            'success': True,
            'saved_posts': posts
        })

    except Exception as e:
        logger.error(f"Error in get_saved_posts: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get saved posts'})


@login_required
@require_POST
def copy_post_link(request):
    """Get the shareable link for a post"""
    try:
        data = json.loads(request.body)
        tweet_id = data.get('tweet_id')

        if not tweet_id:
            return JsonResponse({'success': False, 'error': 'Tweet ID is required'})

        try:
            tweet = Tweet.objects.get(id=tweet_id)
        except Tweet.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Post not found'})

        # Generate the post link using the request's host
        scheme = 'https' if request.is_secure() else 'http'
        host = request.get_host()
        post_link = f"{scheme}://{host}/post/{tweet_id}/"

        return JsonResponse({
            'success': True,
            'link': post_link,
            'message': 'Link copied to clipboard'
        })

    except Exception as e:
        logger.error(f"Error in copy_post_link: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get post link'})


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
def get_tweet(request, tweet_id):
    """Get a single tweet by ID"""
    try:
        from django.utils.timesince import timesince
        tweet = get_object_or_404(Tweet, id=tweet_id)

        # Check if user has liked this tweet
        is_liked = Like.objects.filter(user=request.user, tweet=tweet).exists()

        tweet_data = {
            'id': tweet.id,
            'content': tweet.content,
            'image_url': tweet.image_url,
            'username': tweet.user.username,
            'avatar': tweet.user.profile_picture_url,
            'full_name': tweet.user.full_name,
            'like_count': tweet.tweet_likes.count(),
            'comment_count': tweet.comments.count(),
            'is_liked': is_liked,
            'time_ago': timesince(tweet.timestamp) + ' ago',
            'timestamp': tweet.timestamp.isoformat(),
        }

        return JsonResponse({
            'success': True,
            'tweet': tweet_data
        })

    except Exception as e:
        logger.error(f"Error in get_tweet: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get tweet'})


def view_post(request, post_id):
    """View a single post - accessible without login for sharing"""
    try:
        tweet = get_object_or_404(Tweet, id=post_id)

        # If user is logged in, redirect to dashboard with the post highlighted
        if request.user.is_authenticated:
            return redirect(f'/dashboard/?post={post_id}')

        # If not logged in, redirect to login with next parameter
        return redirect(f'/login/?next=/post/{post_id}/')

    except Exception as e:
        logger.error(f"Error in view_post: {str(e)}")
        return redirect('/login/')


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
            # Check if there's a pending follow request
            existing_request = FollowRequest.objects.filter(
                requester=request.user,
                target=target_user,
                status='pending'
            ).first()

            if existing_request:
                # Cancel the pending request
                existing_request.delete()
                is_following = False
                follow_request_status = None
            elif target_user.is_private:
                # Send new follow request for private account
                # Clear any old declined requests first
                FollowRequest.objects.filter(
                    requester=request.user,
                    target=target_user
                ).delete()

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
            'username': username,
            'follower_count': target_user.follower_count
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
                requester=request.user,
                target=target_user
            ).delete()
            FollowRequest.objects.filter(
                requester=target_user,
                target=request.user
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
                Mention.objects.get_or_create(
                    tweet=tweet, mentioned_user=mentioned_user)
        except CustomUser.DoesNotExist:
            pass  # User doesn't exist, skip


@login_required
def get_hashtag_tweets(request, hashtag):
    """Get all tweets with a specific hashtag"""
    try:
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
        Mention.objects.filter(mentioned_user=request.user,
                               is_read=False).update(is_read=True)

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


@login_required
@require_POST
def update_theme(request):
    """Update user theme preference"""
    try:
        data = json.loads(request.body)
        theme = data.get('theme')

        # Validate theme
        valid_themes = [choice[0] for choice in CustomUser.THEME_CHOICES]
        if theme not in valid_themes:
            return JsonResponse({'success': False, 'error': 'Invalid theme'})

        request.user.theme = theme
        request.user.save(update_fields=['theme'])

        return JsonResponse({'success': True, 'theme': theme})
    except Exception as e:
        logger.error(f"Error updating theme: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to update theme'})


@login_required
def get_all_activity(request):
    """Get all activity for the current user - likes, comments, follows, story activity"""
    try:
        from django.utils.timesince import timesince
        from chat.models import Story, StoryView

        activity_items = []

        # 1. Post likes - people who liked MY posts (excluding my own likes)
        post_likes = Like.objects.filter(
            tweet__user=request.user
        ).exclude(user=request.user).select_related('user', 'tweet').order_by('-timestamp')[:20]

        for like in post_likes:
            activity_items.append({
                'type': 'post_like',
                'timestamp': like.timestamp,
                'user': {
                    'id': like.user.id,
                    'username': like.user.username,
                    'full_name': like.user.full_name,
                    'profile_picture_url': like.user.profile_picture_url,
                },
                'tweet': {
                    'id': like.tweet.id,
                    'content': like.tweet.content[:50] + '...' if len(like.tweet.content) > 50 else like.tweet.content,
                    'image_url': like.tweet.image_url,
                }
            })

        # 2. Post comments - people who commented on MY posts (excluding my own comments)
        post_comments = Comment.objects.filter(
            tweet__user=request.user
        ).exclude(user=request.user).select_related('user', 'tweet').order_by('-timestamp')[:20]

        for comment in post_comments:
            activity_items.append({
                'type': 'post_comment',
                'timestamp': comment.timestamp,
                'user': {
                    'id': comment.user.id,
                    'username': comment.user.username,
                    'full_name': comment.user.full_name,
                    'profile_picture_url': comment.user.profile_picture_url,
                },
                'tweet': {
                    'id': comment.tweet.id,
                    'content': comment.tweet.content[:50] + '...' if len(comment.tweet.content) > 50 else comment.tweet.content,
                },
                'comment_content': comment.content[:80] + '...' if len(comment.content) > 80 else comment.content,
            })

        # 3. New followers
        new_followers = Follow.objects.filter(
            following=request.user
        ).select_related('follower').order_by('-created_at')[:20]

        for follow in new_followers:
            activity_items.append({
                'type': 'follow',
                'timestamp': follow.created_at,
                'user': {
                    'id': follow.follower.id,
                    'username': follow.follower.username,
                    'full_name': follow.follower.full_name,
                    'profile_picture_url': follow.follower.profile_picture_url,
                }
            })

        # 4. Story likes
        story_likes = StoryLike.objects.filter(
            story__user=request.user
        ).exclude(user=request.user).select_related('user', 'story').order_by('-created_at')[:20]

        for like in story_likes:
            activity_items.append({
                'type': 'story_like',
                'timestamp': like.created_at,
                'user': {
                    'id': like.user.id,
                    'username': like.user.username,
                    'full_name': like.user.full_name,
                    'profile_picture_url': like.user.profile_picture_url,
                },
                'story': {
                    'id': like.story.id,
                    'story_type': like.story.story_type,
                }
            })

        # 5. Story replies
        story_replies = StoryReply.objects.filter(
            story__user=request.user
        ).exclude(replier=request.user).select_related('replier', 'story').order_by('-created_at')[:20]

        for reply in story_replies:
            activity_items.append({
                'type': 'story_reply',
                'timestamp': reply.created_at,
                'is_read': reply.is_read,
                'user': {
                    'id': reply.replier.id,
                    'username': reply.replier.username,
                    'full_name': reply.replier.full_name,
                    'profile_picture_url': reply.replier.profile_picture_url,
                },
                'story': {
                    'id': reply.story.id,
                    'story_type': reply.story.story_type,
                },
                'content': reply.content[:80] + '...' if len(reply.content) > 80 else reply.content,
            })

        # 6. Post Reports - Notify the user that they have been reported
        post_reports = PostReport.objects.filter(
            tweet__user=request.user
        ).select_related('reporter', 'tweet').order_by('-created_at')[:20]

        for report in post_reports:
            activity_items.append({
                'type': 'post_report',
                'timestamp': report.created_at,
                'user': {
                    'id': report.reporter.id,
                    'username': report.reporter.username,
                    'full_name': report.reporter.full_name,
                    'profile_picture_url': report.reporter.profile_picture_url,
                },
                'tweet': {
                    'id': report.tweet.id,
                    'content': report.tweet.content[:50] + '...' if len(report.tweet.content) > 50 else report.tweet.content,
                },
                'reason': report.get_reason_display(),
            })

        # 7. Reel Reports - Notify the user that they have been reported
        reel_reports = ReelReport.objects.filter(
            reel__user=request.user
        ).select_related('reporter', 'reel').order_by('-created_at')[:20]

        for report in reel_reports:
            activity_items.append({
                'type': 'reel_report',
                'timestamp': report.created_at,
                'user': {
                    'id': report.reporter.id,
                    'username': report.reporter.username,
                    'full_name': report.reporter.full_name,
                    'profile_picture_url': report.reporter.profile_picture_url,
                },
                'reel': {
                    'id': report.reel.id,
                    'caption': report.reel.caption[:50] + '...' if len(report.reel.caption) > 50 else report.reel.caption,
                },
                'reason': report.get_reason_display(),
            })

        # 8. My Reports - Content the current user reported (show for reporter)
        my_post_reports = PostReport.objects.filter(
            reporter=request.user
        ).select_related('tweet', 'tweet__user').order_by('-created_at')[:20]

        for report in my_post_reports:
            activity_items.append({
                'type': 'my_post_report',
                'timestamp': report.created_at,
                'user': {  # target content owner
                    'id': report.tweet.user.id,
                    'username': report.tweet.user.username,
                    'full_name': report.tweet.user.full_name,
                    'profile_picture_url': report.tweet.user.profile_picture_url,
                },
                'tweet': {
                    'id': report.tweet.id,
                    'content': report.tweet.content[:50] + '...' if len(report.tweet.content) > 50 else report.tweet.content,
                },
                'reason': report.get_reason_display(),
            })

        my_reel_reports = ReelReport.objects.filter(
            reporter=request.user
        ).select_related('reel', 'reel__user').order_by('-created_at')[:20]

        for report in my_reel_reports:
            activity_items.append({
                'type': 'my_reel_report',
                'timestamp': report.created_at,
                'user': {  # target content owner
                    'id': report.reel.user.id,
                    'username': report.reel.user.username,
                    'full_name': report.reel.user.full_name,
                    'profile_picture_url': report.reel.user.profile_picture_url,
                },
                'reel': {
                    'id': report.reel.id,
                    'caption': report.reel.caption[:50] + '...' if len(report.reel.caption) > 50 else report.reel.caption,
                },
                'reason': report.get_reason_display(),
            })

        # Sort all activity by timestamp (newest first)
        activity_items.sort(key=lambda x: x['timestamp'], reverse=True)

        # Take top 50 items
        activity_items = activity_items[:50]

        # Add time_ago to each item
        now = timezone.now()
        for item in activity_items:
            item['time_ago'] = timesince(item['timestamp']) + ' ago'
            item['timestamp'] = item['timestamp'].isoformat()

        return JsonResponse({
            'success': True,
            'activity': activity_items
        })

    except Exception as e:
        logger.error(f"Error getting all activity: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': 'Failed to get activity'})


@login_required
def get_profile_followers(request, username):
    """Get list of followers for a user profile"""
    try:
        user = get_object_or_404(CustomUser, username=username)

        # Get followers (people who follow this user)
        followers = Follow.objects.filter(
            following=user).select_related('follower')

        followers_data = []
        for follow in followers:
            follower = follow.follower
            followers_data.append({
                'id': follower.id,
                'username': follower.username,
                'full_name': follower.full_name,
                'avatar': follower.profile_picture_url,
                'is_following': Follow.objects.filter(
                    follower=request.user, following=follower
                ).exists() if request.user.is_authenticated else False
            })

        return JsonResponse({
            'success': True,
            'followers': followers_data
        })

    except Exception as e:
        logger.error(f"Error getting followers: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get followers'})


@login_required
def get_profile_following(request, username):
    """Get list of users that a profile is following"""
    try:
        user = get_object_or_404(CustomUser, username=username)

        # Get following (people this user follows)
        following = Follow.objects.filter(
            follower=user).select_related('following')

        following_data = []
        for follow in following:
            followed_user = follow.following
            following_data.append({
                'id': followed_user.id,
                'username': followed_user.username,
                'full_name': followed_user.full_name,
                'avatar': followed_user.profile_picture_url,
                'is_following': Follow.objects.filter(
                    follower=request.user, following=followed_user
                ).exists() if request.user.is_authenticated else False
            })

        return JsonResponse({
            'success': True,
            'following': following_data
        })

    except Exception as e:
        logger.error(f"Error getting following: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to get following'})


@login_required
def reels_view(request):
    """View to watch and scroll through reels"""
    from chat.recommendations import ContentRecommender

    # Use Recommendation Engine
    recommender = ContentRecommender(request.user)
    reels = recommender.get_reels(limit=50)

    # Process reels for the frontend
    reels_data = []
    for reel in reels:
        reels_data.append({
            'id': reel.id,
            'url': reel.video_file.url,
            'caption': reel.caption,
            'user': reel.user,
            'likes': reel.like_count,
            'comments_count': reel.comment_count,
            'is_liked': reel.is_liked_by(request.user),
            'views': reel.views_count,
            'timestamp': reel.created_at,
        })

    return render(request, 'chat/reels.html', {
        'reels': reels_data
    })


@login_required
@require_POST
def track_reel_view(request):
    """API endpoint to track when a user watches a specific reel"""
    try:
        data = json.loads(request.body)
        reel_id = data.get('reel_id')

        if not reel_id:
            return JsonResponse({'error': 'reel_id required'}, status=400)

        reel = get_object_or_404(Reel, id=reel_id)

        # Increment view count only for this reel
        reel.views_count += 1
        reel.save(update_fields=['views_count'])

        return JsonResponse({
            'status': 'success',
            'views': reel.views_count
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error tracking reel view: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def upload_reel(request):
    """API to upload a new reel with compression"""
    import os
    import tempfile
    # CHECK DAILY LIMIT (5 reels per day)
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = Reel.objects.filter(
        user=request.user,
        created_at__gte=today_start
    ).count()

    if today_count >= 5:
        return JsonResponse({
            'success': False,
            'error': 'Daily reel limit reached. You can upload up to 5 reels per day. Try again tomorrow!'
        })

    # Try to import MoviePy lazily so missing dependency won't 500
    moviepy_available = True
    try:
        from moviepy.editor import VideoFileClip
    except Exception:
        moviepy_available = False

    try:
        video_file = request.FILES.get('video')
        caption = request.POST.get('caption', '')

        if not video_file:
            return JsonResponse({'success': False, 'error': 'No video provided'})

        # SECURITY CHECK (Magic Bytes)
        try:
            from chat.security import validate_media_file
            if video_file:
                validate_media_file(video_file)
        except ValidationError as e:
            return JsonResponse({'success': False, 'error': str(e)})

        # Create temp file for original video
        # Create temp file for original video
        # On Windows, we must close the file before MoviePy can open it
        temp_in = tempfile.NamedTemporaryFile(
            suffix=os.path.splitext(video_file.name)[1], delete=False)
        try:
            for chunk in video_file.chunks():
                temp_in.write(chunk)
            temp_in_path = temp_in.name
        finally:
            temp_in.close()

        # If MoviePy isn't available, save original without compression
        if not moviepy_available:
            reel = Reel.objects.create(
                user=request.user,
                video_file=video_file,
                caption=caption
            )
            if os.path.exists(temp_in_path):
                os.remove(temp_in_path)
            return JsonResponse({'success': True, 'message': 'Reel uploaded (no compression available)'})

        try:
            # Load video
            clip = VideoFileClip(temp_in_path)

            # Track original size for smart fallback
            original_size = os.path.getsize(temp_in_path)

            # --- COMPRESSION LOGIC ---
            # 1) Resize if too wide (keep aspect ratio)
            try:
                max_width = max(
                    int(getattr(settings, 'REELS_MAX_WIDTH', 720)), 1)
                if getattr(clip, 'w', 0) and clip.w > max_width:
                    # MoviePy API variants: prefer resize; keep existing method name if available
                    if hasattr(clip, 'resize'):
                        clip = clip.resize(width=max_width)
                    else:
                        clip = clip.resized(width=max_width)
            except Exception:
                pass

            # 2) Limit duration
            # 2) Limit duration
            try:
                max_duration = max(
                    int(getattr(settings, 'REELS_MAX_DURATION', 120)), 1)
                if getattr(clip, 'duration', 0) and clip.duration > max_duration:
                    try:
                        clip.close()
                    except:
                        pass
                    return JsonResponse({
                        'success': False,
                        'error': f'Reel is too long. Maximum allowed duration is {max_duration // 60} minutes.'
                    })
            except Exception:
                pass

            # 3) Choose sensible FPS: cap if higher, otherwise keep
            try:
                current_fps = int(getattr(clip, 'fps', 30) or 30)
            except Exception:
                current_fps = 30
            fps_cap = max(int(getattr(settings, 'REELS_MAX_FPS', 30)), 1)
            target_fps = min(current_fps, fps_cap)

            # Create temp file for compressed output (.mp4 enforced)
            temp_out_path = os.path.join(tempfile.gettempdir(
            ), f"compressed_{os.path.basename(temp_in_path)}")
            temp_out_path = os.path.splitext(temp_out_path)[0] + ".mp4"

            # 4) Calculate target bitrate for 8MB limit
            # Target Size: 8MB = 8 * 1024 * 1024 bytes = 8388608 bytes = 67108864 bits
            # Audio Bitrate: 96k = 96000 bps
            # Duration: clip.duration (seconds)

            target_size_bytes = 8 * 1024 * 1024
            duration = clip.duration if clip.duration else 1
            audio_bitrate_kbps = 96

            # Calculate video bitrate
            total_bits = target_size_bytes * 8
            audio_bits = audio_bitrate_kbps * 1000 * duration
            video_bits_available = total_bits - audio_bits

            # Safety margin (5%) for container overhead
            video_bits_available = video_bits_available * 0.95

            target_video_bitrate_bps = video_bits_available / duration

            # Convert to string with 'k' suffix for moviepy/ffmpeg
            # Ensure at least 100k bitrate so it doesn't break completely
            video_bitrate = f"{max(int(target_video_bitrate_bps / 1000), 100)}k"

            preset = str(getattr(settings, 'REELS_PRESET', 'veryfast'))
            audio_bitrate = f"{audio_bitrate_kbps}k"

            clip.write_videofile(
                temp_out_path,
                codec='libx264',
                audio_codec='aac',
                audio_bitrate=audio_bitrate,
                bitrate=video_bitrate,
                temp_audiofile='temp-audio.m4a',
                remove_temp=True,
                fps=target_fps,
                logger=None,
                ffmpeg_params=[
                    '-preset', preset,
                    '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart'
                ]
            )

            # Close to flush handles on Windows before re-opening
            try:
                clip.close()
            except Exception:
                pass

            # Decide which file to save: use compressed only if smaller (smart fallback)
            use_path = temp_out_path
            try:
                compressed_size = os.path.getsize(temp_out_path)
                smart_fallback = bool(
                    getattr(settings, 'REELS_SMART_FALLBACK', True))
                # If compression didn't help and smart fallback enabled, keep original
                if smart_fallback and compressed_size >= max(original_size - 1024, 0):
                    use_path = temp_in_path
            except Exception:
                use_path = temp_out_path if os.path.exists(
                    temp_out_path) else temp_in_path

            # Save to model
            force_mp4 = bool(getattr(settings, 'REELS_FORCE_MP4', True))
            save_name = f"reel_{request.user.id}_{os.path.splitext(video_file.name)[0]}.mp4"
            if use_path == temp_in_path:
                # Preserve original extension when keeping the original
                orig_ext = os.path.splitext(video_file.name)[1] or '.mp4'
                save_name = f"reel_{request.user.id}_{os.path.splitext(video_file.name)[0]}{(orig_ext if not force_mp4 else '.mp4')}"

            with open(use_path, 'rb') as f:
                django_file = File(f, name=save_name)
                reel = Reel.objects.create(
                    user=request.user,
                    video_file=django_file,
                    caption=caption
                )

            # Cleanup temp files
            if os.path.exists(temp_out_path):
                try:
                    os.remove(temp_out_path)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Compression failed, falling back to original: {e}")
            # Fallback: Save original if anything goes wrong
            reel = Reel.objects.create(
                user=request.user,
                video_file=video_file,
                caption=caption
            )
        finally:
            # Always cleanup input temp file
            if os.path.exists(temp_in_path):
                os.remove(temp_in_path)

        return JsonResponse({'success': True, 'message': 'Reel uploaded successfully'})
    except Exception as e:
        logger.error(f"Error uploading reel: {str(e)}")
        return JsonResponse({'success': False, 'error': f'Failed to upload reel: {str(e)}'})


@login_required
@require_POST
def toggle_reel_like(request):
    """API to like/unlike a reel"""
    try:
        data = json.loads(request.body)
        reel_id = data.get('reel_id')
        reel = get_object_or_404(Reel, id=reel_id)

        like = ReelLike.objects.filter(reel=reel, user=request.user).first()
        if like:
            like.delete()
            is_liked = False
        else:
            ReelLike.objects.create(reel=reel, user=request.user)
            is_liked = True

        return JsonResponse({
            'success': True,
            'is_liked': is_liked,
            'likes_count': reel.like_count
        })
    except Exception as e:
        logger.error(f"Error toggling reel like: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Action failed'})


@login_required
def get_reel_comments(request, reel_id):
    """Return comments for a reel (latest first)."""
    try:
        reel = get_object_or_404(Reel, id=reel_id)
        limit = int(request.GET.get('limit', 20))
        offset = int(request.GET.get('offset', 0))

        qs = ReelComment.objects.filter(reel=reel).select_related(
            'user').order_by('-created_at')
        total = qs.count()
        comments = []
        for rc in qs[offset:offset+limit]:
            comments.append({
                'id': rc.id,
                'content': rc.content,
                'created_at': rc.created_at.isoformat(),
                'user': {
                    'id': rc.user.id,
                    'username': rc.user.username,
                    'full_name': rc.user.full_name,
                    'avatar': rc.user.profile_picture_url,
                    'initials': rc.user.initials,
                }
            })

        return JsonResponse({
            'success': True,
            'total': total,
            'comments': comments,
        })
    except Exception as e:
        logger.error(f"Error getting reel comments: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to load comments'})


@login_required
@require_POST
def add_reel_comment(request):
    """Add a comment to a reel."""
    try:
        data = json.loads(request.body)
        reel_id = data.get('reel_id')
        content = (data.get('content') or '').strip()

        if not reel_id:
            return JsonResponse({'success': False, 'error': 'reel_id required'}, status=400)
        if not content:
            return JsonResponse({'success': False, 'error': 'Comment cannot be empty'}, status=400)
        if len(content) > 500:
            return JsonResponse({'success': False, 'error': 'Comment too long (max 500)'}, status=400)

        reel = get_object_or_404(Reel, id=reel_id)
        rc = ReelComment.objects.create(
            reel=reel, user=request.user, content=content)

        return JsonResponse({
            'success': True,
            'comment': {
                'id': rc.id,
                'content': rc.content,
                'created_at': rc.created_at.isoformat(),
                'user': {
                    'id': request.user.id,
                    'username': request.user.username,
                    'full_name': request.user.full_name,
                    'avatar': request.user.profile_picture_url,
                    'initials': request.user.initials,
                }
            },
            'comments_count': reel.comment_count,
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error adding reel comment: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to add comment'})


@login_required
@require_POST
def report_reel(request):
    """Report a reel for inappropriate content"""
    try:
        data = json.loads(request.body)
        reel_id = data.get('reel_id')
        reason = data.get('reason')
        description = data.get('description', '').strip()

        if not reel_id or not reason:
            return JsonResponse({'success': False, 'error': 'Reel ID and reason are required'})

        valid_reasons = ['spam', 'inappropriate', 'harassment',
                         'violence', 'hate_speech', 'false_info', 'copyright', 'other']
        if reason not in valid_reasons:
            return JsonResponse({'success': False, 'error': 'Invalid report reason'})

        try:
            reel = Reel.objects.get(id=reel_id)
        except Reel.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Reel not found'})

        # Can't report your own reels
        if reel.user == request.user:
            return JsonResponse({'success': False, 'error': 'You cannot report your own reel'})

        # Check if already reported by this user
        existing_report = ReelReport.objects.filter(
            reporter=request.user, reel=reel).first()
        if existing_report:
            return JsonResponse({'success': False, 'error': 'You have already reported this reel'})

        ReelReport.objects.create(
            reporter=request.user,
            reel=reel,
            reason=reason,
            description=description
        )

        return JsonResponse({
            'success': True,
            'message': 'Thank you for your report. We will review it shortly.'
        })

    except Exception as e:
        logger.error(f"Error in report_reel: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to report reel'})
