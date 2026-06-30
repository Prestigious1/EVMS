from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from users import views
from users import admin_views

app_name = "users"


urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_view, name="register"),
    path("profile/", views.profile_view, name="profile"),

    # Admin Management Routes
    path("admin/list/", admin_views.admin_user_list, name="admin_user_list"),
    path("admin/create/", admin_views.admin_user_create, name="admin_user_create"),
    path("admin/<int:pk>/", admin_views.admin_user_detail, name="admin_user_detail"),
    path("admin/<int:pk>/edit/", admin_views.admin_user_update, name="admin_user_update"),


    # Password reset (success_url must use app namespace — avoids NoReverseMatch for password_reset_done)
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="users/password_reset_form.html",
            success_url=reverse_lazy("users:password_reset_done"),
            email_template_name="users/password_reset_email.html",
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="users/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="users/password_reset_confirm.html",
            success_url=reverse_lazy("users:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(template_name="users/password_reset_complete.html"),
        name="password_reset_complete",
    ),
]

