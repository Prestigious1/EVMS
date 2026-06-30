def unread_notifications(request):
    if request.user.is_authenticated:
        from notifications.models import Notification
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return {"unread_notifications_count": count}
    return {}
