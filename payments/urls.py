from django.urls import path
from .views import PaydInitiateView, PaydWebhookView

urlpatterns = [
    path('payd/initiate/', PaydInitiateView.as_view(), name='payd-initiate'),
    path('payd-callback/', PaydWebhookView.as_view(), name='payd-callback'),
]