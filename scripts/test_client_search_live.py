import urllib.request
import json

base_url = "http://localhost:8000"

def test_url(endpoint):
    url = f"{base_url}{endpoint}"
    print(f"\n--- Testing: {url} ---")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TestClient"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            print(f"Status: {resp.status}")
            print("Response:", json.dumps(data, indent=2, ensure_ascii=False)[:600])
            return data
    except Exception as e:
        print(f"Failed: {e}")
        return None

if __name__ == "__main__":
    test_url("/api/v1/policies/clients/search?q=LOCHMANN")
    test_url("/api/v1/policies/clients/search?q=CRECER")
    test_url("/api/v1/policies/clients/search?q=1017083029")
    test_url("/api/v1/policies/envelopes/by-client/LOCHMANN")
