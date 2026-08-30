import requests
import os

KNOWLEDGE_URL = "http://127.0.0.1:8001"

def test_upload():
    print("Testing knowledge upload...")
    test_file = "test_doc.md"
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("# Test Document\nThis is a test document about TRAE AI assistant.\nIt supports multi-agent systems.")
    
    with open(test_file, "rb") as f:
        response = requests.post(
            f"{KNOWLEDGE_URL}/upload",
            files={"file": (test_file, f, "text/markdown")}
        )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    os.remove(test_file)
    return response.status_code == 200

def test_query():
    print("\nTesting knowledge query...")
    response = requests.post(
        f"{KNOWLEDGE_URL}/query",
        json={"question": "What does TRAE AI assistant support?"}
    )
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    return response.status_code == 200

if __name__ == "__main__":
    try:
        if test_upload():
            # Wait a bit for background processing
            import time
            print("Waiting for indexing...")
            time.sleep(5)
            test_query()
        else:
            print("Upload failed, skipping query test.")
    except Exception as e:
        print(f"\nError during test: {e}")
