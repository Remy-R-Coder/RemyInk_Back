from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    ChatThreadViewSet,
    ChatMessageViewSet,
    guest_threads,
    GuestThreadCreateView,
    UploadAPIView,
    UnreadCountView,
    ThreadUnreadsView,
    PendingOffersView,
)
from .api_views import UserMessagingViewSet, create_or_get_thread

router = DefaultRouter()
router.register(r'threads', ChatThreadViewSet, basename='thread')
router.register(r'my-messages', UserMessagingViewSet, basename='my-messages')

urlpatterns = [
    # New user messaging API endpoints
    path('my-messages/create-thread/',
         create_or_get_thread,
         name='create-thread'),

    # Legacy endpoints (kept for backward compatibility)
    path('threads/<int:thread_pk>/messages/',
         ChatMessageViewSet.as_view({'get': 'list', 'post': 'create'}),
         name='thread-messages'),

    path('threads/<int:thread_pk>/messages/<int:pk>/update-offer/',
         ChatMessageViewSet.as_view({'post': 'update_offer_status'}),
         name='message-update-offer'),

    path('threads/<int:thread_pk>/read/',
         ChatThreadViewSet.as_view({'put': 'mark_as_read'}),
         name='thread-mark-read'),

    path('threads/sent-offers/',
         ChatThreadViewSet.as_view({'get': 'sent_offers'}),
         name='thread-sent-offers'),

    *router.urls,

    path('guest-threads/',
         guest_threads,
         name='guest-threads'),

    path('guest-thread/create/',
         GuestThreadCreateView.as_view(),
         name='guest-thread-create'),

    path('unread-count/',
         UnreadCountView.as_view(),
         name='unread-count'),

    path('thread-unreads/',
         ThreadUnreadsView.as_view(),
         name='thread-unreads'),

    path('pending-offers/',
          PendingOffersView.as_view(),
          name='pending-offers'),

    path('upload/',
         UploadAPIView.as_view(),
         name='upload'),
]