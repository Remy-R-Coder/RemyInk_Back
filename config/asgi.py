# config/asgi.py (FINAL MODIFICATION)

import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
# from channels.sessions import SessionMiddlewareStack # ❌ Remove standard session import
# from channels.auth import AuthMiddlewareStack      # ❌ Remove standard auth import

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat import routing
# ➡️ Import your custom UUID middleware stack
from chat.middleware import UUIDAuthMiddlewareStack 


application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": UUIDAuthMiddlewareStack(  # 🚨 USE THE CUSTOM STACK HERE
        URLRouter(
            routing.websocket_urlpatterns
        )
    ),
})