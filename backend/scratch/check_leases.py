import psycopg2
import os
from dotenv import load_dotenv

# Load settings
load_dotenv('d:/mykhataproject/Hoa_US/backend/.env')

db_name = os.getenv('DB_NAME')
db_user = os.getenv('DB_USER')
db_password = os.getenv('DB_PASSWORD')
db_host = os.getenv('DB_HOST', 'localhost')
db_port = os.getenv('DB_PORT', '5432')

try:
    conn = psycopg2.connect(
        dbname=db_name,
        user=db_user,
        password=db_password,
        host=db_host,
        port=db_port
    )
    cursor = conn.cursor()
    
    schema = 'tenant_jhjhh'
    
    print(f"\n--- Checking Units in schema '{schema}' ---")
    cursor.execute(f"""
        SELECT u.id, u.unit_number, u.unit_type, u.status, u.is_occupied
        FROM {schema}.properties_unit u
    """)
    for row in cursor.fetchall():
        print(f"Unit ID: {row[0]}, Number: {row[1]}, Type: {row[2]}, Status: {row[3]}, Occupied: {row[4]}")
        
    print(f"\n--- Checking Leases in schema '{schema}' ---")
    cursor.execute(f"""
        SELECT l.id, l.unit_id, l.status, l.start_date, l.end_date, u.email, u.first_name, u.last_name
        FROM {schema}.properties_lease l
        JOIN {schema}.auth_user u ON l.tenant_id = u.id
    """)
    for row in cursor.fetchall():
        print(f"Lease ID: {row[0]}, Unit ID: {row[1]}, Status: {row[2]}, Tenant: {row[6]} {row[7]} ({row[5]})")
        
    conn.close()

except Exception as e:
    print("Error:", e)
