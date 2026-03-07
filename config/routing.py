from django.urls import path, re_path
from chat import routing as chat_routing

websocket_urlpatterns = [
    re_path(r'ws/chat/', chat_routing.websocket_urlpatterns),
]