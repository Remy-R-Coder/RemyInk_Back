import os
import django

# 1. Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings') 
django.setup()

from django.db import transaction
# Using the names found in your user_module imports
from jobs.models import TaskCategory, TaskSubjectArea 

def seed():
    print("--- Starting Database Clean & Seed (Professional Services Pivot) ---")
    
    try:
        with transaction.atomic():
            # 2. Clear existing data
            TaskSubjectArea.objects.all().delete()
            TaskCategory.objects.all().delete()
            print("Successfully cleared old TaskCategories and TaskSubjectAreas.")
            
            # 3. Define New Professional Categories
            categories_to_create = [
                "Content Marketing",
                "Corporate & Career",
                "Creative Writing",
                "Business Strategy"
            ]
            
            category_objs = {}
            for cat_name in categories_to_create:
                obj = TaskCategory.objects.create(name=cat_name)
                category_objs[cat_name] = obj
                print(f"Created Category: {cat_name}")

            # 4. Define Subjects for Content Marketing (Example)
            marketing_subjects = [
                "SEO Blog Posts", 
                "Email Newsletters", 
                "Social Media Copy", 
                "Website Landing Pages"
            ]
            for sub_name in marketing_subjects:
                TaskSubjectArea.objects.create(
                    category=category_objs["Content Marketing"], 
                    name=sub_name
                )
                print(f"Added Marketing Service: {sub_name}")
            
            # 5. Define Subjects for Corporate & Career
            career_subjects = [
                "Professional CV & Resume",
                "LinkedIn Profile Optimization",
                "Cover Letters",
                "Corporate Profiles"
            ]
            for sub_name in career_subjects:
                TaskSubjectArea.objects.create(
                    category=category_objs["Corporate & Career"], 
                    name=sub_name
                )
                print(f"Added Career Service: {sub_name}")

        print("--- Seed Complete: RemyInk is now a Professional Writing Agency ---")

    except Exception as e:
        print(f"Error during seeding: {e}")

if __name__ == '__main__':
    seed()