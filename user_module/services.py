# user_module/services.py

from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction

User = get_user_model()


def generate_guest_username():
    """
    Generate a unique sequential guest username like Guest01, Guest02, etc.
    Uses a transaction to avoid duplicates if multiple guests are created simultaneously.
    """
    with transaction.atomic():
        # Lock the last guest row for update
        last_guest = (
            User.objects.select_for_update()
            .filter(is_guest=True, username__startswith="Guest")
            .order_by("-id")
            .first()
        )

        if last_guest and last_guest.username[5:].isdigit():
            last_number = int(last_guest.username[5:])
            next_number = last_number + 1
        else:
            next_number = 1

        username = f"Guest{next_number:02d}"
        return username


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
