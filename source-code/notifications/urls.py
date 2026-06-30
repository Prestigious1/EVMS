from django.urls import path

from notifications import views


app_name = "notifications"


urlpatterns = [
    path("", views.inbox, name="inbox"),
    # Combined mark-read + redirect: the canonical action for notification buttons
    path("go/<int:pk>/", views.notification_go, name="go"),
    path("mark-read/<int:pk>/", views.mark_read, name="mark_read"),
    path("mark-all-read/", views.mark_all_read, name="mark_all_read"),
    path("delete/<int:pk>/", views.delete_notification, name="delete"),
    path("broadcasts/", views.broadcast_list, name="broadcast_list"),
    path("broadcasts/create/", views.broadcast_create, name="broadcast_create"),
]

