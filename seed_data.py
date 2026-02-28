import os
import django
from collections import OrderedDict

# Set up Django environment
# NOTE: Ensure 'config.settings' and 'user_module.models' are correct for your project
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from user_module.models import Category, SubjectArea # Assuming these models exist

def create_initial_data():
    """
    Populates the database with an ordered list of categories and subject areas.
    """
    categories_and_subjects_ordered = OrderedDict([
        # --- ACADEMIC & EDUCATION NICHE ---
        ('IB Diploma', [
            'IB Mathematics', 'IB Physics', 'IB Chemistry',
            'IB Biology', 'IB History', 'IB Economics', 'IB Business Management',
            'IB Theory of Knowledge (TOK)', # Added
        ]),
        ('Humanities & Social Sciences', [
            'History', 'Philosophy', 'Sociology',
            'Psychology', 'Political Science', 'Linguistics',
            'Anthropology', 'Geography', # Added
        ]),
        ('Sciences', [
            'Physics (General)', 'Chemistry (General)', 'Biology (General)',
            'Environmental Science', 'Astronomy', 'Geology',
        ]),
        ('Academic Writing & Research', [ # Renamed from 'Research Projects'
            'Legal Papers', 'Thesis & Dissertation', 'Literature Review',
            'Statistical Data Analysis (Academic)', # Clarified
        ]),
        
        # --- WRITING & DESIGN NICHE ---
        ('Writing & Translation', [
            'Content Writing (SEO)', 'Copywriting', 'Creative Writing',
            'Technical Writing', 'Proofreading & Editing', 'Translation (General)',
            'Grant Writing', # Added
        ]),
        ('Arts & Design', [
            'Graphic Design', 'Photography', 'Video Production & Editing',
            'UI/UX Design', 'Animation', '3D Modeling', # Added
        ]),
        
        # --- TECH, DATA & ENGINEERING NICHE ---
        ('Technology & Programming', [
            'Web Development (Frontend)', 'Mobile App Development',
            'Backend Development (General)', 'Cybersecurity', 
            'Cloud Computing (AWS/Azure)', 'DevOps', # Added
        ]),
        ('Data & AI', [ # New Category
            'Data Science', 'Data Analysis (Business)', 'Machine Learning (ML)',
            'Artificial Intelligence (AI)', 'Business Intelligence (BI)',
        ]),
        ('Engineering & Architecture', [
            'Civil Engineering', 'Mechanical Engineering',
            'Electrical Engineering', 'Software Engineering',
            'Architecture & Design', 'CAD/BIM Modeling', # Added
        ]),

        # --- BUSINESS & FINANCE NICHE ---
        ('Business & Management', [
            'Business Strategy', 'Marketing & Advertising (General)', 
            'Project Management', 'Human Resources (HR)',
            'Sales & Lead Generation', # Added
        ]),
        ('Finance & Accounting', [ # New Category
            'Accounting', 'Bookkeeping', 'Financial Analysis',
            'Corporate Finance', 'Investment Management',
        ]),
    ])

    print("Creating categories and subject areas...")
    
    # 1. Fetch or Create Categories
    for category_name, subject_names in categories_and_subjects_ordered.items():
        category, created = Category.objects.get_or_create(name=category_name)
        print(f'   ✓ {"Created" if created else "Found"} category: {category_name}')

        # 2. Fetch or Create Subject Areas linked to the Category
        for subject_name in subject_names:
            subject, created = SubjectArea.objects.get_or_create(
                name=subject_name,
                category=category
            )
            print(f'     ✓ {"Created" if created else "Found"} subject: {subject_name}')

    print("\nInitial data creation complete! ✅")

if __name__ == '__main__':
    # Ensure you only run this once or when updating data. 
    # Use a check to prevent running if data already exists, or rely on get_or_create.
    create_initial_data()