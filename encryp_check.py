# Cell: Diagnose the DOCX file format
from pathlib import Path

DOCX_PATH = Path("Behavioral_Specification.docx")

print(f"File:        {DOCX_PATH.resolve()}")
print(f"Exists:      {DOCX_PATH.exists()}")
print(f"Size:        {DOCX_PATH.stat().st_size:,} bytes")
print()

# Read first 16 bytes — the "magic number" tells us the real format
with open(DOCX_PATH, "rb") as f:
    magic = f.read(16)

print(f"First bytes (hex):   {magic.hex()}")
print(f"First bytes (ascii): {magic!r}")
print()

# Interpret the magic bytes
if magic[:4] == b"PK\x03\x04":
    print("✅ This IS a ZIP archive — should be a valid .docx")
    print("   If python-docx still fails, the ZIP internals are malformed,")
    print("   OR the ZIP wraps an MIP-encrypted payload (rare).")
elif magic[:4] == b"PK\x05\x06" or magic[:4] == b"PK\x07\x08":
    print("⚠️  ZIP archive but empty or spanned — unusual")
elif magic[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
    print("❌ OLE Compound Document format (D0 CF 11 E0)")
    print("   This is EITHER:")
    print("     (a) An old Word 97-2003 .doc file renamed to .docx, OR")
    print("     (b) A Microsoft Information Protection (MIP) encrypted file")
    print()
    print("   In both cases, python-docx cannot read it directly.")
    print("   FIX:")
    print("     - If MIP-protected: open in Word with company login,")
    print("       remove protection (File → Info → Protect → Stop Protection),")
    print("       then Save As a new .docx")
    print("     - If old .doc: open in Word, Save As → Word Document (.docx)")
elif magic.startswith(b"{\\rtf"):
    print("❌ This is an RTF file, not a Word document")
elif magic[:5] == b"<?xml":
    print("❌ This is plain XML, not a packaged Word document")
else:
    print("❌ Unknown format. First bytes don't match any known signature.")
    print(f"   Got bytes: {magic.hex()}")
    print("   File may be corrupted or encrypted with proprietary scheme.")
    print("   Try re-uploading from the original source.")