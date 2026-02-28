from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import JobViewSet, InitializePaystackView, PaystackWebhookView

router = DefaultRouter()
router.register(r'jobs', JobViewSet, basename='job')

urlpatterns = [
    path('', include(router.urls)),
    
    path('payments/paystack/initialize/', InitializePaystackView.as_view(), name='initialize_paystack'),
    
    path('webhooks/paystack/', PaystackWebhookView.as_view(), name='paystack_webhook'),
]