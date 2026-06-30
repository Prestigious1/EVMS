from django.urls import path

from hall import views

app_name = "hall"

urlpatterns = [
    # ── Public pages ───────────────────────────────────────────────
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("staff-dashboard/", views.staff_dashboard, name="staff_dashboard"),
    path("department-dashboard/", views.department_dashboard, name="department_dashboard"),
    path("bookmarks/", views.my_bookmarks, name="bookmarks"),
    path("faq/", views.faq_page, name="faq"),
    path("announcements/", views.announcements_page, name="announcements"),
    path("announcements/<int:pk>/", views.announcement_detail, name="announcement_detail"),
    path("contact/", views.contact_page, name="contact"),

    # ── Hall browsing ──────────────────────────────────────────────
    path("halls/", views.hall_list, name="hall_list"),
    path("halls/<int:pk>/", views.hall_detail, name="hall_detail"),
    path("halls/<int:pk>/bookmark/", views.toggle_bookmark, name="toggle_bookmark"),

    # ── Hall blocking ──────────────────────────────────────────────
    path("halls/<int:hall_id>/blocks/", views.hall_block_list, name="hall_block_list"),
    path("halls/<int:hall_id>/block/add/", views.hall_block_add, name="hall_block_add"),
    path("halls/<int:hall_id>/block/<int:block_id>/delete/", views.hall_block_delete, name="hall_block_delete"),

    # ── Hall management ────────────────────────────────────────────
    path("halls/manage/", views.hall_manage, name="hall_manage"),
    path("halls/manage/create/", views.hall_create, name="hall_create"),
    path("halls/manage/<int:pk>/edit/", views.hall_update, name="hall_update"),
    path("halls/manage/<int:pk>/delete/", views.hall_delete, name="hall_delete"),

    # ── Image management ───────────────────────────────────────────
    path(
        "halls/manage/<int:hall_id>/image/<int:image_id>/delete/",
        views.hall_image_delete,
        name="hall_image_delete",
    ),
    path(
        "halls/manage/<int:hall_id>/image/<int:image_id>/set-cover/",
        views.hall_image_set_cover,
        name="hall_image_set_cover",
    ),
    path(
        "halls/manage/<int:hall_id>/images/reorder/",
        views.hall_image_reorder,
        name="hall_image_reorder",
    ),
    path(
        "halls/manage/<int:hall_id>/image/<int:image_id>/replace/",
        views.hall_image_replace,
        name="hall_image_replace",
    ),

    # ── Amenity management ─────────────────────────────────────────
    path("halls/manage/amenities/", views.amenity_manage, name="amenity_manage"),
    path("halls/manage/amenities/save/", views.amenity_create, name="amenity_create"),
    path("halls/manage/amenities/<int:pk>/delete/", views.amenity_delete, name="amenity_delete"),

    # ── Communications dashboard ───────────────────────────────────
    path("communications/", views.communications_dashboard, name="communications_dashboard"),
    path("communications/broadcast/create/", views.broadcast_create_view, name="broadcast_create_view"),
    path("communications/broadcast/<int:pk>/delete/", views.broadcast_delete_view, name="broadcast_delete_view"),
    path("communications/announcement/create/", views.announcement_create_view, name="announcement_create_view"),
    path("communications/announcement/<int:pk>/edit/", views.announcement_edit_view, name="announcement_edit_view"),
    path("communications/announcement/<int:pk>/delete/", views.announcement_delete_view, name="announcement_delete_view"),
]
