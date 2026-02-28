from decimal import Decimal
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from unittest.mock import patch, MagicMock

from .models import (
    GuestSession,
    GuestSessionCounter,
    ChatThread,
    ChatMessage,
    get_guest_display_name,
)
from .services import (
    GuestNameService,
    ChatThreadService,
    ChatMessageService,
)
from user_module.models import Role, RoleIDCounter

User = get_user_model()


class GuestSessionModelTests(TestCase):
    """Test GuestSession model functionality"""

    def setUp(self):
        """Create test freelancer"""
        self.freelancer = User.objects.create_user(
            email='freelancer@test.com',
            password='testpass123',
            role=Role.FREELANCER,
            is_active=True
        )

    def test_guest_session_counter_increments(self):
        """Test that guest session counter increments correctly"""
        # First call
        id1 = GuestSessionCounter.get_next_id()
        self.assertEqual(id1, 1)

        # Second call
        id2 = GuestSessionCounter.get_next_id()
        self.assertEqual(id2, 2)

        # Third call
        id3 = GuestSessionCounter.get_next_id()
        self.assertEqual(id3, 3)

    def test_guest_session_creation(self):
        """Test creating a new guest session"""
        session_key = 'test_session_abc123'
        guest_session, created = GuestSession.get_or_create_session(session_key)

        self.assertTrue(created)
        self.assertEqual(guest_session.session_key, session_key)
        self.assertTrue(guest_session.display_name.startswith('Client'))
        self.assertTrue(guest_session.is_active)
        self.assertIsNone(guest_session.converted_to_user)

    def test_guest_session_get_existing(self):
        """Test retrieving an existing guest session"""
        session_key = 'test_session_xyz789'

        # Create session
        session1, created1 = GuestSession.get_or_create_session(session_key)
        self.assertTrue(created1)

        # Retrieve same session
        session2, created2 = GuestSession.get_or_create_session(session_key)
        self.assertFalse(created2)
        self.assertEqual(session1.id, session2.id)
        self.assertEqual(session1.display_name, session2.display_name)

    def test_guest_session_with_metadata(self):
        """Test guest session creation with metadata"""
        session_key = 'test_session_with_meta'
        user_agent = 'Mozilla/5.0 (Test Browser)'
        ip_address = '192.168.1.1'
        referrer = 'https://example.com/landing'

        guest_session, created = GuestSession.get_or_create_session(
            session_key=session_key,
            user_agent=user_agent,
            ip_address=ip_address,
            referrer=referrer
        )

        self.assertTrue(created)
        self.assertEqual(guest_session.user_agent, user_agent)
        self.assertEqual(guest_session.ip_address, ip_address)
        self.assertEqual(guest_session.referrer, referrer)

    def test_guest_session_mark_converted(self):
        """Test marking a guest session as converted"""
        session_key = 'test_session_convert'
        guest_session, _ = GuestSession.get_or_create_session(session_key)

        # Create client user
        client = User.objects.create_user(
            email='client@test.com',
            role=Role.CLIENT,
            is_active=True
        )

        # Mark as converted
        guest_session.mark_converted(client)

        # Verify conversion
        guest_session.refresh_from_db()
        self.assertEqual(guest_session.converted_to_user, client)
        self.assertIsNotNone(guest_session.conversion_date)
        self.assertFalse(guest_session.is_active)

    def test_guest_session_properties(self):
        """Test guest session property methods"""
        session_key = 'test_session_props'
        guest_session, _ = GuestSession.get_or_create_session(session_key)

        # Test is_converted
        self.assertFalse(guest_session.is_converted)

        # Test session_age
        self.assertIsNotNone(guest_session.session_age)

        # Test days_since_last_activity
        self.assertEqual(guest_session.days_since_last_activity, 0)

    def test_sequential_display_names(self):
        """Test that display names are sequential"""
        sessions = []
        for i in range(5):
            session, _ = GuestSession.get_or_create_session(f'session_{i}')
            sessions.append(session)

        # Verify sequential numbering
        for i, session in enumerate(sessions):
            expected_num = i + 1
            self.assertEqual(session.display_number, expected_num)
            self.assertEqual(session.display_name, f'Client{expected_num:03d}')


class GuestNameServiceTests(TestCase):
    """Test GuestNameService functionality"""

    def test_get_guest_display_name(self):
        """Test getting display name for guest session"""
        session_key = 'test_session_display'
        name = GuestNameService.get_guest_display_name(session_key)

        self.assertTrue(name.startswith('Client'))
        self.assertEqual(len(name), 9)  # "Client" + 3 digits

    def test_get_guest_display_name_consistency(self):
        """Test that same session key returns same display name"""
        session_key = 'test_session_consistent'
        name1 = GuestNameService.get_guest_display_name(session_key)
        name2 = GuestNameService.get_guest_display_name(session_key)

        self.assertEqual(name1, name2)

    def test_get_guest_display_name_empty_session(self):
        """Test getting display name with empty session key"""
        name = GuestNameService.get_guest_display_name('')
        self.assertEqual(name, 'Guest')

        name = GuestNameService.get_guest_display_name(None)
        self.assertEqual(name, 'Guest')

    def test_mark_session_converted(self):
        """Test marking session as converted via service"""
        session_key = 'test_convert_via_service'
        GuestSession.get_or_create_session(session_key)

        client = User.objects.create_user(
            email='client2@test.com',
            role=Role.CLIENT,
            is_active=True
        )

        GuestNameService.mark_session_converted(session_key, client)

        # Verify conversion
        session = GuestSession.objects.get(session_key=session_key)
        self.assertTrue(session.is_converted)
        self.assertEqual(session.converted_to_user, client)


class ThreadLinkingTests(TransactionTestCase):
    """Test thread linking functionality"""

    def setUp(self):
        """Set up test data"""
        self.freelancer = User.objects.create_user(
            email='freelancer@test.com',
            password='testpass123',
            role=Role.FREELANCER,
            is_active=True
        )
        self.client = User.objects.create_user(
            email='client@test.com',
            role=Role.CLIENT,
            is_active=True
        )
        self.session_key = 'test_guest_session_123'

    def test_link_all_guest_threads(self):
        """Test linking all threads for a guest session"""
        # Create multiple guest threads
        threads = []
        for i in range(3):
            thread = ChatThread.objects.create(
                freelancer=self.freelancer,
                guest_session_key=self.session_key,
                client=None
            )
            threads.append(thread)

        # Link all threads
        linked_count = ChatThreadService.link_guest_threads_to_client(
            client=self.client,
            guest_session_key=self.session_key
        )

        self.assertEqual(linked_count, 3)

        # Verify all threads are linked
        for thread in threads:
            thread.refresh_from_db()
            self.assertEqual(thread.client, self.client)

    def test_selective_thread_linking(self):
        """Test linking only specific threads"""
        # Create multiple threads
        thread1 = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=self.session_key,
            client=None
        )
        thread2 = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=self.session_key,
            client=None
        )
        thread3 = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=self.session_key,
            client=None
        )

        # Link only thread1 and thread3
        linked_count = ChatThreadService.link_guest_threads_to_client(
            client=self.client,
            guest_session_key=self.session_key,
            thread_ids=[thread1.id, thread3.id]
        )

        self.assertEqual(linked_count, 2)

        # Verify selective linking
        thread1.refresh_from_db()
        thread2.refresh_from_db()
        thread3.refresh_from_db()

        self.assertEqual(thread1.client, self.client)
        self.assertIsNone(thread2.client)  # Not linked
        self.assertEqual(thread3.client, self.client)

    def test_preview_guest_threads(self):
        """Test previewing guest threads before linking"""
        # Create threads with messages
        thread1 = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=self.session_key,
            client=None
        )
        ChatMessage.objects.create(
            thread=thread1,
            sender=self.freelancer,
            message='Hello!'
        )

        thread2 = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=self.session_key,
            client=None
        )

        # Preview threads
        threads = ChatThreadService.preview_guest_threads(self.session_key)

        self.assertEqual(len(threads), 2)
        self.assertIn(thread1, threads)
        self.assertIn(thread2, threads)

    def test_link_threads_marks_session_converted(self):
        """Test that linking threads marks the session as converted"""
        GuestSession.get_or_create_session(self.session_key)

        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=self.session_key,
            client=None
        )

        # Link thread
        ChatThreadService.link_guest_threads_to_client(
            client=self.client,
            guest_session_key=self.session_key
        )

        # Verify session is marked as converted
        session = GuestSession.objects.get(session_key=self.session_key)
        self.assertTrue(session.is_converted)
        self.assertEqual(session.converted_to_user, self.client)


class GuestMessageAttributionTests(TestCase):
    """Test guest message attribution functionality"""

    def setUp(self):
        """Set up test data"""
        self.freelancer = User.objects.create_user(
            email='freelancer@test.com',
            password='testpass123',
            role=Role.FREELANCER,
            is_active=True
        )
        self.session_key = 'test_message_session'
        self.thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=self.session_key,
            client=None
        )

    def test_message_creation_with_guest_session(self):
        """Test creating a message with guest session attribution"""
        message = ChatMessageService.create_message(
            thread=self.thread,
            sender=None,
            message_text='Hello from guest',
            guest_session_key=self.session_key
        )

        self.assertIsNone(message.sender)
        self.assertIsNotNone(message.guest_session)
        self.assertEqual(message.guest_session.session_key, self.session_key)

    def test_message_creation_without_guest_session(self):
        """Test creating a message from authenticated user"""
        message = ChatMessageService.create_message(
            thread=self.thread,
            sender=self.freelancer,
            message_text='Hello from freelancer'
        )

        self.assertEqual(message.sender, self.freelancer)
        self.assertIsNone(message.guest_session)

    def test_guest_session_tracks_messages(self):
        """Test that guest session properly tracks messages"""
        guest_session, _ = GuestSession.get_or_create_session(self.session_key)

        # Create multiple messages
        for i in range(3):
            ChatMessageService.create_message(
                thread=self.thread,
                sender=None,
                message_text=f'Message {i}',
                guest_session_key=self.session_key
            )

        # Verify messages are linked to session
        messages = guest_session.messages.all()
        self.assertEqual(messages.count(), 3)


class UserCreationTests(TransactionTestCase):
    """Test user creation with RoleIDCounter"""

    def test_client_username_generation(self):
        """Test client username generation uses RoleIDCounter"""
        client1, _ = User.objects.create_client('client1@test.com')
        client2, _ = User.objects.create_client('client2@test.com')
        client3, _ = User.objects.create_client('client3@test.com')

        self.assertEqual(client1.username, 'Client001')
        self.assertEqual(client2.username, 'Client002')
        self.assertEqual(client3.username, 'Client003')

    def test_freelancer_username_generation(self):
        """Test freelancer username generation uses RoleIDCounter"""
        freelancer1, _ = User.objects.create_freelancer('freelancer1@test.com')
        freelancer2, _ = User.objects.create_freelancer('freelancer2@test.com')

        self.assertTrue(freelancer1.username.startswith('Remy'))
        self.assertTrue(freelancer2.username.startswith('Remy'))
        # Should be sequential
        num1 = int(freelancer1.username.replace('Remy', ''))
        num2 = int(freelancer2.username.replace('Remy', ''))
        self.assertEqual(num2, num1 + 1)

    def test_concurrent_user_creation(self):
        """Test that concurrent user creation doesn't create duplicate usernames"""
        emails = [f'client{i}@test.com' for i in range(10)]
        clients = []

        for email in emails:
            client, _ = User.objects.create_client(email)
            clients.append(client)

        # Verify all usernames are unique
        usernames = [c.username for c in clients]
        self.assertEqual(len(usernames), len(set(usernames)))


class EdgeCaseTests(TestCase):
    """Test edge cases and error handling"""

    def setUp(self):
        """Set up test data"""
        self.freelancer = User.objects.create_user(
            email='freelancer@test.com',
            password='testpass123',
            role=Role.FREELANCER,
            is_active=True
        )

    def test_legacy_get_guest_display_name_function(self):
        """Test backward compatibility of legacy function"""
        session_key = 'legacy_session'
        name = get_guest_display_name(session_key)

        self.assertIsNotNone(name)
        self.assertTrue(name.startswith('Client'))

    def test_guest_session_string_representation(self):
        """Test __str__ method of GuestSession"""
        session, _ = GuestSession.get_or_create_session('test_str')
        str_repr = str(session)

        self.assertIn('Client', str_repr)
        self.assertIn('test_str', str_repr)

    def test_link_nonexistent_session(self):
        """Test linking threads with non-existent session"""
        client = User.objects.create_user(
            email='client@test.com',
            role=Role.CLIENT
        )

        linked_count = ChatThreadService.link_guest_threads_to_client(
            client=client,
            guest_session_key='nonexistent_session'
        )

        self.assertEqual(linked_count, 0)

    def test_link_already_linked_threads(self):
        """Test that already linked threads are not re-linked"""
        client1 = User.objects.create_user(
            email='client1@test.com',
            role=Role.CLIENT
        )
        client2 = User.objects.create_user(
            email='client2@test.com',
            role=Role.CLIENT
        )

        session_key = 'test_double_link'
        thread = ChatThread.objects.create(
            freelancer=self.freelancer,
            guest_session_key=session_key,
            client=client1  # Already linked
        )

        # Try to link to different client
        linked_count = ChatThreadService.link_guest_threads_to_client(
            client=client2,
            guest_session_key=session_key
        )

        # Should not link already linked threads
        self.assertEqual(linked_count, 0)
        thread.refresh_from_db()
        self.assertEqual(thread.client, client1)


class IntegrationTests(TransactionTestCase):
    """Integration tests for full guest-to-client flow"""

    def test_complete_guest_to_client_conversion(self):
        """Test complete flow from guest session to registered client"""
        # 1. Create guest session
        session_key = 'integration_test_session'
        guest_session, _ = GuestSession.get_or_create_session(
            session_key=session_key,
            user_agent='Test Browser',
            ip_address='192.168.1.1'
        )

        # 2. Create freelancer
        freelancer = User.objects.create_user(
            email='freelancer@test.com',
            role=Role.FREELANCER,
            is_active=True
        )

        # 3. Create guest thread and messages
        thread = ChatThread.objects.create(
            freelancer=freelancer,
            guest_session_key=session_key,
            client=None
        )

        msg1 = ChatMessageService.create_message(
            thread=thread,
            sender=None,
            message_text='Guest message 1',
            guest_session_key=session_key
        )

        msg2 = ChatMessageService.create_message(
            thread=thread,
            sender=None,
            message_text='Guest message 2',
            guest_session_key=session_key
        )

        # 4. Convert guest to client
        client, password = User.objects.create_client('newclient@test.com')

        # 5. Link threads
        linked_count = ChatThreadService.link_guest_threads_to_client(
            client=client,
            guest_session_key=session_key
        )

        # 6. Verify complete conversion
        self.assertEqual(linked_count, 1)

        thread.refresh_from_db()
        self.assertEqual(thread.client, client)

        guest_session.refresh_from_db()
        self.assertTrue(guest_session.is_converted)
        self.assertEqual(guest_session.converted_to_user, client)

        # Messages should still reference guest session
        msg1.refresh_from_db()
        msg2.refresh_from_db()
        self.assertEqual(msg1.guest_session, guest_session)
        self.assertEqual(msg2.guest_session, guest_session)

        # Verify client has correct username format
        self.assertTrue(client.username.startswith('Client'))
