from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.timesince import timesince
import json
import os
import logging
from chat.models import CustomUser, Story, StoryView, StoryLike, StoryReply

logger = logging.getLogger(__name__)

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
                'time_ago': timesince(reply.created_at) + ' ago',
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
