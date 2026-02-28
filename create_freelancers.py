import os
import django
import random
from faker import Faker

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from user_module.models import User, FreelancerProfile, Role
from jobs.models import Category, SubjectArea

def create_freelancer_accounts(num_accounts=20):
    """
    Creates the specified number of freelancer accounts with random data.
    """
    fake = Faker()

    all_categories = list(Category.objects.all())
    all_subject_areas = list(SubjectArea.objects.all())

    if not all_categories or not all_subject_areas:
        print("Error: No categories or subject areas found. Please run seed_data.py first.")
        return

    print(f"Creating {num_accounts} freelancer accounts...")

    for i in range(num_accounts):
        username = fake.user_name()
        email = fake.email()
        password = 'password123' 

        # Create the User account
        user, created = User.objects.get_or_create(
            username=username,
            email=email,
            is_active=True,
            role=Role.FREELANCER # <--- This is the crucial line
        
        )
        if created:
            user.set_password(password)
            user.save()
            print(f"  ✓ Created user: {username} ({email})")
        else:
            print(f"  - User already exists: {username}. Skipping.")
            continue
        
        # Create the FreelancerProfile, which now has no required category field on creation
        freelancer_profile, created_profile = FreelancerProfile.objects.get_or_create(user=user)

        if created_profile:
            print(f"    ✓ Created freelancer profile for {username}.")
        else:
            print(f"    - Freelancer profile for {username} already exists. Skipping...")
            continue
        
        # Randomly assign 1 to 3 categories to the freelancer
        num_categories_to_assign = random.randint(1, min(3, len(all_categories)))
        assigned_categories = random.sample(all_categories, k=num_categories_to_assign)
        
        # Add the selected categories to the freelancer's profile
        freelancer_profile.categories.set(assigned_categories)
        
        # Now, select subjects that belong to the assigned categories
        assigned_subjects = []
        for category in assigned_categories:
            subjects_in_category = list(SubjectArea.objects.filter(category=category))
            num_subjects_to_assign = random.randint(1, min(5, len(subjects_in_category)))
            
            # Add subjects to the list
            assigned_subjects.extend(random.sample(subjects_in_category, k=num_subjects_to_assign))
        
        # Add the selected subjects to the freelancer's profile
        freelancer_profile.subjects.set(assigned_subjects)
        
        print(f"    ✓ Assigned {len(assigned_categories)} categories and {len(assigned_subjects)} subjects to {username}.")

    print("\nFreelancer account creation complete! ✅")

if __name__ == '__main__':
    create_freelancer_accounts(20)