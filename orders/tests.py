from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.test import TestCase, SimpleTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from chat.models import ChatThread, ChatMessage
from chat.signals import broadcast_new_message
from user_module.models import Role, GuestSession, Rating
from .models import Job, JobStatus, Dispute
from .paystack_service import PaystackService

User = get_user_model()


class InitializePaystackGuestSessionTests(TestCase):
    def setUp(self):
        post_save.disconnect(broadcast_new_message, sender=ChatMessage)
        self.addCleanup(lambda: post_save.connect(broadcast_new_message, sender=ChatMessage))

        self.client_api = APIClient()

        self.freelancer = User.objects.create_user(
            username='freelancer_init',
            email='freelancer_init@test.com',
            password='testpass123',
            role=Role.FREELANCER,
            is_active=True,
        )
        self.client_user = User.objects.create_user(
            username='client_init',
            email='client_init@test.com',
            password='testpass123',
            role=Role.CLIENT,
            is_active=True,
        )

        self.thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            client=self.client_user,
            guest_session_key='guest_payment_session_key',
        )
        GuestSession.objects.create(
            session_key='guest_payment_session_key',
            shadow_client=self.client_user,
        )
        self.job = Job.objects.create(
            title='Guest Payment Job',
            description='Job from accepted offer',
            client=self.client_user,
            freelancer=self.freelancer,
            price=Decimal('500.00'),
            total_amount=Decimal('500.00'),
            delivery_time_days=5,
            status=JobStatus.PROVISIONAL,
        )
        self.offer = ChatMessage.objects.create(
            thread=self.thread,
            sender=self.freelancer,
            is_offer=True,
            offer_title='Offer Title',
            offer_price=Decimal('500.00'),
            offer_timeline=5,
            offer_status='accepted',
            created_job=self.job,
        )

    @patch('orders.views.PaystackService.initialize_transaction')
    def test_guest_can_initialize_payment_with_session_key(self, mock_initialize):
        mock_initialize.return_value = {
            'status': True,
            'data': {'authorization_url': 'https://paystack.test/checkout'},
            'message': 'ok',
        }

        response = self.client_api.post(
            '/api/orders/payments/paystack/initialize/?session_key=guest_payment_session_key',
            {'job_id': str(self.job.id)},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn('authorizationUrl', response.data)

    @patch('orders.views.PaystackService.initialize_transaction')
    def test_shadow_client_initialize_requires_client_email(self, mock_initialize):
        self.client_user.email = 'client.shadow123@test.shadow'
        self.client_user.is_active = False
        self.client_user.save(update_fields=['email', 'is_active'])

        response = self.client_api.post(
            '/api/orders/payments/paystack/initialize/?session_key=guest_payment_session_key',
            {'job_id': str(self.job.id)},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('client_email', response.data.get('error', ''))

        mock_initialize.return_value = {
            'status': True,
            'data': {'authorization_url': 'https://paystack.test/checkout'},
            'message': 'ok',
        }
        response = self.client_api.post(
            '/api/orders/payments/paystack/initialize/?session_key=guest_payment_session_key',
            {
                'job_id': str(self.job.id),
                'client_email': 'guestclient@example.com',
                'client_password': 'GuestStrongPass123!',
                'client_password_confirm': 'GuestStrongPass123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(mock_initialize.call_args.kwargs['email'], 'guestclient@example.com')
        self.client_user.refresh_from_db()
        self.assertTrue(self.client_user.check_password('GuestStrongPass123!'))

    def test_guest_initialize_requires_session_key_if_not_authenticated(self):
        response = self.client_api.post(
            '/api/orders/payments/paystack/initialize/',
            {'job_id': str(self.job.id)},
            format='json',
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn('error', response.data)

    @patch('orders.views.PaystackService.initialize_transaction')
    def test_authenticated_user_can_retry_after_payment_failed(self, mock_initialize):
        mock_initialize.return_value = {
            'status': True,
            'data': {'authorization_url': 'https://paystack.test/retry'},
            'message': 'ok',
        }
        self.client_api.force_authenticate(user=self.client_user)

        self.job.status = JobStatus.PAYMENT_FAILED
        self.job.paystack_reference = 'OLD-FAILED-REF'
        self.job.save(update_fields=['status', 'paystack_reference'])

        response = self.client_api.post(
            '/api/orders/payments/paystack/initialize/',
            {'job_id': str(self.job.id)},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.PENDING_PAYMENT)
        self.assertNotEqual(self.job.paystack_reference, 'OLD-FAILED-REF')

    @patch('orders.views.PaystackService.initialize_transaction')
    def test_guest_can_retry_after_payment_failed_with_session_key(self, mock_initialize):
        mock_initialize.return_value = {
            'status': True,
            'data': {'authorization_url': 'https://paystack.test/retry-guest'},
            'message': 'ok',
        }

        self.job.status = JobStatus.PAYMENT_FAILED
        self.job.paystack_reference = 'OLD-FAILED-REF-GUEST'
        self.job.save(update_fields=['status', 'paystack_reference'])

        response = self.client_api.post(
            '/api/orders/payments/paystack/initialize/?session_key=guest_payment_session_key',
            {'job_id': str(self.job.id)},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.PENDING_PAYMENT)
        self.assertNotEqual(self.job.paystack_reference, 'OLD-FAILED-REF-GUEST')

    @patch('orders.views.PaystackService.initialize_transaction')
    def test_initialize_returns_400_when_gateway_fails(self, mock_initialize):
        mock_initialize.return_value = {
            'status': False,
            'message': '403 Client Error: Forbidden for url: https://api.paystack.co/transaction/initialize',
            'data': {},
        }

        response = self.client_api.post(
            '/api/orders/payments/paystack/initialize/?session_key=guest_payment_session_key',
            {'job_id': str(self.job.id)},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data.get('error'), 'Payment initialization failed.')

    def test_guest_can_retrieve_job_with_matching_session_key(self):
        response = self.client_api.get(
            f'/api/orders/jobs/{self.job.id}/?session_key=guest_payment_session_key',
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.data.get('id')), str(self.job.id))

    def test_guest_job_retrieve_requires_auth_or_session_key(self):
        response = self.client_api.get(f'/api/orders/jobs/{self.job.id}/', format='json')
        self.assertEqual(response.status_code, 401)

    def test_guest_cannot_retrieve_job_from_other_session(self):
        other_client = User.objects.create_user(
            username='other_client',
            email='other_client@test.com',
            password='testpass123',
            role=Role.CLIENT,
            is_active=True,
        )
        other_thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            client=other_client,
            guest_session_key='other_guest_session',
        )
        other_job = Job.objects.create(
            title='Other Guest Job',
            description='Different guest session job',
            client=other_client,
            freelancer=self.freelancer,
            price=Decimal('200.00'),
            total_amount=Decimal('200.00'),
            delivery_time_days=3,
            status=JobStatus.PROVISIONAL,
        )
        ChatMessage.objects.create(
            thread=other_thread,
            sender=self.freelancer,
            is_offer=True,
            offer_title='Other Offer',
            offer_price=Decimal('200.00'),
            offer_timeline=3,
            offer_status='accepted',
            created_job=other_job,
        )

        response = self.client_api.get(
            f'/api/orders/jobs/{other_job.id}/?session_key=guest_payment_session_key',
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    @patch('orders.views.PaystackService.verify_transaction')
    def test_guest_retrieve_refreshes_pending_payment_to_paid(self, mock_verify):
        self.job.status = JobStatus.PENDING_PAYMENT
        self.job.paystack_reference = 'REF-PAID-123'
        self.job.total_amount = Decimal('500.00')
        self.job.save(update_fields=['status', 'paystack_reference', 'total_amount'])

        mock_verify.return_value = {
            'status': True,
            'data': {
                'status': 'success',
                'amount': 50000,
            },
        }

        response = self.client_api.get(
            f'/api/orders/jobs/{self.job.id}/?session_key=guest_payment_session_key',
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.PAID)
        self.assertEqual(response.data.get('status'), JobStatus.PAID)

    @patch('orders.views.PaystackService.verify_transaction')
    def test_guest_retrieve_paid_includes_login_redirect_hint(self, mock_verify):
        self.job.status = JobStatus.PENDING_PAYMENT
        self.job.paystack_reference = 'REF-PAID-LOGIN-1'
        self.job.total_amount = Decimal('500.00')
        self.job.client.is_active = True
        self.job.client.set_password('ClientLoginPass123!')
        self.job.client.save(update_fields=['is_active', 'password'])
        self.job.save(update_fields=['status', 'paystack_reference', 'total_amount'])

        mock_verify.return_value = {
            'status': True,
            'data': {
                'status': 'success',
                'amount': 50000,
            },
        }

        response = self.client_api.get(
            f'/api/orders/jobs/{self.job.id}/?session_key=guest_payment_session_key',
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get('post_payment', {}).get('next'), 'login')

    @patch('orders.views.send_mail')
    @patch('orders.views.PaystackService.verify_transaction')
    def test_guest_retrieve_refresh_finalizes_shadow_client_after_paid(self, mock_verify, mock_send_mail):
        self.client_user.email = 'client.shadow123@test.shadow'
        self.client_user.is_active = False
        self.client_user.save(update_fields=['email', 'is_active'])

        self.job.status = JobStatus.PENDING_PAYMENT
        self.job.paystack_reference = 'REF-PAID-SHADOW-123'
        self.job.total_amount = Decimal('500.00')
        self.job.save(update_fields=['status', 'paystack_reference', 'total_amount'])

        mock_verify.return_value = {
            'status': True,
            'data': {
                'status': 'success',
                'amount': 50000,
                'customer': {'email': 'guestclient@example.com'},
            },
        }

        response = self.client_api.get(
            f'/api/orders/jobs/{self.job.id}/?session_key=guest_payment_session_key',
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.client_user.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.PAID)
        self.assertEqual(self.client_user.email, 'guestclient@example.com')
        self.assertTrue(self.client_user.is_active)
        self.assertTrue(self.client_user.has_usable_password())
        mock_send_mail.assert_called_once()


class JobSubmissionDeliveryTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()

        self.freelancer = User.objects.create_user(
            username='freelancer_submit',
            email='freelancer_submit@test.com',
            password='testpass123',
            role=Role.FREELANCER,
            is_active=True,
        )
        self.client_user = User.objects.create_user(
            username='client_submit',
            email='client_submit@test.com',
            password='testpass123',
            role=Role.CLIENT,
            is_active=True,
        )
        self.job = Job.objects.create(
            title='Submission Job',
            description='Delivery flow job',
            client=self.client_user,
            freelancer=self.freelancer,
            price=Decimal('300.00'),
            total_amount=Decimal('300.00'),
            delivery_time_days=3,
            status=JobStatus.IN_PROGRESS,
        )

    def test_freelancer_can_submit_text_only(self):
        self.client_api.force_authenticate(user=self.freelancer)

        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/submit/',
            {'submission_text': 'Delivered final draft. Please review.'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.DELIVERED)
        self.assertEqual(self.job.submission.submission_text, 'Delivered final draft. Please review.')

    def test_freelancer_can_submit_with_attachments(self):
        self.client_api.force_authenticate(user=self.freelancer)
        file_1 = SimpleUploadedFile('deliverable.txt', b'final deliverable content', content_type='text/plain')
        file_2 = SimpleUploadedFile('notes.txt', b'client notes', content_type='text/plain')

        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/submit/',
            {
                'submission_text': 'Attached files included.',
                'attachments': [file_1, file_2],
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.DELIVERED)
        self.assertEqual(self.job.submission.attachments.count(), 2)
        self.assertEqual(len(response.data.get('submission', {}).get('attachment_files', [])), 2)
        self.assertEqual(len(response.data.get('submission', {}).get('attachments', [])), 2)
        self.assertEqual(len(response.data.get('submission', {}).get('all_attachments', [])), 2)

    def test_freelancer_can_submit_with_attachments_bracket_key(self):
        self.client_api.force_authenticate(user=self.freelancer)
        file_1 = SimpleUploadedFile('deliverable_a.txt', b'a', content_type='text/plain')
        file_2 = SimpleUploadedFile('deliverable_b.txt', b'b', content_type='text/plain')

        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/submit/',
            {
                'submission_text': 'Bracket key upload',
                'attachments[]': [file_1, file_2],
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.submission.attachments.count(), 2)

    def test_all_attachments_includes_legacy_and_deliverable_files(self):
        self.client_api.force_authenticate(user=self.freelancer)
        deliverable = SimpleUploadedFile('deliverable.txt', b'content', content_type='text/plain')
        assignment = SimpleUploadedFile('assignment.pdf', b'%PDF-1.4', content_type='application/pdf')
        ai_report = SimpleUploadedFile('ai_report.pdf', b'%PDF-1.4', content_type='application/pdf')

        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/submit/',
            {
                'submission_text': 'Delivered with legacy + new files',
                'attachments': [deliverable],
                'assignment': assignment,
                'ai_report': ai_report,
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 200)
        all_attachments = response.data.get('submission', {}).get('all_attachments', [])
        self.assertEqual(len(all_attachments), 3)

    def test_client_can_list_submission_attachments(self):
        self.client_api.force_authenticate(user=self.freelancer)
        deliverable = SimpleUploadedFile('deliverable.txt', b'content', content_type='text/plain')
        assignment = SimpleUploadedFile('assignment.pdf', b'%PDF-1.4', content_type='application/pdf')
        self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/submit/',
            {
                'submission_text': 'Delivered with files',
                'attachments': [deliverable],
                'assignment': assignment,
            },
            format='multipart',
        )

        self.client_api.force_authenticate(user=self.client_user)
        response = self.client_api.get(f'/api/orders/jobs/{self.job.id}/submission/attachments/')
        self.assertEqual(response.status_code, 200)
        attachments = response.data.get('attachments', [])
        self.assertGreaterEqual(len(attachments), 2)
        self.assertTrue(all('download_url' in item for item in attachments))

    def test_client_can_download_deliverable_attachment(self):
        self.client_api.force_authenticate(user=self.freelancer)
        deliverable = SimpleUploadedFile('deliverable.txt', b'content', content_type='text/plain')
        self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/submit/',
            {
                'submission_text': 'Delivered with files',
                'attachments': [deliverable],
            },
            format='multipart',
        )
        attachment = self.job.submission.attachments.first()

        self.client_api.force_authenticate(user=self.client_user)
        response = self.client_api.get(
            f'/api/orders/jobs/{self.job.id}/submission/attachments/{attachment.id}/download/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get('Content-Disposition'), 'attachment; filename="deliverable.txt"')

    def test_client_can_download_legacy_attachment(self):
        self.client_api.force_authenticate(user=self.freelancer)
        assignment = SimpleUploadedFile('assignment.pdf', b'%PDF-1.4', content_type='application/pdf')
        self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/submit/',
            {
                'submission_text': 'Delivered with legacy file',
                'assignment': assignment,
            },
            format='multipart',
        )

        self.client_api.force_authenticate(user=self.client_user)
        response = self.client_api.get(
            f'/api/orders/jobs/{self.job.id}/submission/legacy/assignment/download/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get('Content-Disposition'), 'attachment; filename="assignment.pdf"')


class JobStartWorkTransitionTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.freelancer = User.objects.create_user(
            username='freelancer_start',
            email='freelancer_start@test.com',
            password='testpass123',
            role=Role.FREELANCER,
            is_active=True,
        )
        self.client_user = User.objects.create_user(
            username='client_start',
            email='client_start@test.com',
            password='testpass123',
            role=Role.CLIENT,
            is_active=True,
        )
        self.job = Job.objects.create(
            title='Start Transition Job',
            description='Transition into in progress',
            client=self.client_user,
            freelancer=self.freelancer,
            price=Decimal('150.00'),
            total_amount=Decimal('150.00'),
            delivery_time_days=2,
            status=JobStatus.PAID,
        )

    def test_start_work_endpoint_moves_job_to_in_progress(self):
        self.client_api.force_authenticate(user=self.freelancer)
        response = self.client_api.post(f'/api/orders/jobs/{self.job.id}/start-work/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.IN_PROGRESS)

    def test_status_endpoint_allows_in_progress_transition(self):
        self.client_api.force_authenticate(user=self.freelancer)
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/status/',
            {'status': 'IN_PROGRESS'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.IN_PROGRESS)


class JobRatingFlowTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.freelancer = User.objects.create_user(
            username='freelancer_rate',
            email='freelancer_rate@test.com',
            password='testpass123',
            role=Role.FREELANCER,
            is_active=True,
        )
        self.client_user = User.objects.create_user(
            username='client_rate',
            email='client_rate@test.com',
            password='testpass123',
            role=Role.CLIENT,
            is_active=True,
        )
        self.job = Job.objects.create(
            title='Rating Job',
            description='Delivered rating flow',
            client=self.client_user,
            freelancer=self.freelancer,
            price=Decimal('180.00'),
            total_amount=Decimal('180.00'),
            delivery_time_days=2,
            status=JobStatus.DELIVERED,
        )

    def test_client_can_rate_freelancer_after_delivery(self):
        self.client_api.force_authenticate(user=self.client_user)
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/rate-freelancer/',
            {'score': 4.5, 'review': 'Great work.'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.CLIENT_COMPLETED)
        rating = Rating.objects.get(job=self.job, rater=self.client_user)
        self.assertEqual(float(rating.score), 4.5)

    def test_client_can_update_rating_for_same_job(self):
        self.client_api.force_authenticate(user=self.client_user)
        self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/rate-freelancer/',
            {'score': 3.5, 'review': 'Initial'},
            format='json',
        )
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/rate-freelancer/',
            {'score': 5, 'review': 'Updated'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data.get('created'))
        rating = Rating.objects.get(job=self.job, rater=self.client_user)
        self.assertEqual(float(rating.score), 5.0)

    def test_freelancer_cannot_rate_self_on_job(self):
        self.client_api.force_authenticate(user=self.freelancer)
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/rate-freelancer/',
            {'score': 5},
            format='json',
        )
        self.assertEqual(response.status_code, 403)


class JobDisputeFlowTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.freelancer = User.objects.create_user(
            username='freelancer_dispute',
            email='freelancer_dispute@test.com',
            password='testpass123',
            role=Role.FREELANCER,
            is_active=True,
        )
        self.client_user = User.objects.create_user(
            username='client_dispute',
            email='client_dispute@test.com',
            password='testpass123',
            role=Role.CLIENT,
            is_active=True,
        )
        self.admin_user = User.objects.create_user(
            username='admin_dispute',
            email='admin_dispute@test.com',
            password='testpass123',
            role=Role.ADMIN,
            is_staff=True,
            is_active=True,
        )
        self.job = Job.objects.create(
            title='Dispute Job',
            description='Dispute flow',
            client=self.client_user,
            freelancer=self.freelancer,
            price=Decimal('250.00'),
            total_amount=Decimal('250.00'),
            delivery_time_days=2,
            status=JobStatus.DELIVERED,
        )

    def test_client_can_open_dispute(self):
        self.client_api.force_authenticate(user=self.client_user)
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/dispute/',
            {'reason': 'Work did not match requirements.'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.DISPUTE_OPEN)
        dispute = Dispute.objects.get(job=self.job)
        self.assertEqual(dispute.status, 'OPEN')
        self.assertEqual(dispute.reason, 'Work did not match requirements.')

    def test_freelancer_cannot_open_dispute(self):
        self.client_api.force_authenticate(user=self.freelancer)
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/dispute/',
            {'reason': 'Attempt'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_dispute_get_available_to_client_and_freelancer(self):
        Dispute.objects.create(job=self.job, raised_by=self.client_user, reason='Issue', status='OPEN')
        self.job.status = JobStatus.DISPUTE_OPEN
        self.job.save(update_fields=['status'])

        self.client_api.force_authenticate(user=self.client_user)
        client_resp = self.client_api.get(f'/api/orders/jobs/{self.job.id}/dispute/')
        self.assertEqual(client_resp.status_code, 200)
        self.assertEqual(client_resp.data['status'], 'OPEN')

        self.client_api.force_authenticate(user=self.freelancer)
        freelancer_resp = self.client_api.get(f'/api/orders/jobs/{self.job.id}/dispute/')
        self.assertEqual(freelancer_resp.status_code, 200)
        self.assertEqual(freelancer_resp.data['status'], 'OPEN')

    def test_admin_can_move_dispute_to_in_review(self):
        Dispute.objects.create(job=self.job, raised_by=self.client_user, reason='Issue', status='OPEN')
        self.job.status = JobStatus.DISPUTE_OPEN
        self.job.save(update_fields=['status'])

        self.client_api.force_authenticate(user=self.admin_user)
        response = self.client_api.post(f'/api/orders/jobs/{self.job.id}/dispute/in-review/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'IN_REVIEW')

    def test_admin_can_resolve_dispute(self):
        Dispute.objects.create(job=self.job, raised_by=self.client_user, reason='Issue', status='IN_REVIEW')
        self.job.status = JobStatus.DISPUTE_OPEN
        self.job.save(update_fields=['status'])

        self.client_api.force_authenticate(user=self.admin_user)
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/dispute/resolve/',
            {'resolution': 'pay_freelancer', 'admin_resolution_notes': 'Evidence supports delivery quality.'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'RESOLVED_PAID')
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.DISPUTE_RESOLVED)

    def test_non_admin_cannot_resolve_dispute(self):
        Dispute.objects.create(job=self.job, raised_by=self.client_user, reason='Issue', status='OPEN')
        self.job.status = JobStatus.DISPUTE_OPEN
        self.job.save(update_fields=['status'])

        self.client_api.force_authenticate(user=self.client_user)
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/dispute/resolve/',
            {'resolution': 'refund_client'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_client_complete_auto_resolves_open_dispute(self):
        dispute = Dispute.objects.create(job=self.job, raised_by=self.client_user, reason='Issue', status='OPEN')
        self.job.status = JobStatus.DELIVERED
        self.job.save(update_fields=['status'])

        self.client_api.force_authenticate(user=self.client_user)
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/complete/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        dispute.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.CLIENT_COMPLETED)
        self.assertEqual(dispute.status, 'RESOLVED_PAID')
        self.assertIsNotNone(dispute.resolved_at)

    def test_rating_auto_resolves_open_dispute(self):
        dispute = Dispute.objects.create(job=self.job, raised_by=self.client_user, reason='Issue', status='OPEN')
        self.job.status = JobStatus.DELIVERED
        self.job.save(update_fields=['status'])

        self.client_api.force_authenticate(user=self.client_user)
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/rate-freelancer/',
            {'score': 5, 'review': 'Approved after revisions'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        dispute.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.CLIENT_COMPLETED)
        self.assertEqual(dispute.status, 'RESOLVED_PAID')
        self.assertIsNotNone(dispute.resolved_at)

    def test_freelancer_can_resubmit_while_dispute_open_within_limit(self):
        self.job.allowed_reviews = 2
        self.job.reviews_used = 0
        self.job.status = JobStatus.DISPUTE_OPEN
        self.job.save(update_fields=['allowed_reviews', 'reviews_used', 'status'])
        Dispute.objects.create(job=self.job, raised_by=self.client_user, reason='Issue', status='OPEN')

        self.client_api.force_authenticate(user=self.freelancer)
        deliverable = SimpleUploadedFile('revision_v2.txt', b'updated work', content_type='text/plain')
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/submit/',
            {'submission_text': 'Updated delivery per feedback.', 'attachments': [deliverable]},
            format='multipart',
        )

        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.DELIVERED)
        self.assertEqual(self.job.reviews_used, 1)
        self.assertEqual(self.job.submission.revision_round, 1)

    def test_freelancer_resubmit_blocked_when_review_limit_reached(self):
        self.job.allowed_reviews = 1
        self.job.reviews_used = 1
        self.job.status = JobStatus.DISPUTE_OPEN
        self.job.save(update_fields=['allowed_reviews', 'reviews_used', 'status'])
        Dispute.objects.create(job=self.job, raised_by=self.client_user, reason='Issue', status='OPEN')

        self.client_api.force_authenticate(user=self.freelancer)
        deliverable = SimpleUploadedFile('revision_v3.txt', b'again', content_type='text/plain')
        response = self.client_api.post(
            f'/api/orders/jobs/{self.job.id}/submit/',
            {'submission_text': 'Another attempt.', 'attachments': [deliverable]},
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('review rounds remaining', str(response.data).lower())

class PaystackServiceCurrencyTests(SimpleTestCase):
    @patch('orders.paystack_service.requests.post')
    def test_initialize_transaction_uses_usd_currency(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': True,
            'data': {'authorization_url': 'https://paystack.test/checkout'},
        }

        service = PaystackService()
        service.initialize_transaction(
            email='payer@example.com',
            amount=Decimal('50.00'),
            reference='REF-USD-1',
            metadata={'job_id': '1'},
        )

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs['json']['currency'], 'USD')

    @patch('orders.paystack_service.requests.post')
    def test_initialize_transaction_falls_back_to_kes_on_usd_forbidden(self, mock_post):
        usd_resp = type('Resp', (), {})()
        usd_resp.status_code = 403
        usd_resp.json = lambda: {'status': False, 'message': 'Currency not supported'}

        kes_resp = type('Resp', (), {})()
        kes_resp.status_code = 200
        kes_resp.json = lambda: {'status': True, 'data': {'authorization_url': 'https://paystack.test/kes'}}

        mock_post.side_effect = [usd_resp, kes_resp]

        service = PaystackService()
        result = service.initialize_transaction(
            email='payer@example.com',
            amount=Decimal('50.00'),
            reference='REF-FALLBACK-1',
            metadata={'job_id': '1'},
        )

        self.assertTrue(result.get('status'))
        first_currency = mock_post.call_args_list[0].kwargs['json']['currency']
        second_currency = mock_post.call_args_list[1].kwargs['json']['currency']
        self.assertEqual(first_currency, 'USD')
        self.assertEqual(second_currency, 'KES')
