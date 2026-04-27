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
        
        # FORCE cast to float then int to handle Decimal or String inputs safely
        try:
            clean_amount = int(float(amount) * 100)
        except (TypeError, ValueError):
            logger.error(f"Invalid amount provided: {amount}")
            return None

        data = {
            "email": email,
            "amount": clean_amount, 
            "currency": currency,
            "reference": reference,
            # Ensure metadata values are strings to avoid serialization errors
            "metadata": metadata if metadata is not None else {}
        }
        
        try:
            # Set a timeout so the server doesn't hang indefinitely
            response = requests.post(url, headers=self.headers, json=data, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # If Paystack returns an error (like a 400), this will log the body
            if e.response is not None:
                logger.error(f"Paystack rejected request: {e.response.json()}")
            else:
                logger.error(f"Paystack Init Error for ref {reference}: {e}")
            return None
