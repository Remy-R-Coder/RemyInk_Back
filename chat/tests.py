from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.core import mail
from channels.testing import WebsocketCommunicator
from channels.layers import get_channel_layer
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken
import json

from .models import ChatThread, ChatMessage, MessageReadStatus, ChatAttachment
from .services import ChatThreadService, ChatMessageService, GuestNameService
from .constants import OfferStatus
from .signals import broadcast_new_message
from user_module.models import Role
from orders.models import JobStatus

User = get_user_model()


class ChatThreadModelTest(TestCase):
    """Test cases for ChatThread model."""
    
    def setUp(self):
        """Set up test data."""
        self.freelancer = User.objects.create_user(
            username='freelancer1',
            email='freelancer@test.com',
            password='testpass123',
            role=Role.FREELANCER
        )
        
        self.client_user = User.objects.create_user(
            username='client1',
            email='client@test.com',
            password='testpass123',
            role=Role.CLIENT
        )
    
    def test_create_authenticated_thread(self):
        """Test creating a thread between authenticated users."""
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            client=self.client_user
        )
        
        self.assertIsNotNone(thread.id)
        self.assertEqual(thread.freelancer, self.freelancer)
        self.assertEqual(thread.client, self.client_user)
        self.assertFalse(thread.is_guest_thread)
    
    def test_create_guest_thread(self):
        """Test creating a guest thread."""
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key='test_session_123'
        )
        
        self.assertIsNotNone(thread.id)
        self.assertIsNone(thread.client)
        self.assertTrue(thread.is_guest_thread)
        self.assertEqual(thread.guest_session_key, 'test_session_123')
    
    def test_is_participant(self):
        """Test participant checking."""
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            client=self.client_user
        )
        
        self.assertTrue(thread.is_participant(self.freelancer))
        self.assertTrue(thread.is_participant(self.client_user))
        
        # Create another user who is not a participant
        other_user = User.objects.create_user(
            username='other',
            email='other@test.com',
            password='testpass123'
        )
        self.assertFalse(thread.is_participant(other_user))
    
    def test_get_other_party(self):
        """Test getting the other party in a conversation."""
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            client=self.client_user
        )
        
        self.assertEqual(
            thread.get_other_party(self.freelancer),
            self.client_user
        )
        self.assertEqual(
            thread.get_other_party(self.client_user),
            self.freelancer
        )


class ChatMessageModelTest(TestCase):
    """Test cases for ChatMessage model."""
    
    def setUp(self):
        """Set up test data."""
        self.freelancer = User.objects.create_user(
            username='freelancer1',
            email='freelancer@test.com',
            password='testpass123',
            role=Role.FREELANCER
        )
        
        self.client_user = User.objects.create_user(
            username='client1',
            email='client@test.com',
            password='testpass123',
            role=Role.CLIENT
        )
        
        self.thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            client=self.client_user
        )
    
    def test_create_regular_message(self):
        """Test creating a regular chat message."""
        message = ChatMessage.objects.create(
            thread=self.thread,
            sender=self.client_user,
            message='Hello, I need help with a project'
        )
        
        self.assertIsNotNone(message.id)
        self.assertEqual(message.sender, self.client_user)
        self.assertFalse(message.is_offer)
        self.assertEqual(message.message, 'Hello, I need help with a project')
    
    def test_create_offer_message(self):
        """Test creating an offer message."""
        message = ChatMessage.objects.create(
            thread=self.thread,
            sender=self.freelancer,
            message='Project Offer',
            is_offer=True,
            offer_title='Website Development',
            offer_price=1500.00,
            offer_timeline=14,
            offer_description='I will build your website',
            offer_status=OfferStatus.PENDING
        )
        
        self.assertTrue(message.is_offer)
        self.assertTrue(message.is_pending_offer)
        self.assertFalse(message.is_accepted_offer)
        self.assertEqual(message.offer_title, 'Website Development')
        self.assertEqual(float(message.offer_price), 1500.00)
    
    def test_offer_status_properties(self):
        """Test offer status properties."""
        message = ChatMessage.objects.create(
            thread=self.thread,
            sender=self.freelancer,
            is_offer=True,
            offer_title='Test Offer',
            offer_price=1000.00,
            offer_timeline=7,
            offer_status=OfferStatus.ACCEPTED
        )
        
        self.assertTrue(message.is_accepted_offer)
        self.assertFalse(message.is_pending_offer)


class ChatThreadServiceTest(TestCase):
    """Test cases for ChatThreadService."""
    
    def setUp(self):
        """Set up test data."""
        self.freelancer = User.objects.create_user(
            username='freelancer1',
            email='freelancer@test.com',
            password='testpass123',
            role=Role.FREELANCER
        )
        
        self.client_user = User.objects.create_user(
            username='client1',
            email='client@test.com',
            password='testpass123',
            role=Role.CLIENT
        )
    
    def test_get_or_create_authenticated_thread(self):
        """Test getting or creating authenticated thread."""
        # First call should create
        thread1, created1 = ChatThreadService.get_or_create_authenticated_thread(
            self.client_user,
            str(self.freelancer.id)
        )
        
        self.assertTrue(created1)
        self.assertIsNotNone(thread1)
        
        # Second call should retrieve
        thread2, created2 = ChatThreadService.get_or_create_authenticated_thread(
            self.client_user,
            str(self.freelancer.id)
        )
        
        self.assertFalse(created2)
        self.assertEqual(thread1.id, thread2.id)
    
    def test_get_or_create_guest_thread(self):
        """Test getting or creating guest thread."""
        session_key = 'test_session_123'
        
        # First call should create
        thread1, created1 = ChatThreadService.get_or_create_guest_thread(
            session_key,
            str(self.freelancer.id)
        )
        
        self.assertTrue(created1)
        self.assertIsNotNone(thread1)
        self.assertEqual(thread1.guest_session_key, session_key)
        
        # Second call should retrieve
        thread2, created2 = ChatThreadService.get_or_create_guest_thread(
            session_key,
            str(self.freelancer.id)
        )
        
        self.assertFalse(created2)
        self.assertEqual(thread1.id, thread2.id)
    
    def test_link_guest_threads_to_client(self):
        """Test linking guest threads to a client account."""
        session_key = 'test_session_123'
        
        # Create a guest thread
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=session_key
        )
        
        self.assertIsNone(thread.client)
        
        # Link to client
        count = ChatThreadService.link_guest_threads_to_client(
            self.client_user,
            session_key
        )
        
        self.assertEqual(count, 1)
        
        # Refresh from database
        thread.refresh_from_db()
        self.assertEqual(thread.client, self.client_user)


class ChatMessageServiceTest(TestCase):
    """Test cases for ChatMessageService."""
    
    def setUp(self):
        """Set up test data."""
        self.freelancer = User.objects.create_user(
            username='freelancer1',
            email='freelancer@test.com',
            password='testpass123',
            role=Role.FREELANCER
        )
        
        self.client_user = User.objects.create_user(
            username='client1',
            email='client@test.com',
            password='testpass123',
            role=Role.CLIENT
        )
        
        self.thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            client=self.client_user
        )
    
    def test_create_message(self):
        """Test creating a message."""
        message = ChatMessageService.create_message(
            thread=self.thread,
            sender=self.client_user,
            message_text='Test message'
        )
        
        self.assertIsNotNone(message.id)
        self.assertEqual(message.message, 'Test message')
        
        # Check thread was updated
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.last_message, 'Test message')
    
    def test_update_offer_status(self):
        """Test updating offer status."""
        # Create offer
        offer = ChatMessage.objects.create(
            thread=self.thread,
            sender=self.freelancer,
            is_offer=True,
            offer_title='Test Offer',
            offer_price=1000.00,
            offer_timeline=7,
            offer_status=OfferStatus.PENDING
        )
        
        # Client accepts offer
        success = ChatMessageService.update_offer_status(
            offer,
            OfferStatus.ACCEPTED,
            self.client_user,
            None
        )
        
        self.assertTrue(success)
        
        # Refresh from database
        offer.refresh_from_db()
        self.assertEqual(offer.offer_status, OfferStatus.ACCEPTED)


class GuestNameServiceTest(TestCase):
    """Test cases for GuestNameService."""
    
    def test_guest_name_generation(self):
        """Test guest name generation."""
        session_key = 'test_session_123'
        
        name1 = GuestNameService.get_guest_display_name(session_key)
        self.assertTrue(name1.startswith('Client'))
        
        # Should return same name for same session
        name2 = GuestNameService.get_guest_display_name(session_key)
        self.assertEqual(name1, name2)
        
        # Different session should get different name
        name3 = GuestNameService.get_guest_display_name('different_session')
        self.assertNotEqual(name1, name3)


class ChatAPITest(TestCase):
    """Test cases for chat API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.freelancer = User.objects.create_user(
            username='freelancer1',
            email='freelancer@test.com',
            password='testpass123',
            role=Role.FREELANCER
        )
        
        self.client_user = User.objects.create_user(
            username='client1',
            email='client@test.com',
            password='testpass123',
            role=Role.CLIENT
        )
    
    def test_thread_list_authenticated(self):
        """Test listing threads for authenticated user."""
        # Create a thread
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            client=self.client_user
        )
        
        # Login
        self.client.login(username='client1', password='testpass123')
        
        # Make request
        response = self.client.get('/api/chat/threads/')
        
        self.assertEqual(response.status_code, 200)

    def test_update_offer_allows_valid_guest_session_even_if_logged_in_as_other_user(self):
        """A valid guest session key should authorize offer response in a guest thread."""
        post_save.disconnect(broadcast_new_message, sender=ChatMessage)
        self.addCleanup(lambda: post_save.connect(broadcast_new_message, sender=ChatMessage))

        guest_session_key = 'guest_session_for_offer_update'
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=guest_session_key
        )
        offer = ChatMessage.objects.create(
            thread=thread,
            sender=self.freelancer,
            is_offer=True,
            offer_title='Landing Page',
            offer_price=500.00,
            offer_timeline=5,
            offer_status=OfferStatus.PENDING
        )

        admin_user = User.objects.create_user(
            username='admin1',
            email='admin1@test.com',
            password='testpass123',
            role=Role.ADMIN,
            is_active=True,
        )
        access_token = str(AccessToken.for_user(admin_user))

        url = f'/api/chat/threads/{thread.id}/messages/{offer.id}/update-offer/?session_key={guest_session_key}'
        response = self.client.post(
            url,
            data={'offer_status': OfferStatus.ACCEPTED},
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {access_token}',
        )

        self.assertEqual(response.status_code, 200)
        offer.refresh_from_db()
        self.assertEqual(offer.offer_status, OfferStatus.ACCEPTED)

    def test_guest_accepts_freelancer_offer_creates_job_with_shadow_client(self):
        post_save.disconnect(broadcast_new_message, sender=ChatMessage)
        self.addCleanup(lambda: post_save.connect(broadcast_new_message, sender=ChatMessage))

        session = self.client.session
        if not session.session_key:
            session.save()
        guest_session_key = session.session_key

        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=guest_session_key,
        )
        offer = ChatMessage.objects.create(
            thread=thread,
            sender=self.freelancer,
            is_offer=True,
            offer_title='API Integration',
            offer_price=1200.00,
            offer_timeline=10,
            offer_revisions=4,
            offer_status=OfferStatus.PENDING,
        )

        response = self.client.post(
            f'/api/chat/threads/{thread.id}/messages/{offer.id}/update-offer/?session_key={guest_session_key}',
            data={
                'offer_status': OfferStatus.ACCEPTED,
                'client_email': 'guestclient@example.com',
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        offer.refresh_from_db()
        thread.refresh_from_db()

        self.assertEqual(offer.offer_status, OfferStatus.ACCEPTED)
        self.assertIsNotNone(offer.created_job)
        self.assertIsNotNone(thread.client)
        self.assertTrue(str(thread.client.email).endswith('.shadow'))
        self.assertFalse(thread.client.is_active)
        self.assertEqual(offer.created_job.status, JobStatus.PROVISIONAL)
        self.assertEqual(offer.created_job.allowed_reviews, 4)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(response.data.get('job_created', {}).get('payment_required'))
        self.assertEqual(response.data.get('job_created', {}).get('allowed_reviews'), 4)
        self.assertFalse(response.data.get('account_created'))

    def test_update_offer_accepts_legacy_action_payload(self):
        post_save.disconnect(broadcast_new_message, sender=ChatMessage)
        self.addCleanup(lambda: post_save.connect(broadcast_new_message, sender=ChatMessage))

        guest_session_key = 'guest_session_legacy_action'
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=guest_session_key
        )
        offer = ChatMessage.objects.create(
            thread=thread,
            sender=self.freelancer,
            is_offer=True,
            offer_title='Legacy Payload Offer',
            offer_price=100.00,
            offer_timeline=3,
            offer_status=OfferStatus.PENDING
        )

        response = self.client.post(
            f'/api/chat/threads/{thread.id}/messages/{offer.id}/update-offer/?session_key={guest_session_key}',
            data={'action': 'accept'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        offer.refresh_from_db()
        self.assertEqual(offer.offer_status, OfferStatus.ACCEPTED)

    def test_update_offer_accepts_offer_status_accept_variant(self):
        post_save.disconnect(broadcast_new_message, sender=ChatMessage)
        self.addCleanup(lambda: post_save.connect(broadcast_new_message, sender=ChatMessage))

        guest_session_key = 'guest_session_status_variant'
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=guest_session_key
        )
        offer = ChatMessage.objects.create(
            thread=thread,
            sender=self.freelancer,
            is_offer=True,
            offer_title='Variant Status Offer',
            offer_price=100.00,
            offer_timeline=3,
            offer_status=OfferStatus.PENDING
        )

        response = self.client.post(
            f'/api/chat/threads/{thread.id}/messages/{offer.id}/update-offer/?session_key={guest_session_key}',
            data={'offer_status': 'ACCEPT'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        offer.refresh_from_db()
        self.assertEqual(offer.offer_status, OfferStatus.ACCEPTED)

    def test_guest_accept_offer_does_not_finalize_existing_client_email_pre_payment(self):
        post_save.disconnect(broadcast_new_message, sender=ChatMessage)
        self.addCleanup(lambda: post_save.connect(broadcast_new_message, sender=ChatMessage))

        existing_client = User.objects.create_user(
            username='existingclient',
            email='existingclient@example.com',
            password='testpass123',
            role=Role.CLIENT,
            is_active=True,
        )

        guest_session_key = 'guest_session_existing_client'
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=guest_session_key
        )
        offer = ChatMessage.objects.create(
            thread=thread,
            sender=self.freelancer,
            is_offer=True,
            offer_title='Reuse Account Offer',
            offer_price=450.00,
            offer_timeline=5,
            offer_status=OfferStatus.PENDING
        )

        response = self.client.post(
            f'/api/chat/threads/{thread.id}/messages/{offer.id}/update-offer/?session_key={guest_session_key}',
            data={
                'offer_status': OfferStatus.ACCEPTED,
                'client_email': existing_client.email,
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        thread.refresh_from_db()
        offer.refresh_from_db()

        self.assertNotEqual(thread.client_id, existing_client.id)
        self.assertEqual(offer.offer_status, OfferStatus.ACCEPTED)
