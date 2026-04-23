from decimal import Decimal
from django.db import transaction # Added this
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny

from orders.models import Job, JobStatus 
from pay_freelancer.models import Payout, PayoutStatus, PaymentGateway
from .payd_service import PaydService

class PaydInitiateView(APIView):
    def post(self, request):
        phone_number = request.data.get('phone_number')
        job_id = request.data.get('job_id')
        
        try:
            job = Job.objects.get(id=job_id)
            payd = PaydService()
            response = payd.initiate_payment(
                amount=job.total_amount, 
                phone=phone_number, 
                job_id=job.id
            )
            return Response(response, status=status.HTTP_200_OK)
        except Job.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

@method_decorator(csrf_exempt, name='dispatch')
class PaydWebhookView(APIView):
    # It's safer to explicitly set AllowAny for webhooks
    permission_classes = [AllowAny] 

    def post(self, request):
        data = request.data
        
        # Check Payd success codes
        if data.get('status') == 'success' or str(data.get('result_code')) == '0':
            job_id = data.get('external_id')
            try:
                with transaction.atomic():
                    # select_for_update prevents two webhooks from processing at once
                    job = Job.objects.select_for_update().get(id=job_id)
                    
                    if job.status == JobStatus.PAID:
                        return Response({"message": "Already processed"}, status=status.HTTP_200_OK)

                    # 1. Update Job Status
                    job.status = JobStatus.PAID 
                    job.save()

                    # 2. Create the Payout record for the freelancer
                    if job.freelancer:
                        # 70% share logic
                        freelancer_share_usd = job.total_amount * Decimal('0.70')
                        
                        Payout.objects.get_or_create(
                            job=job,
                            freelancer=job.freelancer,
                            defaults={
                                'usd_amount': freelancer_share_usd,
                                'gateway': PaymentGateway.PAYD,
                                'status': PayoutStatus.PENDING,
                                'destination_id': data.get('phone_number'), 
                                'narration': f"70% Share: Job #{job.id}"
                            }
                        )
                
                return Response({"message": "Success"}, status=status.HTTP_200_OK)
            
            except Job.DoesNotExist:
                return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)
        
        return Response({"message": "Payment failed or pending"}, status=status.HTTP_200_OK)