from django.shortcuts import render

# Create your views here.
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .payd_service import PaydService
from orders.models import Job, JobStatus # Correct imports based on your model file

class PaydInitiateView(APIView):
    def post(self, request):
        phone_number = request.data.get('phone_number')
        job_id = request.data.get('job_id')
        
        try:
            job = Job.objects.get(id=job_id)
            payd = PaydService()
            # Use total_amount from your model
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
    permission_classes = [] 

    def post(self, request):
        data = request.data
        # Payd typically sends success/result_code
        if data.get('status') == 'success' or data.get('result_code') == 0:
            job_id = data.get('external_id')
            try:
                job = Job.objects.get(id=job_id)
                # Update status to PAID using your JobStatus enum
                job.status = JobStatus.PAID 
                job.save()
                return Response({"message": "Job marked as PAID"}, status=status.HTTP_200_OK)
            except Job.DoesNotExist:
                return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)
        
        return Response({"message": "Payment not successful"}, status=status.HTTP_200_OK)