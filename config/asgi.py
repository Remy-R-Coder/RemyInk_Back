import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat import routing
from chat.middleware import UUIDAuthMiddlewareStack 


application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": UUIDAuthMiddlewareStack(
        URLRouter(
            routing.websocket_urlpatterns
        )
    ),
})