from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.db.models.signals import post_save
from django.test import TestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient

from chat.models import GuestSession as ChatGuestSession, ChatThread, ChatMessage, MessageReadStatus
from chat.signals import broadcast_new_message
from notifications.models import Notification, NotificationPreference
from user_module.models import Role

User = get_user_model()


class PasswordSetupFlowTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.user = User.objects.create_user(
            username='client_setup',
            email='client_setup@example.com',
            password='TempPass123!',
            role=Role.CLIENT,
            is_active=True,
        )
        self.user.set_unusable_password()
        self.user.save(update_fields=['password'])
        ChatGuestSession.objects.create(
            session_key='guest_setup_session_1',
            display_name='Client001',
            display_number=1,
            converted_to_user=self.user,
        )

    def test_client_login_blocked_when_password_not_set(self):
        response = self.client_api.post(
            '/api/users/token/client/',
            {'email': self.user.email, 'password': 'anything123'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Password setup required', str(response.data))

    def test_setup_password_confirm_sets_password_and_enables_login(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        response = self.client_api.post(
            '/api/users/password/setup/confirm/',
            {
                'uid': uid,
                'token': token,
                'password': 'NewStrongPass123!',
                'confirm_password': 'NewStrongPass123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.has_usable_password())
        self.assertTrue(self.user.check_password('NewStrongPass123!'))

        login_response = self.client_api.post(
            '/api/users/token/client/',
            {'email': self.user.email, 'password': 'NewStrongPass123!'},
            format='json',
        )
        self.assertEqual(login_response.status_code, 200)

    def test_setup_password_request_sends_email_for_existing_user(self):
        response = self.client_api.post(
            '/api/users/password/setup/request/',
            {'email': self.user.email},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('set your remyink password', mail.outbox[0].subject.lower())

    def test_setup_password_request_returns_generic_response_for_unknown_user(self):
        response = self.client_api.post(
            '/api/users/password/setup/request/',
            {'email': 'unknown@example.com'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_setup_password_request_does_not_send_for_non_guest_user(self):
        non_guest_user = User.objects.create_user(
            username='non_guest_client',
            email='nonguest@example.com',
            password='TempPass123!',
            role=Role.CLIENT,
            is_active=True,
        )
        non_guest_user.set_unusable_password()
        non_guest_user.save(update_fields=['password'])

        response = self.client_api.post(
            '/api/users/password/setup/request/',
            {'email': non_guest_user.email},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_setup_password_confirm_rejects_non_guest_user(self):
        non_guest_user = User.objects.create_user(
            username='non_guest_confirm',
            email='nonguestconfirm@example.com',
            password='TempPass123!',
            role=Role.CLIENT,
            is_active=True,
        )
        non_guest_user.set_unusable_password()
        non_guest_user.save(update_fields=['password'])
        uid = urlsafe_base64_encode(force_bytes(non_guest_user.pk))
        token = default_token_generator.make_token(non_guest_user)

        response = self.client_api.post(
            '/api/users/password/setup/confirm/',
            {
                'uid': uid,
                'token': token,
                'password': 'NewStrongPass123!',
                'confirm_password': 'NewStrongPass123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('guest-converted', str(response.data))


class NotificationPreferencesCompatibilityTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.user = User.objects.create_user(
            username='notif_client',
            email='notif_client@example.com',
            password='StrongPass123!',
            role=Role.CLIENT,
            is_active=True,
        )
        self.client_api.force_authenticate(user=self.user)

    def test_get_notification_preferences_returns_legacy_fields(self):
        response = self.client_api.get('/api/users/settings/notifications/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('email_new_message', response.data)
        self.assertIn('app_new_message', response.data)
        self.assertIn('email_marketing', response.data)

    def test_patch_notification_preferences_updates_type_and_category_preferences(self):
        response = self.client_api.patch(
            '/api/users/settings/notifications/',
            {
                'email_new_offer': False,
                'app_new_message': False,
                'email_marketing': False,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)

        preferences = NotificationPreference.objects.get(user=self.user)
        self.assertFalse(preferences.type_preferences['OFFER_RECEIVED']['email'])
        self.assertFalse(preferences.type_preferences['MESSAGE']['in_app'])
        self.assertFalse(preferences.category_preferences['SYSTEM']['email'])


class DashboardNotificationsLinkTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.user = User.objects.create_user(
            username='notif_links_client',
            email='notif_links@example.com',
            password='StrongPass123!',
            role=Role.CLIENT,
            is_active=True,
        )
        self.client_api.force_authenticate(user=self.user)

    def test_dashboard_notifications_normalizes_legacy_jobs_link(self):
        Notification.objects.create(
            recipient=self.user,
            notification_type='JOB_CREATED',
            title='Job Created',
            message='Job ready',
            link='/jobs/abc123',
        )

        response = self.client_api.get('/api/users/dashboard/notifications/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]['link'], '/job/abc123')

    def test_dashboard_notifications_maps_orders_link_to_job(self):
        Notification.objects.create(
            recipient=self.user,
            notification_type='JOB_CREATED',
            title='Payment Required',
            message='Please pay',
            link='/orders',
            metadata={'job_id': 'job-001'},
        )

        response = self.client_api.get('/api/users/dashboard/notifications/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]['link'], '/job/job-001')


class DashboardNotificationReadTests(TestCase):
    def setUp(self):
        post_save.disconnect(broadcast_new_message, sender=ChatMessage)
        self.addCleanup(lambda: post_save.connect(broadcast_new_message, sender=ChatMessage))

        self.client_api = APIClient()
        self.user = User.objects.create_user(
            username='notif_read_user',
            email='notif_read_user@example.com',
            password='StrongPass123!',
            role=Role.CLIENT,
            is_active=True,
        )
        self.freelancer = User.objects.create_user(
            username='notif_read_freelancer',
            email='notif_read_freelancer@example.com',
            password='StrongPass123!',
            role=Role.FREELANCER,
            is_active=True,
        )
        self.client_api.force_authenticate(user=self.user)

    def test_marks_notification_as_read_with_notif_prefix(self):
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type='JOB_CREATED',
            title='Test',
            message='Please check',
            link='/job/abc',
            is_read=False,
        )

        response = self.client_api.post(
            f'/api/users/dashboard/notifications/notif-{notification.id}/read/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_marks_message_as_read_with_msg_prefix(self):
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            client=self.user,
        )
        message = ChatMessage.objects.create(
            thread=thread,
            sender=self.freelancer,
            message='Hello from freelancer',
        )

        response = self.client_api.post(
            f'/api/users/dashboard/notifications/msg-{message.id}/read/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            MessageReadStatus.objects.filter(message=message, user=self.user).exists()
        )

    def test_marks_notification_as_unread_with_notif_prefix(self):
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type='JOB_CREATED',
            title='Test',
            message='Please check',
            link='/job/abc',
            is_read=True,
        )

        response = self.client_api.post(
            f'/api/users/dashboard/notifications/notif-{notification.id}/unread/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        notification.refresh_from_db()
        self.assertFalse(notification.is_read)

    def test_marks_message_as_unread_with_msg_prefix(self):
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            client=self.user,
        )
        message = ChatMessage.objects.create(
            thread=thread,
            sender=self.freelancer,
            message='Hello from freelancer',
        )
        MessageReadStatus.objects.create(message=message, user=self.user)

        response = self.client_api.post(
            f'/api/users/dashboard/notifications/msg-{message.id}/unread/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            MessageReadStatus.objects.filter(message=message, user=self.user).exists()
        )


class ProfileAliasEndpointTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.user = User.objects.create_user(
            username='alias_user',
            email='alias_user@example.com',
            password='StrongPass123!',
            role=Role.CLIENT,
            is_active=True,
        )
        self.client_api.force_authenticate(user=self.user)

    def test_get_profile_alias_defaults_to_username(self):
        response = self.client_api.get('/api/users/profile/alias/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['alias'], self.user.username)

    def test_post_profile_alias_updates_display_name(self):
        response = self.client_api.post(
            '/api/users/profile/alias/',
            {'alias': 'WriterPro'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['alias'], 'WriterPro')

        response_get = self.client_api.get('/api/users/profile/alias/')
        self.assertEqual(response_get.status_code, 200)
        self.assertEqual(response_get.data['alias'], 'WriterPro')


class ProfilePictureEndpointTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.user = User.objects.create_user(
            username='picture_user',
            email='picture_user@example.com',
            password='StrongPass123!',
            role=Role.CLIENT,
            is_active=True,
        )
        self.client_api.force_authenticate(user=self.user)

    def test_get_profile_picture_endpoint(self):
        response = self.client_api.get('/api/users/profile/picture/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('picture', response.data)
        self.assertIn('country', response.data)

    def test_patch_profile_picture_endpoint_updates_country(self):
        response = self.client_api.patch(
            '/api/users/profile/picture/',
            {'country': 'Kenya'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['country'], 'Kenya')
