from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from django.conf import settings
from django.db import transaction
import json
import logging
import hmac
import hashlib
from .models import Payout, PayoutStatus, PayoutLog
from .tasks import initiate_paystack_transfer_task
from orders.models import Job, JobStatus

logger = logging.getLogger(__name__)


class EmptySerializer(serializers.Serializer):
    pass

class TransferInitiationView(APIView):
    """
    View to manually initiate a Paystack transfer for a specific job/payout ID.
    """
    permission_classes = [IsAuthenticated] 
    serializer_class = EmptySerializer
    def post(self, request):
        payout_id = request.data.get('payout_id')

        if not payout_id:
            return Response({'error': 'Payout ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payout = Payout.objects.get(id=payout_id)
        except Payout.DoesNotExist:
            return Response({'error': 'Payout not found.'}, status=status.HTTP_404_NOT_FOUND)

        if payout.status != PayoutStatus.PENDING:
            return Response({'error': f'Payout is already {payout.status}. Only PENDING payouts can be initiated.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            initiate_paystack_transfer_task.delay(str(payout.id))
            
            logger.info(f"Paystack transfer initiation request received for Payout ID: {payout.id}. Task dispatched.")
            return Response(
                {'message': 'Paystack transfer initiation dispatched.',
                 'payout_id': str(payout.id)},
                status=status.HTTP_202_ACCEPTED
            )
        except Exception as e:
            logger.error(f"Error dispatching Paystack transfer task: {e}", exc_info=True)
            return Response({'error': 'Failed to dispatch transfer initiation task.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PaystackTransferWebhookView(APIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = EmptySerializer

    def post(self, request):
        signature = request.headers.get('x-paystack-signature')
        if not signature:
            logger.warning("Paystack Webhook received without signature.")
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if not settings.PAYSTACK_WEBHOOK_SECRET:
            logger.error("PAYSTACK_WEBHOOK_SECRET is not configured.")
            return Response(status=status.HTTP_200_OK)

        body = request.body.decode('utf-8')
        digest = hmac.new(
            settings.PAYSTACK_WEBHOOK_SECRET.encode('utf-8'), 
            body.encode('utf-8'), 
            hashlib.sha512
        ).hexdigest()

        if signature != digest:
            logger.error("Paystack Webhook signature verification failed.")
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            event_data = json.loads(body)
            event_type = event_data.get('event')
            transfer_data = event_data.get('data', {})

            if event_type == 'transfer.success' or event_type == 'transfer.failed' or event_type == 'transfer.reversed':
                transfer_code = transfer_data.get('transfer_code')
                
                if not transfer_code:
                    logger.error(f"Paystack Webhook missing transfer_code in event: {event_type}")
                    return Response(status=status.HTTP_400_BAD_REQUEST)

                try:
                    payout = Payout.objects.get(transfer_code=transfer_code)
                except Payout.DoesNotExist:
                    logger.warning(f"Paystack Webhook received for unknown Transfer Code: {transfer_code}. Skipping processing.")
                    return Response(status=status.HTTP_200_OK)

                with transaction.atomic():
                    new_status = PayoutStatus.INITIATED 
                    
                    if event_type == 'transfer.success':
                        new_status = PayoutStatus.SUCCESS
                    elif event_type == 'transfer.failed':
                        new_status = PayoutStatus.FAILED
                        payout.error_message = transfer_data.get('status', 'Transfer failed via webhook')
                    elif event_type == 'transfer.reversed':
                        new_status = PayoutStatus.REVERSED
                        payout.error_message = transfer_data.get('status', 'Transfer reversed via webhook')

                    payout.status = new_status
                    payout.response_data = event_data 
                    payout.save()
                    
                    PayoutLog.objects.create(
                        payout=payout,
                        status_update=f"Paystack Webhook: {event_type}",
                        response_data=event_data,
                    )
                    
                    if new_status == PayoutStatus.SUCCESS:
                        job = payout.job
                        if job:
                            # Job lifecycle does not include a dedicated payout status.
                            logger.info(f"Paystack Transfer success for Payout {payout.id}. Job {job.id} payout marked successful.")


            return Response(status=status.HTTP_200_OK)

        except json.JSONDecodeError:
            logger.error("Paystack Webhook received invalid JSON payload.")
            return Response(status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error in Paystack Webhook: {e}", exc_info=True)
            return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)
