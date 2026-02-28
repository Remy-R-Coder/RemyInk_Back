# user_module/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

from .models import FreelancerProfile, Role
from jobs.models import SubjectArea, Category

User = get_user_model()


@receiver(post_save, sender=User)
def create_or_update_freelancer_profile(sender, instance, created, **kwargs):
    if instance.role in [Role.ADMIN, Role.FREELANCER]:
        # Ensure FreelancerProfile exists
        freelancer_profile, _ = FreelancerProfile.objects.get_or_create(user=instance)

        if instance.is_superuser or instance.role == Role.ADMIN:
            # ✅ Always attach ALL subject areas & categories for admins
            freelancer_profile.subjects.set(SubjectArea.objects.all())
            freelancer_profile.categories.set(Category.objects.all())
            freelancer_profile.save()
            print(f"[ADMIN] Ensured freelancer profile for '{instance.username}' with ALL subjects & categories.")

        elif instance.role == Role.FREELANCER:
            # ✅ Freelancers keep empty profile unless onboarding assigns data
            if created:  # only clear at first creation
                freelancer_profile.subjects.clear()
                freelancer_profile.categories.clear()
                freelancer_profile.save()
                print(f"[FREELANCER] Created empty freelancer profile for '{instance.username}'.")
