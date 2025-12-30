from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from chat.models import Chat


@login_required
def unread_counts(request):
    user = request.user
    chats = Chat.objects.filter(participants=user)
    data = {}
    for chat in chats:
        unread = chat.messages.filter(
            is_read=False).exclude(sender=user).count()
        data[chat.id] = unread
    return JsonResponse({'counts': data})


@require_GET
def chat_partial(request, chat_id):
    # Dummy implementation for AJAX chat partial
    # Replace with your actual logic
    return JsonResponse({'success': True, 'chat_id': chat_id, 'html': '<div>Chat partial for chat_id {}</div>'.format(chat_id)})
