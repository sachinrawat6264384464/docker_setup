import time
import psycopg2
import os

print("Waiting for database...")
db_name = os.environ.get('DB_NAME', 'mydatabasess')
db_user = os.environ.get('DB_USER', 'postgres')
db_password = os.environ.get('DB_PASSWORD', '')
db_host = os.environ.get('DB_HOST', 'db')
db_port = os.environ.get('DB_PORT', '5432')

while True:
    try:
        conn = psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port
        )
        conn.close()
        print("Database ready!")
        break
    except psycopg2.OperationalError as e:
        print(f"Database unavailable, waiting 1 second... ({e})")
        time.sleep(1)
