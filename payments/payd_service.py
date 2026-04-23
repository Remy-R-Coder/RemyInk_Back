import os
import requests
from requests.auth import HTTPBasicAuth

class PaydService:
    def __init__(self):
        self.username = os.getenv('PAYD_USERNAME')
        self.password = os.getenv('PAYD_PASSWORD')
        self.base_url = os.getenv('PAYD_API_URL', 'https://api.payd.money/api/v2')

    def initiate_card_checkout(self, amount, job_id, client_email=""):
        """
        Generates a hosted checkout link for UAE card payments.
        """
        url = f"{self.base_url}/checkout/"
        auth = HTTPBasicAuth(self.username, self.password)
        
        payload = {
            "amount": float(amount),
            "currency": "USD", # Or AED if your Payd account supports it
            "narration": f"RemyInk Order: {job_id}",
            "callback_url": "https://remyink-9gqjd.ondigitalocean.app/api/payments/payd-callback/",
            "return_url": "https://remyink.co.ke/payment-success", # Where client goes after paying
            "external_id": str(job_id),
            "email": client_email
        }
        
        response = requests.post(url, json=payload, auth=auth)
        return response.json()