"""
NASCA Roundtrip Verifier.

Run this on the GPU server after uploading `nasca_test.json` from your
company laptop. It checks every way a DRM system could have corrupted
the file during the trip, and reports exactly what it finds.

Usage:
    1. Place `nasca_test.json` somewhere on your company laptop
    2. Upload it to the GPU server via Jupyter's file uploader
       (or via your normal upload route)
    3. In a Jupyter cell:
           exec(open("render_nasca_test.py").read())
"""

import json
import hashlib
from pathlib import Path


# Expected values computed from the ORIGINAL nasca_test.json before upload.
# These are the ground truth. If the file on the GPU server produces
# different values, something changed during upload.
EXPECTED = {
    "total_entries":       3,
    "tool_name":           "nasca_test",
    "korean_text":         "기획 요청 (planning request)",
    "emoji_text":          "✅ ❌ 🎉 📄",
    "symbol_text":         "≥ ± ° μ Ω §",
    "first_topic":         "4.8.3 SCP Feature Enable/Disable",
    "weight_cell_snippet": "기획 요청: request change",
}


def verify(file_path: str = "nasca_test.json") -> bool:
    """Run all checks. Returns True if the file survived intact, False otherwise."""

    path = Path(file_path)
    print("=" * 70)
    print("  NASCA ROUNDTRIP VERIFIER")
    print("=" * 70)

    # ── Check 1: File exists ──────────────────────────────────────────────
    if not path.exists():
        print(f"\n[FAIL] File not found: {path.resolve()}")
        print("       Upload nasca_test.json to the current directory first.")
        return False
    print(f"\n[OK] File found: {path.resolve()}")
    print(f"     Size: {path.stat().st_size:,} bytes")

    # ── Check 2: First bytes — is this still a JSON file? ─────────────────
    # A legit JSON file starts with '{' or '[' (optionally after a BOM).
    # A NASCA-wrapped file would start with '<## NASCA DRM FI'.
    with open(path, "rb") as f:
        raw = f.read(64)

    print(f"\n[INFO] First 32 bytes (hex):   {raw[:32].hex()}")
    print(f"[INFO] First 32 bytes (ascii): {raw[:32]!r}")

    if raw[:16] == b"<## NASCA DRM FI":
        print("\n[FAIL] File was re-encrypted by NASCA during upload!")
        print("       This means even .json files go through the DRM layer.")
        print("       We need a different strategy (not plain JSON).")
        return False

    # Strip UTF-8 BOM if present (not an error, just note it)
    text_start = raw[3:7] if raw[:3] == b"\xef\xbb\xbf" else raw[:4]
    if raw[:3] == b"\xef\xbb\xbf":
        print("[INFO] UTF-8 BOM detected (harmless, json.loads handles it)")

    if not (b"{" in text_start or b"[" in text_start):
        print(f"\n[FAIL] File does not look like JSON. First chars: {text_start!r}")
        return False
    print("[OK] File begins with JSON content — no DRM wrapper")

    # ── Check 3: Parses as valid JSON ─────────────────────────────────────
    try:
        text = path.read_text(encoding="utf-8-sig")  # -sig strips BOM if present
        data = json.loads(text)
        print("\n[OK] Parses as valid JSON")
    except Exception as e:
        print(f"\n[FAIL] JSON parse failed: {e}")
        print(f"       First 200 chars of file content: {path.read_text()[:200]!r}")
        return False

    # ── Check 4: Expected top-level structure ─────────────────────────────
    required_keys = {"metadata", "entries", "special_chars_test"}
    missing = required_keys - set(data.keys())
    if missing:
        print(f"\n[FAIL] Missing top-level keys: {missing}")
        return False
    print(f"[OK] All required top-level keys present: {sorted(data.keys())}")

    # ── Check 5: Metadata content preserved ───────────────────────────────
    meta = data["metadata"]
    if meta.get("total_entries") != EXPECTED["total_entries"]:
        print(f"\n[FAIL] total_entries mismatch: "
              f"got {meta.get('total_entries')}, expected {EXPECTED['total_entries']}")
        return False
    if meta.get("tool_name") != EXPECTED["tool_name"]:
        print(f"\n[FAIL] tool_name mismatch: got {meta.get('tool_name')!r}")
        return False
    print("[OK] Metadata values intact")

    # ── Check 6: Unicode roundtrip (the critical one) ─────────────────────
    # If DRM or the transport layer did character encoding conversion,
    # Korean text and emojis are where it shows up.
    special = data["special_chars_test"]
    issues = []

    if special.get("korean") != EXPECTED["korean_text"]:
        issues.append(f"Korean text changed: got {special.get('korean')!r}")
    if special.get("emojis") != EXPECTED["emoji_text"]:
        issues.append(f"Emoji text changed: got {special.get('emojis')!r}")
    if special.get("symbols") != EXPECTED["symbol_text"]:
        issues.append(f"Symbol text changed: got {special.get('symbols')!r}")

    if issues:
        print("\n[FAIL] Unicode corruption detected:")
        for issue in issues:
            print(f"       - {issue}")
        return False
    print("[OK] Unicode (Korean, emoji, symbols) intact")

    # ── Check 7: Entries list — structure and content ─────────────────────
    entries = data["entries"]
    if len(entries) != EXPECTED["total_entries"]:
        print(f"\n[FAIL] Wrong number of entries: got {len(entries)}, "
              f"expected {EXPECTED['total_entries']}")
        return False

    first = entries[0]
    if first.get("topic") != EXPECTED["first_topic"]:
        print(f"\n[FAIL] First entry topic corrupted: got {first.get('topic')!r}")
        return False

    # Nested key object preserved?
    if first.get("key", {}).get("origin") != "section":
        print(f"\n[FAIL] Nested key.origin not preserved: {first.get('key')}")
        return False
    if first.get("key", {}).get("section") != "4.8.3":
        print(f"\n[FAIL] Nested key.section not preserved: {first.get('key')}")
        return False
    print("[OK] Entry list structure and nested objects intact")

    # ── Check 8: Korean in entry cell_text ────────────────────────────────
    weight_entry = next((e for e in entries if e.get("topic") == "Weight"), None)
    if not weight_entry:
        print("\n[FAIL] Weight entry missing")
        return False
    cell_text = weight_entry.get("cell_text") or ""
    if EXPECTED["weight_cell_snippet"] not in cell_text:
        print(f"\n[FAIL] Korean in cell_text corrupted:")
        print(f"       Got: {cell_text!r}")
        return False
    print("[OK] Korean text inside entry cell_text intact")

    # ── Check 9: Show a content digest for confirmation ───────────────────
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f"\n[INFO] SHA-256 of file on GPU server: {digest}")
    print("        (tell the laptop side to compute the same — if digests match,")
    print("         the file is byte-for-byte identical to what you uploaded)")

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  SUCCESS — .json survived the NASCA-laptop-to-GPU trip intact")
    print("=" * 70)
    print("\n  Safe to proceed with prepare_docx.py on the laptop side.")
    print()
    return True


# Run immediately when this script is exec'd in a Jupyter cell.
verify()
