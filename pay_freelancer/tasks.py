from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone
import logging
from decimal import Decimal

from .api_utils import initiate_transfer
from .models import Payout, PayoutStatus, PayoutLog
from orders.models import Job, JobStatus, Dispute

logger = logging.getLogger(__name__)

@shared_task(bind=True, default_retry_delay=300, max_retries=5)
def initiate_paystack_transfer_task(self, payout_id):
    try:
        payout = Payout.objects.get(id=payout_id)
    except Payout.DoesNotExist:
        logger.error(f"Payout with ID {payout_id} not found for Paystack transfer task.")
        return

    if payout.status != PayoutStatus.PENDING:
        logger.info(f"Payout {payout_id} is not in PENDING status. Skipping initiation.")
        return

    try:
        api_response = initiate_transfer(
            recipient_code=payout.recipient_code,
            amount_ngn=float(payout.payout_amount),
        )
        
        PayoutLog.objects.create(
            payout=payout,
            status_update=f"Paystack API Request: {api_response.get('message')}",
            response_data=api_response,
        )

        if api_response.get('status') is True:
            transfer_data = api_response.get('data', {})
            payout.transfer_code = transfer_data.get('transfer_code')
            payout.status = PayoutStatus.INITIATED
            payout.response_data = api_response
            payout.save(update_fields=['transfer_code', 'status', 'response_data', 'updated_at'])
            logger.info(f"Paystack Transfer {payout_id} initiated successfully. Transfer Code: {payout.transfer_code}")
        else:
            payout.status = PayoutStatus.FAILED
            payout.error_message = api_response.get('message', 'Unknown Paystack API Error')
            payout.response_data = api_response
            payout.save(update_fields=['status', 'error_message', 'response_data', 'updated_at'])
            logger.error(f"Paystack Transfer {payout_id} initiation failed: {payout.error_message}")
            
    except Exception as e:
        logger.exception(f"Error in initiate_paystack_transfer_task for payout {payout_id}: {e}")
        payout.status = PayoutStatus.FAILED
        payout.error_message = f"Task error: {e}"
        payout.save(update_fields=['status', 'error_message', 'updated_at'])
        if not isinstance(e, SystemExit):
            raise self.retry(exc=e)


@shared_task
def check_and_process_auto_payouts():
    logger.info("Running check_and_process_auto_payouts task.")

    seven_days_ago = timezone.now() - timezone.timedelta(days=7)

    eligible_jobs = Job.objects.filter(
        status=JobStatus.CLIENT_COMPLETED,
        client_marked_complete_at__lte=seven_days_ago,
    ).exclude(
        dispute__status__in=[Dispute.DISPUTE_STATUS_CHOICES[0][0], Dispute.DISPUTE_STATUS_CHOICES[1][0]]
    ).exclude(
        payouts__status__in=[PayoutStatus.SUCCESS, PayoutStatus.INITIATED, PayoutStatus.PENDING]
    ).select_related('freelancer')

    if not eligible_jobs.exists():
        logger.info("No jobs currently eligible for auto payout.")
        return

    logger.info(f"Found {eligible_jobs.count()} jobs eligible for auto payout.")

    for job in eligible_jobs:
        try:
            with transaction.atomic():
                profile = getattr(job.freelancer, 'freelancerprofile', None) if job.freelancer else None
                freelancer_recipient = getattr(profile, 'mpesa_number', None)
                if not job.freelancer or not freelancer_recipient:
                    logger.warning(f"Freelancer for job {job.id} has no valid Paystack recipient code. Skipping payout.")
                    continue

                payout_amount = job.total_amount * Decimal(str(settings.FREELANCER_PAYOUT_PERCENTAGE))

                payout = Payout.objects.create(
                    job=job,
                    freelancer=job.freelancer,
                    recipient_code=freelancer_recipient,
                    payout_amount=payout_amount,
                    status=PayoutStatus.PENDING,
                )
                
                PayoutLog.objects.create(
                    payout=payout,
                    status_update="Payout record created for Paystack auto-payout",
                    response_data={"message": "System initiated auto-payout based on job completion period."}
                )

                initiate_paystack_transfer_task.delay(str(payout.id))

                logger.info(f"Initiated auto Paystack transfer for Job {job.id}.")
        except Exception as e:
            logger.exception(f"Failed to process auto payout for Job {job.id}: {e}")

    logger.info("check_and_process_auto_payouts task completed.")
