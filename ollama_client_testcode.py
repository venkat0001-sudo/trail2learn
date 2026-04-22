# Cell: Test OllamaClient with memory-safe config
from ollama_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaError,
)

# Memory-safe model choices based on 32GB VRAM budget on RTX 5090
# (remember: ~5 GB already consumed by other processes per dashboard)
STAGE1_MODEL = "mistral-small3.2:latest"   # 14.1 GB — fits with room
STAGE2_MODEL = "qwen3-coder:30b"           # 17.3 GB — fits, loads after Stage 1
TEST_CTX     = 8192                         # small for test; production will tune up

with OllamaClient() as client:
    # Step 1: Connection
    print("Step 1: Verifying connection...")
    info = client.verify_connection()
    print(f"  ✅ Connected. {len(info.get('models', []))} models available.\n")

    # Step 2: Verify selected models
    print("Step 2: Verifying required models...")
    for model_name in [STAGE1_MODEL, STAGE2_MODEL]:
        try:
            m_info = client.verify_model(model_name)
            size_gb = m_info.get("size", 0) / (1024**3)
            print(f"  ✅ {model_name:35s} ({size_gb:.1f} GB)")
        except OllamaModelNotFoundError as e:
            print(f"  ❌ {model_name} NOT FOUND")
            print(f"     {str(e).splitlines()[0]}")
    print()

    # Step 3: Plain-text inference with Mistral
    print(f"Step 3: Plain-text inference with {STAGE1_MODEL}...")
    try:
        result = client.generate(
            prompt="Reply with exactly one word: HELLO",
            model=STAGE1_MODEL,
            temperature=0.0,
            max_tokens=10,
            num_ctx=TEST_CTX,
        )
        print(f"  Response: {result.response_text.strip()!r}")
        print(f"  Duration: {result.duration_seconds:.2f}s")
        print(f"  Tokens:   {result.output_tokens} output")
        print(f"  ✅ Inference working.\n")
    except OllamaError as e:
        print(f"  ❌ FAILED: {type(e).__name__}")
        print(f"     {str(e)[:400]}\n")
        raise

    # Step 4: Structured JSON output
    print(f"Step 4: Structured JSON with {STAGE1_MODEL}...")
    test_schema = {
        "type": "object",
        "properties": {
            "greeting": {"type": "string"},
            "number":   {"type": "integer"},
        },
        "required": ["greeting", "number"],
    }

    try:
        parsed, result = client.generate_json(
            prompt="Return a JSON object with greeting='hello world' and number=42.",
            model=STAGE1_MODEL,
            schema=test_schema,
            temperature=0.0,
            max_tokens=100,
            num_ctx=TEST_CTX,
        )
        print(f"  Parsed:   {parsed}")
        print(f"  Duration: {result.duration_seconds:.2f}s")
        assert isinstance(parsed.get("greeting"), str), "greeting should be string"
        assert isinstance(parsed.get("number"), int), "number should be integer"
        assert parsed["number"] == 42, f"expected 42, got {parsed['number']}"
        print(f"  ✅ Schema enforcement working.\n")
    except OllamaError as e:
        print(f"  ❌ FAILED: {type(e).__name__}")
        print(f"     {str(e)[:400]}\n")
        raise

    # Step 5: Test Stage 2 model briefly
    print(f"Step 5: Quick test of {STAGE2_MODEL}...")
    try:
        result = client.generate(
            prompt="Write exactly: int main() { return 0; }",
            model=STAGE2_MODEL,
            temperature=0.0,
            max_tokens=30,
            num_ctx=TEST_CTX,
        )
        print(f"  Response: {result.response_text.strip()[:80]}")
        print(f"  Duration: {result.duration_seconds:.2f}s")
        print(f"  ✅ Stage 2 model working.\n")
    except OllamaError as e:
        print(f"  ❌ FAILED: {type(e).__name__}")
        print(f"     {str(e)[:400]}\n")

print("🎉 All tests passed. Safe to proceed to Stage 1 build.")