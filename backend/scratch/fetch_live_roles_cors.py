import urllib.request
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

url = "https://demo.hoaconnecthub.com/api/auth/available-roles/"
req = urllib.request.Request(
    url, 
    headers={
        'X-Tenant': 'demo.hoaconnecthub.com',
        'Origin': 'https://demo.hoaconnecthub.com',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    }
)

try:
    with urllib.request.urlopen(req, context=ctx) as response:
        print("Status:", response.status)
        print("Headers:")
        for name, value in response.headers.items():
            print(f"  {name}: {value}")
        data = response.read().decode('utf-8')
        print("Response:")
        try:
            print(json.dumps(json.loads(data), indent=2))
        except:
            print(data)
except Exception as e:
    print("Error:", e)
