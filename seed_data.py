import os
import django

# 1. Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings') 
django.setup()

from django.db import transaction
from jobs.models import TaskCategory, TaskSubjectArea 

def seed():
    print("--- Starting Database Clean & Seed (Expanded Professional Pivot) ---")
    
    try:
        with transaction.atomic():
            # 2. Clear existing data
            TaskSubjectArea.objects.all().delete()
            TaskCategory.objects.all().delete()
            print("Successfully cleared old TaskCategories and TaskSubjectAreas.")
            
            # 3. Define 6 Professional Categories
            categories_to_create = [
                "Content Marketing",
                "Corporate & Career",
                "Creative Writing",
                "Business Strategy",
                "Digital Media & Design",
                "E-commerce Solutions"
            ]
            
            category_objs = {}
            for cat_name in categories_to_create:
                obj = TaskCategory.objects.create(name=cat_name)
                category_objs[cat_name] = obj
                print(f"Created Category: {cat_name}")

            # 4. Content Marketing Subjects
            marketing_subjects = ["SEO Blog Posts", "Email Newsletters", "Social Media Copy", "Website Landing Pages"]
            for sub_name in marketing_subjects:
                TaskSubjectArea.objects.create(category=category_objs["Content Marketing"], name=sub_name)
            
            # 5. Corporate & Career Subjects
            career_subjects = ["Professional CV & Resume", "LinkedIn Optimization", "Cover Letters", "Executive Bios"]
            for sub_name in career_subjects:
                TaskSubjectArea.objects.create(category=category_objs["Corporate & Career"], name=sub_name)

            # 6. Creative Writing Subjects
            creative_subjects = ["Ghostwriting", "Scriptwriting", "Poetry & Prose", "Short Stories"]
            for sub_name in creative_subjects:
                TaskSubjectArea.objects.create(category=category_objs["Creative Writing"], name=sub_name)

            # 7. Business Strategy Subjects
            strategy_subjects = ["Pitch Decks", "Business Plans", "Market Research Reports", "White Papers"]
            for sub_name in strategy_subjects:
                TaskSubjectArea.objects.create(category=category_objs["Business Strategy"], name=sub_name)

            # 8. Digital Media & Design Subjects (New)
            design_subjects = ["Brand Identity Design", "Presentation Design", "Infographics", "Digital Ad Creative"]
            for sub_name in design_subjects:
                TaskSubjectArea.objects.create(category=category_objs["Digital Media & Design"], name=sub_name)

            # 9. E-commerce Solutions Subjects (New)
            ecomm_subjects = ["Product Descriptions", "Shopify Store Copy", "Amazon Listing Optimization", "Sales Funnel Copy"]
            for sub_name in ecomm_subjects:
                TaskSubjectArea.objects.create(category=category_objs["E-commerce Solutions"], name=sub_name)

        print("--- Seed Complete: 6 Categories & 24 Subjects Created ---")

    except Exception as e:
        print(f"Error during seeding: {e}")

if __name__ == '__main__':
    seed()