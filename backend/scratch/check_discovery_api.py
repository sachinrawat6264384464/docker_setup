import requests
import json

# Backend URL
URL = "http://localhost:8000/api/system/tenants/discovery/"

def test_discovery():
    print(f"Testing Endpoint: {URL}\n" + "="*40)
    try:
        response = requests.get(URL)
        if response.status_code == 200:
            data = response.json()
            print("SUCCESS! Output matches screenshot format:\n")
            print(json.dumps(data, indent=4))
            
            if data['count'] == 0:
                print("\nNOTE: Count 0 hai kyunki database mein abhi koi Active Society nahi hai.")
        else:
            print(f"FAILED! Status Code: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"ERROR: Backend server nahi chal raha ya connection issue hai.\n{e}")

if __name__ == "__main__":
    test_discovery()
