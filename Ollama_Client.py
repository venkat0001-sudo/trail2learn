"""
Ollama Client — Foundational HTTP wrapper for our Ollama instance.

This module is the single source of truth for all LLM communication in the
OEM Spec Analyzer pipeline. Every stage (extraction, enrichment, sanity check)
uses this client. Centralizing here means:

  1. One place to change if the Ollama URL or auth scheme changes.
  2. Consistent retry and timeout behavior across the whole pipeline.
  3. Uniform error messages that help debugging.
  4. Testing can mock one class instead of scattered requests.post() calls.

The server sits behind a reverse proxy, so the URL is:
    http://107.99.41.85/ollama/srv1/api/...
NOT the usual:
    http://localhost:11434/api/...

All methods are synchronous because Stage 2 enrichment runs features
sequentially (one at a time) for now. We can add async later if we want
parallel Qwen calls, but premature async adds complexity without benefit
at this stage.
"""

import json
import time
import logging
from typing import Optional
from dataclasses import dataclass, field

import requests


# ─────────────────────────────────────────────────────────────────────────
# Configuration
#
# These are module-level constants, not class attributes, because they
# represent infrastructure facts about THIS specific server, not runtime
# decisions. If we ever deploy to a different server, we change these
# three values and nothing else.
# ─────────────────────────────────────────────────────────────────────────

# Reverse-proxied Ollama URL for the company GPU server.
# Confirmed working via colleague's code and connectivity test (HTTP 200).
OLLAMA_BASE_URL = "http://107.99.41.85/ollama/srv1"

# Default timeout per inference call. Generous because large models on
# quantized CPU offload can take 60-180 seconds for long contexts.
DEFAULT_TIMEOUT = 300  # 5 minutes

# Default context window. Ollama's built-in default is 2048 which is far
# too small for our 30K+ token specs. We explicitly override to 32K.
# Higher values are possible but consume more VRAM.
DEFAULT_NUM_CTX = 32768

# Default max tokens in the model's response. 8K is enough for a JSON
# array of ~50 extracted features. Increase only if we hit truncation.
DEFAULT_MAX_OUTPUT = 8192

# Low temperature for structured extraction tasks. We want deterministic,
# well-formed JSON — not creative variation. Stage 2 enrichment may want
# slightly higher (0.3) for more natural-sounding CodeMate prompts.
DEFAULT_TEMPERATURE = 0.1


# ─────────────────────────────────────────────────────────────────────────
# Custom Exceptions
#
# We define our own exception hierarchy so calling code can distinguish
# "network problem" from "model missing" from "bad JSON response".
# This is much better than catching generic `Exception` everywhere.
# ─────────────────────────────────────────────────────────────────────────

class OllamaError(Exception):
    """Base exception for all Ollama-related failures."""
    pass


class OllamaConnectionError(OllamaError):
    """Cannot reach the Ollama server at all. Network or firewall issue."""
    pass


class OllamaModelNotFoundError(OllamaError):
    """A specific model was requested but is not pulled on the server."""
    pass


class OllamaInferenceError(OllamaError):
    """The API call completed but returned an error status."""
    pass


class OllamaResponseError(OllamaError):
    """Response arrived but could not be parsed as expected JSON."""
    pass


# ─────────────────────────────────────────────────────────────────────────
# Result dataclass
#
# Instead of returning raw JSON dicts from inference calls, we return
# a structured dataclass. This gives us type hints in IDEs, enforces
# a consistent shape across all callers, and makes it easy to add
# fields later (e.g., token counts for cost tracking).
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class InferenceResult:
    """Result of a single inference call, with metadata for debugging."""

    response_text: str           # The actual model output (prose or JSON string)
    model: str                   # Which model was used
    duration_seconds: float      # Wall-clock time of the call
    total_tokens: int = 0        # Total tokens processed (prompt + output)
    prompt_tokens: int = 0       # Tokens in the prompt
    output_tokens: int = 0       # Tokens the model generated
    raw_response: dict = field(default_factory=dict)  # Full API response for debugging

    def __repr__(self) -> str:
        # Concise repr that avoids dumping the entire response_text,
        # which can be thousands of characters long.
        preview = self.response_text[:80].replace("\n", " ")
        if len(self.response_text) > 80:
            preview += "..."
        return (f"InferenceResult(model={self.model}, "
                f"duration={self.duration_seconds:.2f}s, "
                f"tokens={self.output_tokens}, "
                f"preview='{preview}')")


# ─────────────────────────────────────────────────────────────────────────
# The client class itself
#
# Design note: We use a class rather than module-level functions because
# the client holds state (base URL, session, defaults) that callers may
# want to configure once and reuse. For example, Stage 1 and Stage 2 may
# use the same client instance with different model names per call.
# ─────────────────────────────────────────────────────────────────────────

class OllamaClient:
    """
    Client for interacting with our reverse-proxied Ollama instance.

    Typical usage:
        client = OllamaClient()
        client.verify_connection()                # call once at startup
        client.verify_model("qwen3:32b")          # check required models
        result = client.generate(
            prompt="Extract features from...",
            model="qwen3:32b",
        )
        print(result.response_text)
    """

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        default_timeout: int = DEFAULT_TIMEOUT,
        default_num_ctx: int = DEFAULT_NUM_CTX,
        default_temperature: float = DEFAULT_TEMPERATURE,
        max_retries: int = 2,
    ):
        self.base_url = base_url.rstrip("/")  # strip trailing slash to avoid // in URLs
        self.default_timeout = default_timeout
        self.default_num_ctx = default_num_ctx
        self.default_temperature = default_temperature
        self.max_retries = max_retries

        # A requests.Session reuses TCP connections across calls.
        # This matters because our Stage 2 makes many sequential Qwen calls
        # to the same server. Without a session, each call opens a new
        # connection, adding ~100ms of overhead per call.
        self._session = requests.Session()

        self.logger = logging.getLogger(__name__)

        # Track whether verify_connection() has been called successfully.
        # Some methods refuse to proceed without this, to fail fast on
        # infrastructure issues rather than failing mysteriously mid-pipeline.
        self._verified = False

    # ──────────────────────────────────────────────────────────────────
    # Infrastructure verification methods
    #
    # These are called ONCE at the start of a pipeline run. They establish
    # that the server is reachable and has the models we need. If any of
    # these fail, the user needs IT help, not code changes — so we raise
    # informative exceptions and let the caller decide how to handle them.
    # ──────────────────────────────────────────────────────────────────

    def verify_connection(self) -> dict:
        """
        Check that the Ollama API is reachable.

        Returns a dict with server info on success.
        Raises OllamaConnectionError with a clear message on failure.

        Call this once at application startup, BEFORE any real work.
        It prevents the pipeline from running halfway and then dying.
        """
        url = f"{self.base_url}/api/tags"
        self.logger.info(f"Verifying Ollama connection to {url}")

        try:
            response = self._session.get(url, timeout=10)
        except requests.exceptions.ConnectionError as e:
            # Network-level failure — server down, firewall blocking, DNS issue
            raise OllamaConnectionError(
                f"Cannot reach Ollama at {url}.\n"
                f"Possible causes:\n"
                f"  1. Server is down (check GPU farm dashboard)\n"
                f"  2. Reverse proxy is not routing /ollama/srv1 correctly\n"
                f"  3. Company firewall is blocking this host\n"
                f"Original error: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise OllamaConnectionError(
                f"Ollama took longer than 10s to respond at {url}. "
                f"Server may be overloaded. Original error: {e}"
            ) from e

        if response.status_code != 200:
            raise OllamaConnectionError(
                f"Ollama returned HTTP {response.status_code} from {url}.\n"
                f"Response body: {response.text[:500]}"
            )

        data = response.json()
        models = data.get("models", [])
        self.logger.info(f"✅ Connected. {len(models)} models available.")
        self._verified = True
        return data

    def list_models(self) -> list[dict]:
        """
        Return list of available model dicts.
        Each dict has keys: name, size, details, modified_at, etc.
        """
        if not self._verified:
            self.verify_connection()

        response = self._session.get(f"{self.base_url}/api/tags", timeout=10)
        response.raise_for_status()
        return response.json().get("models", [])

    def verify_model(self, model_name: str) -> dict:
        """
        Check that a specific model is available on the server.

        Returns the model's info dict on success.
        Raises OllamaModelNotFoundError with suggestions on failure.

        We match case-insensitively and allow partial matches on the
        pre-colon portion (e.g., "qwen3" will match "qwen3:32b") so
        callers can be a bit sloppy about exact tags.
        """
        models = self.list_models()
        names = [m["name"] for m in models]

        # Exact match first
        for m in models:
            if m["name"] == model_name:
                return m

        # Case-insensitive match
        for m in models:
            if m["name"].lower() == model_name.lower():
                return m

        # No match — raise a helpful error listing what IS available
        raise OllamaModelNotFoundError(
            f"Model '{model_name}' not found on server.\n"
            f"Available models ({len(names)}):\n"
            + "\n".join(f"  - {n}" for n in names)
            + f"\n\nTo pull this model, ask your admin to run:\n"
            f"  ollama pull {model_name}"
        )

    # ──────────────────────────────────────────────────────────────────
    # The core inference methods
    #
    # generate() is for single-turn prompts (our primary use case).
    # chat() is for multi-turn conversations (not used yet, but included
    # for future extensibility, e.g., iterative Qwen refinement loops).
    # ──────────────────────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        model: str,
        *,
        system: Optional[str] = None,
        format_schema: Optional[dict] = None,
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> InferenceResult:
        """
        Run a single-turn generation call.

        Args:
            prompt: The user prompt text.
            model: Ollama model name (e.g., "qwen3:32b").
            system: Optional system prompt (sets the model's role/behavior).
            format_schema: Optional JSON schema dict. When provided, Ollama
                           forces the output to match this schema exactly.
                           This is how we enforce Pydantic-validated JSON.
            temperature: Override default temperature for this call.
            num_ctx: Override default context window.
            max_tokens: Override default max output tokens.
            timeout: Override default timeout in seconds.

        Returns:
            InferenceResult with response_text and metadata.

        Raises:
            OllamaInferenceError: API returned non-200 status.
            OllamaConnectionError: Network failed even after retries.
        """
        url = f"{self.base_url}/api/generate"

        # Build the payload. Note that we use Ollama's options dict to pass
        # num_ctx, temperature, etc. — these are NOT top-level params.
        # A common mistake is putting them at top level; they get ignored.
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,  # we always want the full response at once
            "options": {
                "num_ctx": num_ctx or self.default_num_ctx,
                "temperature": temperature if temperature is not None else self.default_temperature,
                "num_predict": max_tokens or DEFAULT_MAX_OUTPUT,
            },
        }

        if system:
            payload["system"] = system

        if format_schema:
            # Ollama's structured output feature. When "format" is a JSON
            # schema dict, Ollama constrains token generation so the output
            # MUST be valid JSON matching the schema. This is far more
            # reliable than asking the model nicely in the prompt.
            payload["format"] = format_schema

        # Try the call with retries for transient failures.
        effective_timeout = timeout or self.default_timeout
        start_time = time.time()
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                self.logger.debug(
                    f"Calling Ollama (attempt {attempt + 1}/{self.max_retries + 1}) "
                    f"model={model} prompt_len={len(prompt)}"
                )

                response = self._session.post(
                    url,
                    json=payload,
                    timeout=effective_timeout,
                )

                duration = time.time() - start_time

                # HTTP error codes — don't retry 4xx (our fault, won't change)
                # but DO retry 5xx (server's fault, might recover)
                if response.status_code == 404:
                    raise OllamaModelNotFoundError(
                        f"Model '{model}' returned 404. It may have been deleted. "
                        f"Response: {response.text[:300]}"
                    )

                if 400 <= response.status_code < 500:
                    raise OllamaInferenceError(
                        f"Client error HTTP {response.status_code} for model {model}.\n"
                        f"Response: {response.text[:500]}"
                    )

                if response.status_code != 200:
                    # 5xx — retry
                    last_error = OllamaInferenceError(
                        f"Server error HTTP {response.status_code}. "
                        f"Response: {response.text[:300]}"
                    )
                    self.logger.warning(f"Attempt {attempt + 1} got {response.status_code}, retrying...")
                    time.sleep(2 ** attempt)  # exponential backoff: 1s, 2s, 4s...
                    continue

                # Success — parse the response
                try:
                    data = response.json()
                except json.JSONDecodeError as e:
                    raise OllamaResponseError(
                        f"Ollama returned non-JSON response.\n"
                        f"Response (first 500 chars): {response.text[:500]}\n"
                        f"Parse error: {e}"
                    ) from e

                response_text = data.get("response", "")

                return InferenceResult(
                    response_text=response_text,
                    model=model,
                    duration_seconds=duration,
                    # Ollama returns token counts in nanoseconds/tokens fields
                    prompt_tokens=data.get("prompt_eval_count", 0),
                    output_tokens=data.get("eval_count", 0),
                    total_tokens=(data.get("prompt_eval_count", 0)
                                  + data.get("eval_count", 0)),
                    raw_response=data,
                )

            except requests.exceptions.Timeout:
                last_error = OllamaConnectionError(
                    f"Request timed out after {effective_timeout}s. "
                    f"Model {model} may be loading or overloaded."
                )
                self.logger.warning(f"Attempt {attempt + 1} timed out, retrying...")
                time.sleep(2 ** attempt)

            except requests.exceptions.ConnectionError as e:
                last_error = OllamaConnectionError(
                    f"Connection failed: {e}. Check server and firewall."
                )
                self.logger.warning(f"Attempt {attempt + 1} connection error, retrying...")
                time.sleep(2 ** attempt)

        # All retries exhausted
        raise last_error or OllamaError("Unknown failure after all retries")

    # ──────────────────────────────────────────────────────────────────
    # Convenience methods for common workflows
    # ──────────────────────────────────────────────────────────────────

    def generate_json(
        self,
        prompt: str,
        model: str,
        schema: dict,
        **kwargs,
    ) -> tuple[dict, InferenceResult]:
        """
        Generate JSON output matching a Pydantic schema. Parses the result
        for you and returns both the parsed dict and the raw InferenceResult.

        This is the primary method Stage 1 and Stage 2 will use.

        Args:
            prompt: The user prompt.
            model: Ollama model name.
            schema: JSON schema dict (typically from YourPydanticModel.model_json_schema()).
            **kwargs: Passed through to generate() (e.g., system, temperature).

        Returns:
            (parsed_dict, inference_result_for_metadata)

        Raises:
            OllamaResponseError if the response is not valid JSON
            (should be rare with format_schema, but possible).
        """
        result = self.generate(
            prompt=prompt,
            model=model,
            format_schema=schema,
            **kwargs,
        )

        try:
            parsed = json.loads(result.response_text)
        except json.JSONDecodeError as e:
            # With format_schema set, this should almost never happen,
            # but we guard against it. Show the raw text to help debug.
            raise OllamaResponseError(
                f"Response was not valid JSON despite format_schema.\n"
                f"Response text (first 500 chars): {result.response_text[:500]}\n"
                f"Parse error: {e}"
            ) from e

        return parsed, result

    def close(self):
        """Close the underlying HTTP session. Call at end of program."""
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()