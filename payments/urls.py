from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    InitializePaymentView,
    VerifyPaymentView,
    PaymentStatusView,
    PaystackWebhookView,
    PaymentViewSet,
    PaymentWebhookLogViewSet
)

router = DefaultRouter()
router.register(r'list', PaymentViewSet, basename='payment')
router.register(r'webhooks/logs', PaymentWebhookLogViewSet, basename='webhook-log')

urlpatterns = [
    path('initialize/', InitializePaymentView.as_view(), name='payment-initialize'),
    path('verify/', VerifyPaymentView.as_view(), name='payment-verify'),
    path('status/<uuid:job_id>/', PaymentStatusView.as_view(), name='payment-status'),
    path('webhook/', PaystackWebhookView.as_view(), name='paystack-webhook'),
    path('', include(router.urls)),
] 