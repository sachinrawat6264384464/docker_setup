import psycopg2

dbs = ['property_saas', 'propflow_db', 'hoaconnect_pass', 'test_hoa_usa_prod', 'hoaplatfrom', 'postgres']

for db in dbs:
    try:
        conn = psycopg2.connect(
            host="localhost",
            port="5433",
            user="postgres",
            password="sa626438",
            database=db
        )
        cursor = conn.cursor()
        
        # Check if public.tenants_client exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'tenants_client'
            );
        """)
        exists = cursor.fetchone()[0]
        if exists:
            cursor.execute("SELECT schema_name, name FROM public.tenants_client;")
            clients = cursor.fetchall()
            print(f"Database '{db}' has tenants_client:")
            for client in clients:
                print(f"  - Schema: {client[0]}, Name: {client[1]}")
        conn.close()
    except Exception as e:
        print(f"Database '{db}' error: {e}")
