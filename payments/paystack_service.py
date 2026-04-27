import requests
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class PaystackService:
    def __init__(self):
        self.headers = {
            'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
            'Content-Type': 'application/json',
        }

    def initialize_transaction(self, email, amount, reference, currency="USD", metadata=None):
        url = settings.PAYSTACK_INITIALIZE_URL
        
        data = {
            "email": email,
            "amount": int(amount * 100), 
            "currency": currency,  # <--- THIS IS THE LINE YOU ARE MISSING
            "reference": reference,
            "metadata": metadata if metadata is not None else {}
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack Init Error for ref {reference}: {e}")
            return None

    def verify_transaction(self, reference):
        url = f"{settings.PAYSTACK_VERIFY_URL}{reference}"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack Verify Error for ref {reference}: {e}")
            return None