"""
Paystack Payment Integration Service
Handles payment initialization, verification, and webhooks
"""
import requests
import hmac
import hashlib
import logging
import uuid
from django.conf import settings
from decimal import Decimal

logger = logging.getLogger(__name__)


class PaystackService:
    """Service for interacting with Paystack API"""

    BASE_URL = "https://api.paystack.co"

    def __init__(self):
        self.secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', None)
        self.public_key = getattr(settings, 'PAYSTACK_PUBLIC_KEY', None)

        if not self.secret_key:
            logger.warning("PAYSTACK_SECRET_KEY not configured in settings")

    def _get_headers(self):
        """Get authorization headers for Paystack API"""
        return {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
        }

    def generate_reference(self):
        """Generate a unique payment reference."""
        return f"PAY-{uuid.uuid4().hex[:16].upper()}"

    def initialize_payment(self, email, amount, reference, callback_url=None, metadata=None):
        """
        Initialize a payment transaction with Paystack

        Args:
            email: Customer email
            amount: Amount in kobo (multiply by 100 from naira/shillings)
            reference: Unique payment reference
            callback_url: URL to redirect after payment
            metadata: Additional metadata for the transaction

        Returns:
            dict: Response from Paystack API
        """
        url = f"{self.BASE_URL}/transaction/initialize"

        # Convert amount to kobo (Paystack expects amount in lowest currency unit)
        amount_in_kobo = int(Decimal(amount) * 100)

        def _attempt(currency):
            payload = {
                'email': email,
                'amount': amount_in_kobo,
                'reference': reference,
                'currency': currency,
            }
            if callback_url:
                payload['callback_url'] = callback_url
            if metadata:
                payload['metadata'] = metadata

            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=self._get_headers(),
                    timeout=30
                )
                response_data = response.json()
            except requests.exceptions.RequestException as e:
                logger.exception(f"Paystack API request failed ({currency}): {e}")
                return None, {
                    'success': False,
                    'message': f'Network error: {str(e)}',
                    'data': {}
                }

            if response.status_code == 200 and response_data.get('status'):
                logger.info(f"Payment initialized successfully: {reference} ({currency})")
                data = response_data.get('data', {})
                data['_currency_used'] = currency
                return response, {
                    'success': True,
                    'data': data,
                    'message': response_data.get('message', 'Payment initialized')
                }

            logger.error(f"Payment initialization failed ({currency}): {response_data}")
            return response, {
                'success': False,
                'message': response_data.get('message', 'Payment initialization failed'),
                'data': response_data
            }

        def _should_fallback(resp, result):
            message = str(result.get('message', '')).lower()
            return (
                (resp is not None and resp.status_code == 403)
                or 'currency' in message
                or 'unsupported' in message
            )

        resp, result = _attempt('USD')
        if result.get('success'):
            return result

        if _should_fallback(resp, result):
            logger.warning(f"USD payment init failed for {reference}; retrying with KES.")
            _, retry_result = _attempt('KES')
            return retry_result

        return result

    def verify_payment(self, reference):
        """
        Verify a payment transaction

        Args:
            reference: Payment reference to verify

        Returns:
            dict: Verification response
        """
        url = f"{self.BASE_URL}/transaction/verify/{reference}"

        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=30
            )

            response_data = response.json()

            if response.status_code == 200 and response_data.get('status'):
                data = response_data.get('data', {})

                # Check if payment was successful
                if data.get('status') == 'success':
                    logger.info(f"Payment verified successfully: {reference}")
                    return {
                        'success': True,
                        'data': data,
                        'message': 'Payment verified successfully'
                    }
                else:
                    logger.warning(f"Payment verification failed - status: {data.get('status')}")
                    return {
                        'success': False,
                        'message': f"Payment status: {data.get('status')}",
                        'data': data
                    }
            else:
                logger.error(f"Payment verification API error: {response_data}")
                return {
                    'success': False,
                    'message': response_data.get('message', 'Verification failed'),
                    'data': response_data
                }

        except requests.exceptions.RequestException as e:
            logger.exception(f"Paystack verification request failed: {e}")
            return {
                'success': False,
                'message': f'Network error: {str(e)}',
                'data': {}
            }

    def verify_webhook_signature(self, payload, signature):
        """
        Verify that a webhook request came from Paystack

        Args:
            payload: Raw request body as bytes
            signature: X-Paystack-Signature header value

        Returns:
            bool: True if signature is valid
        """
        if not self.secret_key:
            logger.error("Cannot verify webhook - PAYSTACK_SECRET_KEY not configured")
            return False

        try:
            # Compute HMAC signature
            computed_signature = hmac.new(
                self.secret_key.encode('utf-8'),
                payload,
                hashlib.sha512
            ).hexdigest()

            # Compare signatures
            is_valid = hmac.compare_digest(computed_signature, signature)

            if not is_valid:
                logger.warning("Webhook signature verification failed")

            return is_valid

        except Exception as e:
            logger.exception(f"Error verifying webhook signature: {e}")
            return False

    def get_transaction(self, transaction_id):
        """
        Fetch transaction details

        Args:
            transaction_id: Transaction ID or reference

        Returns:
            dict: Transaction data
        """
        url = f"{self.BASE_URL}/transaction/{transaction_id}"

        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=30
            )

            response_data = response.json()

            if response.status_code == 200 and response_data.get('status'):
                return {
                    'success': True,
                    'data': response_data.get('data', {}),
                    'message': 'Transaction fetched successfully'
                }
            else:
                return {
                    'success': False,
                    'message': response_data.get('message', 'Failed to fetch transaction'),
                    'data': response_data
                }

        except requests.exceptions.RequestException as e:
            logger.exception(f"Failed to fetch transaction: {e}")
            return {
                'success': False,
                'message': f'Network error: {str(e)}',
                'data': {}
            }


# Singleton instance
paystack_service = PaystackService()