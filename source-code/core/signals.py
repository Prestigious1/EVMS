from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import EmailMessage

from core.models import ContactMessage
from core.services import email_user
from users.models import User


@receiver(post_save, sender=ContactMessage)
def contact_reply_email(sender, instance: ContactMessage, created: bool, **kwargs):
    """
    When a user submits a contact message, email admin and ventures.
    When admin adds a reply in admin panel, email the contact address.
    """
    if created:
        # Forward new message to Admin and Ventures with Reply-To set to the sender
        subject = f"New Contact Message: {instance.subject}"
        body = f"From: {instance.name} ({instance.email})\n\nMessage:\n{instance.message}"
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email="no-reply@evms.lasu.edu.ng",
            to=["admin@lasu.edu.ng", "ventures@lasu.edu.ng"],
            reply_to=[instance.email]
        )
        email.send(fail_silently=True)
        return

    if not instance.admin_reply:
        return

    # Best-effort email to external contact address if admin uses Django admin to reply
    user = User(email=instance.email)
    email_user(
        user=user,
        subject=f"Re: {instance.subject}",
        message=instance.admin_reply,
    )

