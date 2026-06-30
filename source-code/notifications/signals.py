from django.db.models.signals import post_save
from django.dispatch import receiver

from notifications.models import BroadcastMessage, Notification
from reservations.models import HallInspection, ReservationDocument, ReservationMessage, ThreadMessage
from users.models import User
from django.urls import reverse


@receiver(post_save, sender=BroadcastMessage)
def broadcast_message_create_notifications(sender, instance: BroadcastMessage, created: bool, **kwargs):
    if not created:
        return

    qs = User.objects.all()
    if instance.target_role:
        qs = qs.filter(role=instance.target_role)

    notifications = [
        Notification(user=u, title=instance.title, message=instance.message)
        for u in qs.iterator()
    ]
    Notification.objects.bulk_create(notifications, batch_size=500)


@receiver(post_save, sender=ThreadMessage)
def thread_message_notification(sender, instance: ThreadMessage, created: bool, **kwargs):
    if not created:
        return
    reservation = instance.thread.reservation
    from users.models import UserRole
    
    target_roles = [r.strip() for r in instance.target_roles.split(",") if r.strip()]
    
    recipients = []
    if "APPLICANT" in target_roles:
        recipients.append(reservation.user)
        
    staff_roles = []
    if "VENTURES" in target_roles:
        staff_roles.append(UserRole.VENTURES)
    if "BURSARY" in target_roles:
        staff_roles.append(UserRole.BURSARY)
    if "FACILITY" in target_roles:
        staff_roles.append(UserRole.FACILITY)
        
    # Always notify Admin
    staff_roles.append(UserRole.ADMIN)
    
    if staff_roles:
        staff = User.objects.filter(role__in=staff_roles, is_active=True)
        recipients.extend(staff)
        
    # Deduplicate recipients
    recipients = list(set(recipients))
    
    link = reverse("reservations:detail", kwargs={"booking_reference": reservation.booking_reference}) + "#communication"
    
    for user in recipients:
        if user == instance.sender:
            continue
        Notification.objects.create(
            user=user,
            title=f"New message on {reservation.booking_reference}",
            message=instance.content,
            link=link
        )


@receiver(post_save, sender=ReservationDocument)
def reservation_document_notification(sender, instance: ReservationDocument, created: bool, **kwargs):
    if not created:
        return
    reservation = instance.reservation
    from users.models import UserRole
    
    target_roles = [r.strip() for r in instance.visible_to.split(",") if r.strip()]
    
    recipients = []
    if "APPLICANT" in target_roles:
        recipients.append(reservation.user)
        
    staff_roles = []
    if "VENTURES" in target_roles:
        staff_roles.append(UserRole.VENTURES)
    if "BURSARY" in target_roles:
        staff_roles.append(UserRole.BURSARY)
    if "FACILITY" in target_roles:
        staff_roles.append(UserRole.FACILITY)
        
    staff_roles.append(UserRole.ADMIN)
    
    if staff_roles:
        staff = User.objects.filter(role__in=staff_roles, is_active=True)
        recipients.extend(staff)
        
    recipients = list(set(recipients))
    
    link = reverse("reservations:detail", kwargs={"booking_reference": reservation.booking_reference}) + "#documents"
    
    for user in recipients:
        if user == instance.uploaded_by:
            continue
        Notification.objects.create(
            user=user,
            title=f"Document uploaded on {reservation.booking_reference}",
            message=f"{instance.get_document_type_display()} (v{instance.version}) uploaded.",
            link=link
        )


@receiver(post_save, sender=HallInspection)
def inspection_notification(sender, instance: HallInspection, created: bool, **kwargs):
    if not created:
        return
    reservation = instance.reservation
    from users.models import UserRole
    staff = User.objects.filter(role__in=[UserRole.VENTURES, UserRole.ADMIN], is_active=True)
    for user in staff:
        if user == instance.inspector:
            continue
        Notification.objects.create(
            user=user,
            title=f"Inspection completed for {reservation.booking_reference}",
            message=f"Result: {instance.get_result_display()}",
        )

