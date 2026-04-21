import requests
import logging
from django.conf import settings
from decimal import Decimal

logger = logging.getLogger(__name__)

class PaydService:
    """Service for interacting with Payd API for Kenyan Payouts (M-Pesa)"""
    
    BASE_URL = "https://api.payd.money/api/v2"

    def __init__(self):
        self.username = getattr(settings, 'PAYD_API_USERNAME', None)
        self.password = getattr(settings, 'PAYD_API_PASSWORD', None)
        self.payd_username = getattr(settings, 'PAYD_WALLET_USERNAME', None)

    def _get_auth(self):
        return (self.username, self.password)

    def initiate_payout(self, payout):
        """
        Sends money to a freelancer via Payd (M-Pesa).
        """
        url = f"{self.BASE_URL}/withdrawals" # Or their specific payout endpoint
        
        payload = {
            "username": self.payd_username,
            "amount": int(payout.payout_amount), # Payd usually takes whole units or decimals depending on version
            "phone_number": payout.destination_id,
            "narration": f"RemyInk Payout {payout.reference}",
            "currency": "KES",
            "callback_url": f"{settings.SITE_URL}/api/payouts/webhook/payd/",
        }

        try:
            response = requests.post(
                url, 
                json=payload, 
                auth=self._get_auth(),
                timeout=30
            )
            data = response.json()

            if response.status_code in [200, 201] and data.get('success'):
                return {
                    'success': True,
                    'transfer_code': data.get('transaction_reference'),
                    'data': data
                }
            
            return {
                'success': False,
                'message': data.get('remarks', 'Payd payout failed'),
                'data': data
            }
        except Exception as e:
            logger.exception(f"Payd Payout Error: {e}")
            return {'success': False, 'message': str(e)}

payd_service = PaydService()