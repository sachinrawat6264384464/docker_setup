import psycopg2

dbs = ['property_saas', 'propflow_db']

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
        cursor.execute("SELECT schema_name, domain_url FROM customers_client;")
        clients = cursor.fetchall()
        print(f"Database '{db}' Clients:")
        for client in clients:
            print(f"  - Schema: {client[0]}, Domain: {client[1]}")
        conn.close()
    except Exception as e:
        try:
            cursor.execute("SELECT schema_name FROM tenants_client;")
            clients = cursor.fetchall()
            print(f"Database '{db}' Clients (tenants_client):")
            for client in clients:
                print(f"  - Schema: {client[0]}")
            conn.close()
        except Exception as e2:
            print(f"Database '{db}' Error: {e} | {e2}")
