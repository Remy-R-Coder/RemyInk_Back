# config/routing.py
from django.urls import path, re_path
from chat import routing as chat_routing

websocket_urlpatterns = [
    # This path directs all traffic starting with 'ws/chat/' to the chat app's routing file.
    re_path(r'ws/chat/', chat_routing.websocket_urlpatterns),
]