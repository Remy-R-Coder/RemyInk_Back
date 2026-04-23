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
import logging
logger = logging.getLogger(__name__)

class PaydInitiateView(APIView):
    permission_classes = [AllowAny]  # <--- ADD THIS LINE HERE
    def post(self, request):
        job_id = request.data.get('job_id')
        
        try:
            job = Job.objects.get(id=job_id)
            payd = PaydService()
            
            # Use the new checkout method for card payments
            response = payd.initiate_card_checkout(
                amount=job.total_amount, 
                job_id=job.id
            )
            
            # Return the URL so the Next.js frontend can redirect the client
            return Response({
                "checkout_url": response.get("checkout_url"),
                "status": "success"
            }, status=status.HTTP_200_OK)
            
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



                    # 2. Handle the Freelancer Payout
                    if job.freelancer:
                        # Calculate the 70% share in USD
                        freelancer_share_usd = job.total_amount * Decimal('0.70')
                        
                        # Access the mpesa_number from the FreelancerProfile
                        # We use getattr safely in case the profile hasn't been created yet
                        profile = getattr(job.freelancer, 'freelancerprofile', None)
                        target_phone = profile.mpesa_number if profile else data.get('phone_number')

                        payout, created = Payout.objects.get_or_create(

                            job=job,
                            freelancer=job.freelancer,
                            defaults={
                                'usd_amount': freelancer_share_usd,
                                'gateway': PaymentGateway.PAYD,
                                'status': PayoutStatus.PENDING,
                                'destination_id': target_phone, # This will now be the M-Pesa number
                                'narration': f"Share for Job #{job.id}"
                            }
                        )
                        if created:
                            logger.info(f"Created payout for Job {job.id} to {target_phone} (USD {freelancer_share_usd})")  
                    

                return Response({"message": "Success"}, status=status.HTTP_200_OK)
            
            except Job.DoesNotExist:
                return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)
        
        return Response({"message": "Payment failed or pending"}, status=status.HTTP_200_OK)