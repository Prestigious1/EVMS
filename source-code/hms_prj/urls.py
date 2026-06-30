"""hms_prj URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from core import views as core_views

admin.site.site_header = "EVMS Administration"
admin.site.site_title = "EVMS Admin"
admin.site.index_title = "Welcome to the LASU Electronic Venue Management System"

urlpatterns = [
    path('admin/', admin.site.urls),

    # Apps Routes
    path("", include("hall.urls")),
    path("users/", include("users.urls")),
    path("reservations/", include("reservations.urls")),
    path("payments/", include("payments.urls")),
    path("notifications/", include("notifications.urls")),
    path("reports/", include("reports.urls")),
    path("system/logs/", core_views.admin_system_logs, name="admin_system_logs"),

    # Ckeditor
    path("ckeditor5/", include('django_ckeditor_5.urls')),

]

handler403 = core_views.custom_403
handler404 = core_views.custom_404
handler500 = core_views.custom_500


if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

