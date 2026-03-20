import os
import django
from collections import OrderedDict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from user_module.models import Category, SubjectArea 

def create_initial_data():
    """
    Populates the database with a specialized IB focus and 
    compact professional categories.
    """
    data = OrderedDict([
        # --- PRIMARY FOCUS: IB DIPLOMA ---
        ('IB Diploma Program', [
            'IB Mathematics (AA/AI)', 
            'IB Sciences (Physics, Chem, Bio)', 
            'IB Humanities (Econ, Hist, Psych)',
            'IB Theory of Knowledge (TOK)',
            'IB Extended Essay (EE) Support',
            'IB Languages & Literature'
        ]),
        
        # --- SECONDARY: UNIVERSITY & RESEARCH ---
        ('University & Academic', [
            'Thesis & Dissertation Support', 
            'Admissions & Personal Statements',
            'Advanced STEM & Data Analysis',
            'General Humanities & Arts'
        ]),

        # --- TERTIARY: TECH & DESIGN ---
        ('Software & Design', [
            'Web & Mobile Development', 
            'Graphic & UI/UX Design',
            'Software Engineering',
            'Video & Animation'
        ]),

        # --- QUATERNARY: BUSINESS & WRITING ---
        ('Business & Content', [
            'Copywriting & SEO', 
            'Business Strategy & Marketing',
            'Finance & Accounting',
            'Technical & Grant Writing'
        ]),
    ])

    print("Cleaning up old categories (optional)...")
    # Uncomment the next line if you want to wipe the slate clean first:
    # Category.objects.all().delete()

    for cat_name, sub_names in data.items():
        category, _ = Category.objects.get_or_create(name=cat_name)
        print(f"Adding Category: {cat_name}")
        for sub_name in sub_names:
            SubjectArea.objects.get_or_create(name=sub_name, category=category)
            print(f"  - Added Subject: {sub_name}")

    print("\nDatabase populated successfully! ✅")

if __name__ == '__main__':
    create_initial_data()
