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

print(f"Connecting to database {db_name} at {db_host}:{db_port}...")

try:
    conn = psycopg2.connect(
        dbname=db_name,
        user=db_user,
        password=db_password,
        host=db_host,
        port=db_port
    )
    cursor = conn.cursor()
    
    # Get all schemas
    cursor.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT LIKE 'pg_%' AND schema_name != 'information_schema'")
    schemas = [row[0] for row in cursor.fetchall()]
    print("Found schemas:", schemas)
    
    # Check notifications table in all schemas
    for schema in schemas:
        cursor.execute(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = '{schema}' 
                AND table_name = 'notifications_notification'
            );
        """)
        exists = cursor.fetchone()[0]
        print(f"Schema '{schema}' has notifications_notification table? {exists}")
        
        if exists:
            cursor.execute(f"SELECT COUNT(*) FROM {schema}.notifications_notification")
            count = cursor.fetchone()[0]
            print(f"  Count of rows in '{schema}.notifications_notification': {count}")
            
            # Print a sample of rows
            cursor.execute(f"SELECT id, recipient_id, title, notification_type, created_at FROM {schema}.notifications_notification ORDER BY created_at DESC LIMIT 5")
            rows = cursor.fetchall()
            for r in rows:
                print(f"    Sample: {r}")
                
    conn.close()

except Exception as e:
    print("Error:", e)
