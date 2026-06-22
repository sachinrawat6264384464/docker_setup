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
    
    print("\n--- Listing Recent Units across all Schemas ---")
    for schema in schemas:
        # Check if properties_unit table exists in this schema
        cursor.execute(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = '{schema}' 
                AND table_name = 'properties_unit'
            );
        """)
        exists = cursor.fetchone()[0]
        if exists:
            cursor.execute(f"""
                SELECT u.id, u.unit_number, u.block, u.floor, u.unit_type, u.created_at, b.name
                FROM {schema}.properties_unit u
                JOIN {schema}.properties_building b ON u.building_id = b.id
                ORDER BY u.created_at DESC LIMIT 5
            """)
            units = cursor.fetchall()
            if units:
                print(f"\nSchema '{schema}':")
                for u in units:
                    print(f"  Unit: {u[1]}, Block: {u[2]}, Floor: {u[3]}, Type: {u[4]}, Created: {u[5]}, Building: {u[6]}")
            else:
                print(f"Schema '{schema}': No units found.")
        else:
            print(f"Schema '{schema}': No properties_unit table.")
            
    conn.close()

except Exception as e:
    print("Error:", e)
