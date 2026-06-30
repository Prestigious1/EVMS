from django.db.models.signals import post_save
from django.dispatch import receiver

from core.services import create_audit_log, notify_user
from reservations.models import DamageReport, Penalty, Reservation
from users.models import User


def _sync_user_block_status(user: User):
    unpaid = (
        DamageReport.objects.filter(user=user, is_paid=False, is_forgiven=False).exists()
        or Penalty.objects.filter(user=user, is_paid=False, is_forgiven=False).exists()
    )
    if user.is_blocked != unpaid:
        user.is_blocked = unpaid
        user.save(update_fields=["is_blocked"])


@receiver(post_save, sender=DamageReport)
def damage_report_sync_block(sender, instance: DamageReport, created: bool, **kwargs):
    _sync_user_block_status(instance.user)
    if created:
        # Notify the affected user
        notify_user(
            user=instance.user,
            title="Damage Report Issued",
            message=(
                f"A damage report of ₦{instance.amount or instance.cost_estimate} has been recorded "
                f"against your account. You will be restricted from submitting new bookings until this "
                f"is resolved."
            ),
        )
        create_audit_log(
            user=instance.user,
            action=f"Damage report created: ₦{instance.amount}",
            model_name="DamageReport",
        )

        # If there is a linked reservation, advance it to AWAITING_DAMAGE_PAYMENT if not already there
        if instance.reservation:
            from reservations.models import BookingCaseStatus
            res = instance.reservation
            if res.case_status not in (
                BookingCaseStatus.AWAITING_DAMAGE_PAYMENT,
                BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED,
                BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION,
                BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED,
                BookingCaseStatus.CASE_CLOSED,
            ):
                pass  # WorkflowService.inspection_damage_found handles the transition


@receiver(post_save, sender=Penalty)
def penalty_sync_block(sender, instance: Penalty, created: bool, **kwargs):
    _sync_user_block_status(instance.user)
    if created:
        notify_user(
            user=instance.user,
            title="Penalty Recorded",
            message=(
                f"A penalty of ₦{instance.amount} ({instance.title}) has been recorded on your account. "
                f"You may be restricted from submitting new bookings until it is cleared."
            ),
        )
        create_audit_log(
            user=instance.user,
            action=f"Penalty created: ₦{instance.amount}",
            model_name="Penalty",
        )


@receiver(post_save, sender=Reservation)
def reservation_created(sender, instance: Reservation, created: bool, **kwargs):
    """
    Fires only on creation — sends confirmation notification and creates the communication thread.

    NOTE: Status-change notifications are handled exclusively by
    WorkflowService._notify_status_change() to prevent duplicates.
    Do NOT add an `else` branch here.
    """
    if created:
        notify_user(
            user=instance.user,
            title="Booking Case Created",
            message=(
                f"Your booking case {instance.booking_reference} has been created for "
                f"{instance.hall.name} on {instance.booking_date} "
                f"({instance.start_time}–{instance.end_time}). "
                f"You will be notified as it progresses through each review stage."
            ),
        )
        create_audit_log(
            user=instance.user,
            action="Reservation created",
            model_name="Reservation",
            object_repr=str(instance),
        )
        # Ensure communication thread exists
        from reservations.models import CommunicationThread
        CommunicationThread.objects.get_or_create(reservation=instance)
