import requests
import time

BASE_URL = "http://127.0.0.1:8002"

def test_register():
    print("Testing registration...")
    username = f"testuser_{int(time.time())}"
    password = "testpassword123"
    
    response = requests.post(
        f"{BASE_URL}/auth/register",
        json={"username": username, "password": password}
    )
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    return username, password

def test_login(username, password):
    print("\nTesting login...")
    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={"username": username, "password": password}
    )
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    if response.status_code == 200:
        return response.json().get("access_token")
    return None

if __name__ == "__main__":
    try:
        u, p = test_register()
        token = test_login(u, p)
        if token:
            print("\nAuth test passed!")
        else:
            print("\nAuth test failed!")
    except Exception as e:
        print(f"\nError during test: {e}")
