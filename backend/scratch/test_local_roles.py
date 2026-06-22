import urllib.request
import json

url = "http://127.0.0.1:8000/api/auth/available-roles/"

print("--- Request WITHOUT authorization header ---")
req = urllib.request.Request(
    url,
    headers={
        'X-Tenant': 'demo.localhost',
        'User-Agent': 'Mozilla/5.0'
    }
)
try:
    with urllib.request.urlopen(req) as response:
        print("Status:", response.status)
        data = response.read().decode('utf-8')
        print("Response:", json.dumps(json.loads(data), indent=2))
except Exception as e:
    print("Error:", e)

print("\n--- Request WITH invalid authorization header ---")
req = urllib.request.Request(
    url,
    headers={
        'X-Tenant': 'demo.localhost',
        'Authorization': 'Bearer invalid_or_expired_token',
        'User-Agent': 'Mozilla/5.0'
    }
)
try:
    with urllib.request.urlopen(req) as response:
        print("Status:", response.status)
        data = response.read().decode('utf-8')
        print("Response:", json.dumps(json.loads(data), indent=2))
except Exception as e:
    # If it is unauthorized, it will throw an HTTPError
    if hasattr(e, 'code'):
        print(f"HTTP Error: {e.code}")
        if hasattr(e, 'read'):
            print("Response:", e.read().decode('utf-8'))
    else:
        print("Error:", e)
