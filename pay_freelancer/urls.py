from django.urls import path
from .views import TransferInitiationView, PaystackTransferWebhookView

urlpatterns = [
    path('paystack/transfer/initiate/', TransferInitiationView.as_view(), name='paystack_transfer_initiate'),
    path('paystack/transfer/webhook/', PaystackTransferWebhookView.as_view(), name='paystack_transfer_webhook'),
]