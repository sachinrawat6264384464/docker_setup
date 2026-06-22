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
    cursor.execute("SELECT schema_name FROM information_schema.schemata;")
    schemas = [row[0] for row in cursor.fetchall()]
    
    for schema in schemas:
        if schema in ['information_schema', 'pg_catalog', 'pg_toast']:
            continue
        try:
            cursor.execute(f'SELECT id, email, role, unit_number, building_name FROM "{schema}"."accounts_user" WHERE email = \'sdfsdf@gmail.com\';')
            users = cursor.fetchall()
            for u in users:
                print(f"Found in Schema '{schema}':")
                print(f"  ID: {u[0]}, Email: {u[1]}, Role: {u[2]}, Unit: {u[3]}, Building: {u[4]}")
                # Now print units in this schema
                cursor.execute(f'SELECT id, unit_number, unit_type, status, current_resident, building_id FROM "{schema}"."properties_unit";')
                units = cursor.fetchall()
                print("  Units in this schema:")
                for unit in units:
                    print(f"    - Unit ID: {unit[0]}, Number: {unit[1]}, Type: {unit[2]}, Status: {unit[3]}, Resident: {unit[4]}, Building ID: {unit[5]}")
                # Print building name
                cursor.execute(f'SELECT id, name FROM "{schema}"."properties_building";')
                blds = cursor.fetchall()
                print("  Buildings in this schema:")
                for b in blds:
                    print(f"    - Building ID: {b[0]}, Name: {b[1]}")
                # Print leases in this schema
                cursor.execute(f'SELECT id, tenant_id, unit_id, status FROM "{schema}"."properties_lease";')
                leases = cursor.fetchall()
                print("  Leases in this schema:")
                for lease in leases:
                    print(f"    - Lease ID: {lease[0]}, Tenant ID: {lease[1]}, Unit ID: {lease[2]}, Status: {lease[3]}")
        except Exception as e:
            pass
    conn.close()
except Exception as e:
    print(f"Error: {e}")
