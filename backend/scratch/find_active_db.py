import psycopg2

dbs = [
    'test_hoa_usa_prod',
    'hoa_connect_hub',
    'propflow_db',
    'property_saas',
    'hoaplatfrom',
    'mydatabase'
]

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
        cursor.execute("SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'django_migrations');")
        exists = cursor.fetchone()[0]
        if exists:
            # check schemas
            cursor.execute("SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'website_contactlead');")
            has_contact = cursor.fetchone()[0]
            print(f"Database '{db}': Has django_migrations={exists}, Has website_contactlead={has_contact}")
        else:
            print(f"Database '{db}': Connection success but no django_migrations table.")
        conn.close()
    except Exception as e:
        print(f"Database '{db}': Error: {e}")
