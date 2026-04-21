import os
import requests
from requests.auth import HTTPBasicAuth

class PaydService:
    def __init__(self):
        self.username = os.getenv('PAYD_USERNAME')
        self.password = os.getenv('PAYD_PASSWORD')
        self.base_url = os.getenv('PAYD_API_URL', 'https://api.payd.money/api/v2')

    def initiate_payment(self, amount, phone, job_id):
        url = f"{self.base_url}/payments"
        auth = HTTPBasicAuth(self.username, self.password)
        
        payload = {
            "amount": float(amount), # Ensure it's a float for JSON
            "phone_number": phone,
            "narration": f"RemyInk Job payment: {job_id}",
            "callback_url": "https://remyink-9gqjd.ondigitalocean.app/api/payments/payd-callback/",
            "external_id": str(job_id) # Send the Job UUID as a string
        }
        
        response = requests.post(url, json=payload, auth=auth)
        return response.json()