from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(
        r'^ws/chat/thread/(?P<thread_id>\d+)/$',
        consumers.GlobalChatConsumer.as_asgi(),
        name='ws-thread-detail'
    ),
    re_path(
        r'^ws/chat/new/(?P<freelancer_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$',
        consumers.GlobalChatConsumer.as_asgi(),
        name='ws-thread-create'
    ),
]