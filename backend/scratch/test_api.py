import requests
try:
    r = requests.get('http://localhost:8000/api/location/states/?search=J')
    print(f"Status: {r.status_code}")
    print(f"Count: {r.json().get('count', 0)}")
    print(f"Results: {[s['name'] for s in r.json().get('results', [])]}")
except Exception as e:
    print(f"Error: {e}")
