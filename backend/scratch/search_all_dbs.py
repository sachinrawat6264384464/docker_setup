import psycopg2

databases = [
    "postgres",
    "property_saas",
    "hoaplatfrom",
    "hoaconnect_pass",
    "test_hoa_usa_prod",
    "mydatabase",
    "aapka_naya_db_name",
    "school_erp"
]

for db in databases:
    try:
        conn = psycopg2.connect(
            host="localhost",
            port="5433",
            user="postgres",
            password="sa626438",
            database=db
        )
        cursor = conn.cursor()
        cursor.execute("SELECT schema_name FROM information_schema.schemata;")
        schemas = [row[0] for row in cursor.fetchall()]
        
        for schema in schemas:
            if schema in ['information_schema', 'pg_catalog', 'pg_toast']:
                continue
            try:
                cursor.execute(f'SELECT id, email, role, unit_number, building_name FROM "{schema}"."accounts_user";')
                users = cursor.fetchall()
                for u in users:
                    if 'sdfsdf' in str(u[1]).lower():
                        print(f"Match found in DB: '{db}', Schema: '{schema}':")
                        print(f"  ID: {u[0]}, Email: {u[1]}, Role: {u[2]}, Unit: {u[3]}, Building: {u[4]}")
            except Exception:
                pass
        conn.close()
    except Exception as e:
        pass
