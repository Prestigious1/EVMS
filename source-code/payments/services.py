import logging
from decimal import Decimal
from django.db import transaction
from core.services import create_audit_log, notify_and_email
from payments.models import Payment, PaymentStatus, PaymentMethod, PaymentProvider, PaymentProof, PaymentProofType, PaymentProofStatus
from reservations.models import Reservation
from reservations.services import WorkflowService

logger = logging.getLogger(__name__)

class PaymentResolutionService:
    """
    Consolidated Enterprise Payment Resolution Service.
    Every successful payment (Online, Manual, Internal) must invoke finalize_payment.
    """
    @classmethod
    def finalize_payment(
        cls, 
        *, 
        reservation: Reservation, 
        amount: Decimal, 
        method: str, 
        transaction_reference: str, 
        actor, 
        provider: str = PaymentProvider.PAYSTACK,
        proof_file=None,
        payment_type: str = PaymentProofType.BOOKING,
        metadata: dict = None
    ):
        with transaction.atomic():
            # 1. Check if payment already exists to prevent duplicates (especially for callbacks)
            payment = Payment.objects.filter(
                reservation=reservation,
                transaction_reference=transaction_reference,
                status=PaymentStatus.PAID
            ).first()

            if not payment:
                payment = Payment.objects.create(
                    user=actor or reservation.user,
                    reservation=reservation,
                    amount=amount,
                    status=PaymentStatus.PAID,
                    payment_method=method,
                    provider=provider,
                    transaction_reference=transaction_reference,
                    metadata=metadata or {}
                )
            
            # 2. Create the unified PaymentProof for Bursary queue
            proof = PaymentProof.objects.filter(
                reservation=reservation,
                transaction_ref=transaction_reference
            ).first()

            if not proof:
                proof = PaymentProof.objects.create(
                    reservation=reservation,
                    uploaded_by=actor or reservation.user,
                    transaction_ref=transaction_reference,
                    amount_claimed=amount,
                    payment_type=payment_type,
                    status=PaymentProofStatus.PENDING,
                    receipt_file=proof_file if proof_file else None,
                )

            # 3. Trigger standard Workflow state machine (Timeline, Audit, Notifications, Status)
            # This ensures EVERY payment goes to Bursary queue. No bypassing.
            from reservations.models import BookingCaseStatus
            if payment_type == PaymentProofType.BOOKING:
                if reservation.case_status in [BookingCaseStatus.AWAITING_PAYMENT, BookingCaseStatus.PAYMENT_REJECTED]:
                    WorkflowService.submit_payment_proof(
                        reservation=reservation,
                        actor=actor,
                        notes=f"System: Payment submitted via {method} (Ref: {transaction_reference}). Awaiting Bursary verification.",
                    )
            else:
                if reservation.case_status == BookingCaseStatus.AWAITING_DAMAGE_PAYMENT:
                    WorkflowService.submit_damage_payment_proof(
                        reservation=reservation,
                        actor=actor,
                        notes=f"System: Damage payment submitted via {method} (Ref: {transaction_reference}). Awaiting Bursary verification.",
                    )

            # Audit log
            create_audit_log(
                user=actor or reservation.user,
                action=f"Payment finalized: {transaction_reference} via {method}",
                model_name="Payment"
            )

        return payment
