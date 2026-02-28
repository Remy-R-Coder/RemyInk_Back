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

    def initialize_transaction(self, email, amount, reference, metadata=None):
        url = settings.PAYSTACK_INITIALIZE_URL

        def _attempt(currency):
            payload = {
                "email": email,
                "amount": int(amount * 100),
                "reference": reference,
                "currency": currency,
                "metadata": metadata if metadata is not None else {}
            }
            try:
                response = requests.post(url, headers=self.headers, json=payload)
                data = response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"Paystack Init Error for ref {reference} ({currency}): {e}")
                return None, {"status": False, "message": str(e), "data": {}}

            if response.status_code >= 400 or not data.get("status"):
                message = data.get("message", f"HTTP {response.status_code}")
                return response, {"status": False, "message": message, "data": data.get("data", {})}

            data["_currency_used"] = currency
            return response, data

        def _should_fallback(resp, result):
            message = str(result.get("message", "")).lower()
            return (
                (resp is not None and resp.status_code == 403)
                or "currency" in message
                or "unsupported" in message
            )

        resp, result = _attempt("USD")
        if result.get("status"):
            return result

        if _should_fallback(resp, result):
            logger.warning(f"USD Paystack init failed for {reference}; retrying with KES.")
            _, retry_result = _attempt("KES")
            if retry_result.get("status"):
                return retry_result
            return retry_result

        return result

    def verify_transaction(self, reference):
        url = f"{settings.PAYSTACK_VERIFY_URL}{reference}"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack Verify Error for ref {reference}: {e}")
            return None
