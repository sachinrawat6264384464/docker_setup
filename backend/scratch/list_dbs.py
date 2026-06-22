import psycopg2

try:
    conn = psycopg2.connect(
        host="localhost",
        port="5433",
        user="postgres",
        password="sa626438",
        database="postgres"
    )
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute("SELECT datname FROM pg_database;")
    dbs = cursor.fetchall()
    print("Databases on 5433 with password sa626438:")
    for db in dbs:
        print(f"  - {db[0]}")
    conn.close()
except Exception as e:
    print(f"Error on 5433/sa626438: {e}")

try:
    conn = psycopg2.connect(
        host="localhost",
        port="5433",
        user="postgres",
        password="rdcv4c75",
        database="postgres"
    )
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute("SELECT datname FROM pg_database;")
    dbs = cursor.fetchall()
    print("Databases on 5433 with password rdcv4c75:")
    for db in dbs:
        print(f"  - {db[0]}")
    conn.close()
except Exception as e:
    print(f"Error on 5433/rdcv4c75: {e}")
