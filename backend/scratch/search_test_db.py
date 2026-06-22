import psycopg2

try:
    conn = psycopg2.connect(
        host="localhost",
        port="5433",
        user="postgres",
        password="sa626438",
        database="test_hoa_usa_prod"
    )
    cursor = conn.cursor()
    cursor.execute("SELECT schema_name FROM information_schema.schemata;")
    schemas = [row[0] for row in cursor.fetchall()]
    print("Schemas in test_hoa_usa_prod:", schemas)
    
    for schema in schemas:
        if schema in ['information_schema', 'pg_catalog', 'pg_toast']:
            continue
        try:
            cursor.execute(f'SELECT id, email, role, unit_number, building_name FROM "{schema}"."accounts_user";')
            users = cursor.fetchall()
            for u in users:
                print(f"User in Schema '{schema}':")
                print(f"  ID: {u[0]}, Email: {u[1]}, Role: {u[2]}, Unit: {u[3]}, Building: {u[4]}")
        except Exception as e:
            pass
    conn.close()
except Exception as e:
    print(f"Error: {e}")
