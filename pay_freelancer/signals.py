from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Payout
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Payout)
def update_user_balance_on_successful_payout(sender, instance, **kwargs):
    if instance.status == 'SUCCESS':
        try:
            instance.freelancer.deduct_from_balance(instance.payout_amount)
            logger.info(f"Deducted {instance.payout_amount} from {instance.freelancer.username}'s balance for payout {instance.id}")
        except Exception as e:
            logger.error(f"Failed to update user balance for payout {instance.id}: {str(e)}")