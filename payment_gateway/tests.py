from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from .services import PaystackService


class PaystackServiceCurrencyTests(SimpleTestCase):
    @patch('payment_gateway.services.requests.post')
    def test_initialize_payment_uses_usd_currency(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': True,
            'data': {'authorization_url': 'https://paystack.test/checkout'},
            'message': 'ok',
        }

        service = PaystackService()
        service.initialize_payment(
            email='payer@example.com',
            amount=Decimal('75.00'),
            reference='PAY-USD-1',
            metadata={'job_id': '123'},
        )

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs['json']['currency'], 'USD')

    @patch('payment_gateway.services.requests.post')
    def test_initialize_payment_falls_back_to_kes_on_usd_forbidden(self, mock_post):
        usd_resp = type('Resp', (), {})()
        usd_resp.status_code = 403
        usd_resp.json = lambda: {'status': False, 'message': 'Currency not supported'}

        kes_resp = type('Resp', (), {})()
        kes_resp.status_code = 200
        kes_resp.json = lambda: {
            'status': True,
            'data': {'authorization_url': 'https://paystack.test/kes'},
            'message': 'ok',
        }

        mock_post.side_effect = [usd_resp, kes_resp]

        service = PaystackService()
        result = service.initialize_payment(
            email='payer@example.com',
            amount=Decimal('75.00'),
            reference='PAY-FALLBACK-1',
            metadata={'job_id': '123'},
        )

        self.assertTrue(result.get('success'))
        first_currency = mock_post.call_args_list[0].kwargs['json']['currency']
        second_currency = mock_post.call_args_list[1].kwargs['json']['currency']
        self.assertEqual(first_currency, 'USD')
        self.assertEqual(second_currency, 'KES')
