import urllib.request
import urllib.error
import json

url = "http://localhost:8000/api/calendar-alerts/alerts/?month=4&year=2026&page_size=200"

req = urllib.request.Request(url)
# Add an auth header if needed, but since it's a 500 error we might get it even without auth 
# (if the 500 happens before auth or if auth is token based, we might get 401 instead)

try:
    response = urllib.request.urlopen(req)
    print("Success:", response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code}")
    body = e.read().decode('utf-8')
    print("Response body:")
    print(body)
except Exception as e:
    print(f"Error: {e}")
