import os
import django

# 1. Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings') 
django.setup()

from django.db import transaction
# Using the names found in your user_module imports
from jobs.models import TaskCategory, TaskSubjectArea 

def seed():
    print("--- Starting Database Clean & Seed ---")
    
    try:
        with transaction.atomic():
            # 2. Clear existing data
            TaskSubjectArea.objects.all().delete()
            TaskCategory.objects.all().delete()
            print("Successfully cleared old TaskCategories and TaskSubjectAreas.")
            
            # 3. Define Categories
            categories_to_create = [
                "Business & Content",
                "IB Diploma Program",
                "Software & Design",
                "University & Academic"
            ]
            
            category_objs = {}
            for cat_name in categories_to_create:
                # Use TaskCategory here
                obj = TaskCategory.objects.create(name=cat_name)
                category_objs[cat_name] = obj
                print(f"Created Category: {cat_name}")

            # 4. Define Subjects for IB Diploma
            ib_subjects = ["Economics HL", "Physics SL", "English A", "Psychology"]
            for sub_name in ib_subjects:
                # Use TaskSubjectArea here
                TaskSubjectArea.objects.create(
                    category=category_objs["IB Diploma Program"], 
                    name=sub_name
                )
                print(f"Added IB Subject: {sub_name}")

        print("--- Seed Complete ---")

    except Exception as e:
        print(f"Error during seeding: {e}")
        print("\nDouble check: Do 'TaskCategory' and 'TaskSubjectArea' exist in jobs/models.py?")

if __name__ == '__main__':
    seed()