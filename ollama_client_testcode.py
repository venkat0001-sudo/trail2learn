# Cell: Test OllamaClient end-to-end
#
# This imports the client we just wrote and exercises every major method.
# If this cell runs without exceptions, we have a solid foundation.

from ollama_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaError,
)

# Step 1: Create a client and verify the server is reachable.
# The 'with' statement ensures the HTTP session is closed when we're done.
with OllamaClient() as client:
    print("Step 1: Verifying connection...")
    info = client.verify_connection()
    print(f"  ✅ Connected. {len(info.get('models', []))} models available.\n")

    # Step 2: Verify our target models are available.
    # If any of these fails, we'll get a helpful error telling us which
    # models ARE available, so we can choose substitutes.
    print("Step 2: Verifying required models...")
    for model_name in ["qwen3:32b", "qwen3-coder:30b", "glm-4.7-flash"]:
        try:
            model_info = client.verify_model(model_name)
            size_gb = model_info.get("size", 0) / (1024**3)
            print(f"  ✅ {model_name}  ({size_gb:.1f} GB)")
        except OllamaModelNotFoundError as e:
            print(f"  ❌ {model_name} NOT FOUND")
            print(f"     {str(e).splitlines()[0]}")
    print()

    # Step 3: Run a simple plain-text inference to confirm calls work.
    print("Step 3: Testing plain-text inference with qwen3:32b...")
    result = client.generate(
        prompt="Reply with exactly one word: HELLO",
        model="qwen3:32b",
        temperature=0.0,
        max_tokens=10,
    )
    print(f"  Response: {result.response_text.strip()}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    print(f"  Tokens:   {result.output_tokens} output\n")

    # Step 4: Run a structured JSON inference.
    # This is the critical test — does format_schema enforcement work?
    # We ask for a simple two-field JSON and verify it parses cleanly.
    print("Step 4: Testing structured JSON output...")
    test_schema = {
        "type": "object",
        "properties": {
            "greeting": {"type": "string"},
            "number":   {"type": "integer"},
        },
        "required": ["greeting", "number"],
    }

    parsed, result = client.generate_json(
        prompt="Return a JSON object with greeting='hello world' and number=42.",
        model="qwen3:32b",
        schema=test_schema,
        temperature=0.0,
    )
    print(f"  Parsed dict: {parsed}")
    print(f"  Duration:    {result.duration_seconds:.2f}s")
    print(f"  Type checks: greeting is {type(parsed['greeting']).__name__}, "
          f"number is {type(parsed['number']).__name__}")
    assert parsed["greeting"].lower() in ("hello world", "hello, world", "hello, world!")
    assert parsed["number"] == 42
    print(f"  ✅ Schema enforcement working correctly.\n")

print("🎉 All OllamaClient tests passed. Ready to build Stage 1.")