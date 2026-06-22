import os
import sys
import django

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from website.models import ContactLead
from django_tenants.utils import schema_context

def seed():
    with schema_context('public'):
        # Clean existing leads if any, or keep them. Let's delete all to have a fresh state
        ContactLead.objects.all().delete()
        print("Cleared existing Contact Leads.")

        leads_data = [
            # status='new'
            {
                'name': 'John Doe',
                'email': 'john.doe@example.com',
                'phone': '+15550199',
                'company': 'Doe Properties LLC',
                'unit_count': 150,
                'message': 'Looking for a demo of the resident portal and billing feature.',
                'lead_type': 'demo',
                'status': 'new'
            },
            {
                'name': 'Jane Smith',
                'email': 'jane.smith@example.com',
                'phone': '+15550200',
                'company': 'Smith & Co',
                'unit_count': 45,
                'message': 'Interested in the basic plan for our HOA association.',
                'lead_type': 'contact',
                'status': 'new'
            },
            # status='contacted'
            {
                'name': 'Robert Johnson',
                'email': 'robert.j@example.com',
                'phone': '+15550201',
                'company': 'Apex Living',
                'unit_count': 500,
                'message': 'We have 500 units spread across 3 locations. Need multi-property management info.',
                'lead_type': 'enterprise',
                'status': 'contacted'
            },
            # status='qualified'
            {
                'name': 'Emily Davis',
                'email': 'emily.davis@example.com',
                'phone': '+15550202',
                'company': 'Greenwood HOA',
                'unit_count': 120,
                'message': 'Need integration details for existing Stripe accounts.',
                'lead_type': 'demo',
                'status': 'qualified'
            },
            # status='converted'
            {
                'name': 'Michael Brown',
                'email': 'michael.brown@example.com',
                'phone': '+15550203',
                'company': 'Lakeside Condos',
                'unit_count': 85,
                'message': 'Ready to sign up for the premium plan.',
                'lead_type': 'contact',
                'status': 'converted'
            },
            # status='lost'
            {
                'name': 'David Wilson',
                'email': 'david.wilson@example.com',
                'phone': '+15550204',
                'company': 'Sunset Villas',
                'unit_count': 30,
                'message': 'Looking for free options only.',
                'lead_type': 'contact',
                'status': 'lost'
            },
            # Duplicate email lead (to test duplicate detection/filtering)
            {
                'name': 'John Doe Duplicate',
                'email': 'john.doe@example.com',
                'phone': '+15550199',
                'company': 'Doe Properties LLC',
                'unit_count': 150,
                'message': 'Second submission from John Doe requesting urgency.',
                'lead_type': 'demo',
                'status': 'new'
            },
            # Extremely long message
            {
                'name': 'Alexander Great',
                'email': 'alexander.great@example.com',
                'phone': '+15550999',
                'company': 'Empire Realty Group',
                'unit_count': 1500,
                'message': 'Hello, we are interested in migrating our entire portfolio of 1500 units. ' * 30,
                'lead_type': 'enterprise',
                'status': 'new'
            }
        ]

        for data in leads_data:
            ContactLead.objects.create(**data)
        
        print(f"Successfully seeded {len(leads_data)} Contact Leads!")

if __name__ == '__main__':
    seed()
