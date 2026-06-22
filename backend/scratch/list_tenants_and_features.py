import psycopg2

try:
    conn = psycopg2.connect(
        host="localhost",
        port="5433",
        user="postgres",
        password="sa626438",
        database="property_saas"
    )
    cursor = conn.cursor()
    
    # List clients/tenants
    cursor.execute("SELECT schema_name, name FROM public.tenants_client;")
    clients = cursor.fetchall()
    print("Clients:")
    for client in clients:
        print(f"- Schema: {client[0]}, Name: {client[1]}")
        # Fetch columns of tenants_tenantfeature
        try:
            conn.commit() # Clear transaction
            cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_schema = '{client[0]}' AND table_name = 'tenants_tenantfeature';")
            cols = [r[0] for r in cursor.fetchall()]
            print(f"  Columns: {cols}")
            if cols:
                cursor.execute(f"SELECT * FROM \"{client[0]}\".\"tenants_tenantfeature\" LIMIT 5;")
                rows = cursor.fetchall()
                for row in rows:
                    print(f"    - Row: {row}")
        except Exception as e:
            print(f"  Error fetching columns/rows: {e}")
            
    conn.close()
except Exception as e:
    print(f"Error: {e}")
