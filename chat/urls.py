# urls.py - FIXED - All URLs with correct function names

from django.urls import path, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from . import views


urlpatterns = [
    # Authentication URLs
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),

    # Email verification URL
    path('verify-email/<str:token>/', views.verify_email, name='verify_email'),

    # Main application URLs
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/update/', views.update_profile, name='update_profile'),
    path('profile/<str:username>/', views.profile_view, name='user_profile'),
    path('chat/<int:chat_id>/', views.chat_view, name='chat_detail'),
    path('delete-message-for-me/<int:message_id>/',
         views.delete_message_for_me, name='delete_message_for_me'),
    path('delete-message-for-everyone/<int:message_id>/',
         views.delete_message_for_everyone, name='delete_message_for_everyone'),

    # Group join URL
    path('join-group/<str:invite_code>/',
         views.join_group_view, name='join_group'),

    # Group discovery URL
    path('discover-groups/', views.discover_groups_view, name='discover_groups'),
    path('api/explore/load-more/', views.load_more_explore_content,
         name='load_more_explore'),

    # FIXED: Media serving URL with correct parameter name
    re_path(r'^media/(?P<file_path>.*)$',
            views.serve_media_file, name='serve_media'),

    # Story URLs
    path('api/create-story/', views.create_story, name='create_story'),
    path('api/story/<int:story_id>/', views.view_story, name='view_story'),
    # NEW: User stories API endpoint
    path('api/user-stories/<str:username>/',
         views.get_user_stories, name='get_user_stories'),

    # Tweet URLs - Enhanced
    path('api/post-tweet/', views.post_tweet, name='post_tweet'),
    path('api/toggle-like/', views.toggle_like, name='toggle_like'),
    path('api/toggle-save-post/', views.toggle_save_post, name='toggle_save_post'),
    path('api/delete-post/', views.delete_post, name='delete_post'),
    path('api/report-post/', views.report_post, name='report_post'),
    path('api/saved-posts/', views.get_saved_posts, name='get_saved_posts'),
    path('api/copy-post-link/', views.copy_post_link, name='copy_post_link'),

    # Single post view (for shared links)
    path('post/<int:post_id>/', views.view_post, name='view_post'),

    # Comment URLs
    path('api/add-comment/', views.add_comment, name='add_comment'),
    path('api/tweet/<int:tweet_id>/', views.get_tweet, name='get_tweet'),
    path('api/tweet/<int:tweet_id>/comments/',
         views.get_tweet_comments, name='get_tweet_comments'),

    # Chat API endpoints - FIXED
    path('api/chats/', views.get_chats_api, name='get_chats_api'),
    path('api/send-message/', views.send_message, name='send_message'),
    path('api/chat/<int:chat_id>/messages/',
         views.get_chat_messages, name='get_chat_messages'),
    path('api/create-chat/', views.create_chat, name='create_chat'),
    path('api/create-group/', views.create_group, name='create_group'),
    path('api/join-group/', views.join_group_api, name='join_group_api'),
    path('api/manage-join-request/', views.manage_join_request,
         name='manage_join_request'),

    path('api/consume-message/<int:message_id>/',
         views.consume_one_time_message, name='consume_message'),
    path('api/mark-read/<int:message_id>/',
         views.mark_message_read, name='mark_message_read'),
    path('api/react-message/<int:message_id>/',
         views.react_to_message, name='react_message'),
    path('api/chat/<int:chat_id>/typing/',
         views.update_typing_status, name='update_typing'),
    path('api/chat/<int:chat_id>/typing-status/',
         views.get_typing_status, name='get_typing_status'),
    # Follow system
    path('api/toggle-follow/', views.toggle_follow, name='toggle_follow'),
    path('api/follow-states/', views.follow_states, name='follow_states'),
    path('api/toggle-block/', views.toggle_block, name='toggle_block'),
    path('api/manage-follow-request/', views.manage_follow_request,
         name='manage_follow_request'),
    path('api/follow-requests/', views.get_follow_requests,
         name='get_follow_requests'),
    path('api/toggle-account-privacy/', views.toggle_account_privacy,
         name='toggle_account_privacy'),
    path('api/profile/<str:username>/followers/',
         views.get_profile_followers, name='get_profile_followers'),
    path('api/profile/<str:username>/following/',
         views.get_profile_following, name='get_profile_following'),

    # Story API endpoints - Instagram-like features
    path('api/story/mark-viewed/', views.mark_story_viewed,
         name='mark_story_viewed'),
    path('api/story/toggle-like/', views.toggle_story_like,
         name='toggle_story_like'),
    path('api/story/add-reply/', views.add_story_reply, name='add_story_reply'),
    path('api/story/<int:story_id>/replies/',
         views.get_story_replies, name='get_story_replies'),
    path('api/story/<int:story_id>/viewers/',
         views.get_story_viewers, name='get_story_viewers'),
    path('api/replies/<int:reply_id>/delete/',
         views.delete_reply, name='delete_reply'),
    path('api/story-inbox/', views.get_story_inbox, name='get_story_inbox'),
    path('api/story-inbox/count/', views.get_story_inbox_count,
         name='get_story_inbox_count'),
    path('api/activity/', views.get_all_activity, name='get_all_activity'),

    # Message Editing feature
    path('api/edit-message/<int:message_id>/',
         views.edit_message, name='edit_message'),

    # Pinned Messages feature
    path('api/pin-message/<int:message_id>/',
         views.pin_message, name='pin_message'),
    path('api/unpin-message/<int:message_id>/',
         views.unpin_message, name='unpin_message'),
    path('api/chat/<int:chat_id>/pinned-messages/',
         views.get_pinned_messages, name='get_pinned_messages'),

    # Pin/Unpin Chat (conversation)
    path('api/pin-chat/<int:chat_id>/', views.pin_chat, name='pin_chat'),
    path('api/unpin-chat/<int:chat_id>/', views.unpin_chat, name='unpin_chat'),

    # Hashtag & Mention features
    path('api/hashtag/<str:hashtag>/',
         views.get_hashtag_tweets, name='get_hashtag_tweets'),
    path('api/trending-hashtags/', views.get_trending_hashtags,
         name='get_trending_hashtags'),
    path('api/mentions/', views.get_user_mentions, name='get_user_mentions'),
    path('api/search-users/', views.search_users_for_mention,
         name='search_users_for_mention'),

    # Starred Messages feature
    path('api/star-message/<int:message_id>/',
         views.toggle_star_message, name='toggle_star_message'),
    path('api/starred-messages/', views.get_starred_messages,
         name='get_starred_messages'),
    path('api/message/<int:message_id>/is-starred/',
         views.is_message_starred, name='is_message_starred'),

    # Read Receipts feature
    path('api/chat/<int:chat_id>/mark-read/',
         views.mark_messages_read, name='mark_messages_read'),
    path('api/message/<int:message_id>/read-status/',
         views.get_message_read_status, name='get_message_read_status'),
    path('api/chat/<int:chat_id>/read-status/',
         views.get_chat_read_status, name='get_chat_read_status'),

    # User Online Status
    path('api/user/heartbeat/', views.user_heartbeat, name='user_heartbeat'),
    path('api/user/<int:user_id>/online-status/',
         views.get_user_online_status, name='get_user_online_status'),
    path('api/user/update-theme/', views.update_theme, name='update_theme'),
    path('api/chat/<int:chat_id>/participant-status/',
         views.get_chat_participant_status, name='get_chat_participant_status'),

    # Group Management
    path('api/group/<int:chat_id>/details/',
         views.get_group_details, name='get_group_details'),
    path('api/group/<int:chat_id>/update-settings/',
         views.update_group_settings, name='update_group_settings'),
    path('api/group/<int:chat_id>/remove-member/',
         views.remove_group_member, name='remove_group_member'),
    path('api/group/<int:chat_id>/leave/',
         views.leave_group, name='leave_group'),
    path('api/group/<int:chat_id>/regenerate-invite/',
         views.regenerate_invite_code, name='regenerate_invite_code'),

    # P2P File Sharing (WebRTC Signaling)
    path('api/p2p/send-signal/', views.p2p_send_signal, name='p2p_send_signal'),
    path('api/p2p/<int:chat_id>/signals/',
         views.p2p_get_signals, name='p2p_get_signals'),
    path('api/p2p/<int:chat_id>/participants/',
         views.get_chat_participants_for_p2p, name='p2p_participants'),

    # Reels
    path('reels/', views.reels_view, name='reels'),
    path('api/reels/upload/', views.upload_reel, name='upload_reel'),
    path('api/reels/like/', views.toggle_reel_like, name='toggle_reel_like'),
    path('api/reels/track-view/', views.track_reel_view, name='track_reel_view'),
    path('api/reels/<int:reel_id>/comments/',
         views.get_reel_comments, name='get_reel_comments'),
    path('api/reels/comment/', views.add_reel_comment, name='add_reel_comment'),
    path('api/reels/report/', views.report_reel, name='report_reel'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
