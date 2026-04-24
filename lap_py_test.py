import sys
print(f"Python: {sys.version}")
print(f"Exe:    {sys.executable}")
print()

checks = []

# Check 1 — pywin32 for COM automation
try:
    import win32com.client
    checks.append(("pywin32", True, None))
except ImportError as e:
    checks.append(("pywin32", False, str(e)))

# Check 2 — pydantic for schema serialization
try:
    import pydantic
    checks.append(("pydantic", True, pydantic.VERSION))
except ImportError as e:
    checks.append(("pydantic", False, str(e)))

# Check 3 — Word COM actually works (this is the big one)
try:
    import win32com.client
    word = win32com.client.Dispatch("Word.Application")
    version = word.Version
    word.Quit()
    checks.append(("Word COM", True, f"Word {version}"))
except Exception as e:
    checks.append(("Word COM", False, str(e)))

# Check 4 — python-docx is available for schema types
try:
    import docx
    checks.append(("python-docx", True, docx.__version__))
except ImportError as e:
    checks.append(("python-docx", False, str(e)))

# Report
print("Dependency check results:")
print("-" * 60)
all_ok = True
for name, ok, info in checks:
    marker = "[OK]  " if ok else "[FAIL]"
    print(f"  {marker}  {name:15s}  {info}")
    if not ok:
        all_ok = False

print()
if all_ok:
    print("✅ Laptop is ready for prepare_docx.py")
else:
    print("⚠️  Install missing packages with:")
    print("   pip install pywin32 pydantic python-docx")