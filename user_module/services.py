# user_module/services.py

import secrets
import string
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()


def generate_guest_username():
    """
    Generate a unique guest username like Guest_3F9A1B
    """
    return "Guest_" + ''.join(
        secrets.choice(string.ascii_uppercase + string.digits)
        for _ in range(6)
    )


def create_guest_user():
    """
    Create a guest user in the database with timestamp
    """
    username = generate_guest_username()

    user = User.objects.create(
        username=username,
        is_guest=True,
        guest_created_at=timezone.now(),
    )

    return user
