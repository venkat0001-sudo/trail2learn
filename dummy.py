import requests
import json

BASE_URL = "http://107.99.41.85/ollama/srv1"

print("=" * 70)
print("OLLAMA CONNECTIVITY TEST — via reverse proxy")
print("=" * 70)

# Test 1: List available models
print("\n[1] Checking available models...")
try:
    resp = requests.get(f"{BASE_URL}/api/tags", timeout=10)
    print(f"    HTTP {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        models = data.get("models", [])
        print(f"    📦 {len(models)} models found:")
        for m in models:
            name = m.get("name", "?")
            size_gb = m.get("size", 0) / (1024**3)
            family = m.get("details", {}).get("family", "?")
            print(f"       • {name:30s}  {size_gb:6.2f} GB  family={family}")
    else:
        print(f"    ❌ Unexpected status: {resp.text[:200]}")
except Exception as e:
    print(f"    ❌ Error: {e}")

# Test 2: Quick inference test with gpt-oss
#adding comment to test github commits
print("\n[2] Testing inference with gpt-oss (tiny prompt)...")
try:
    payload = {
        "model": "gpt-oss",
        "prompt": "Reply with exactly one word: ACK",
        "stream": False,
    }
    resp = requests.post(f"{BASE_URL}/api/generate", json=payload, timeout=60)
    if resp.status_code == 200:
        result = resp.json()
        print(f"    ✅ Response: {result.get('response', '')[:100]}")
        print(f"    ⏱️  Total duration: {result.get('total_duration', 0) / 1e9:.2f}s")
    else:
        print(f"    ❌ HTTP {resp.status_code}: {resp.text[:200]}")
except Exception as e:
    print(f"    ❌ Error: {e}")

# Test 3: Check if other servers exist (srv2, srv3...)
print("\n[3] Checking for additional Ollama instances...")
for srv_num in range(1, 5):
    url = f"http://107.99.41.85/ollama/srv{srv_num}/api/tags"
    try:
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            models = r.json().get("models", [])
            print(f"    ✅ srv{srv_num}: {len(models)} models")
    except:
        pass  # silent fail, just checking

print("\n" + "=" * 70)
print("Paste this output back to Claude")
print("=" * 70)
