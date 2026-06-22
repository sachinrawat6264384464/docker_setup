import os
import django
from django.db import connection
from django.apps import apps

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

def check_notifications():
    from django_tenants.utils import schema_context
    from tenants.models import Client

    print("Checking installed apps:")
    print("Is 'notifications' installed?", apps.is_installed('notifications'))
    
    with connection.cursor() as cursor:
        cursor.execute("SELECT schema_name FROM tenants_client")
        schemas = [row[0] for row in cursor.fetchall()]
    
    print("\nAll Schemas in DB:", schemas)
    
    # 1. Check in public schema
    with schema_context('public'):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema='public' AND table_name LIKE '%notification%'
            """)
            tables = [row[0] for row in cursor.fetchall()]
            print("\nPublic schema tables matching 'notification':", tables)
            
            if 'notifications_notification' in tables:
                cursor.execute("SELECT COUNT(*) FROM notifications_notification")
                print("Total notifications in public schema:", cursor.fetchone()[0])
            else:
                print("notifications_notification table NOT found in public schema!")

    # 2. Check in a tenant schema
    for tenant_schema in schemas:
        if tenant_schema == 'public':
            continue
        with schema_context(tenant_schema):
            with connection.cursor() as cursor:
                cursor.execute(f"""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema='{tenant_schema}' AND table_name LIKE '%notification%'
                """)
                tables = [row[0] for row in cursor.fetchall()]
                print(f"\nTenant schema '{tenant_schema}' tables matching 'notification':", tables)
                
                if 'notifications_notification' in tables:
                    cursor.execute("SELECT COUNT(*) FROM notifications_notification")
                    print(f"Total notifications in tenant schema '{tenant_schema}':", cursor.fetchone()[0])
                else:
                    print(f"notifications_notification table NOT found in tenant schema '{tenant_schema}'!")
        break # Just check the first tenant schema to see

if __name__ == "__main__":
    check_notifications()
