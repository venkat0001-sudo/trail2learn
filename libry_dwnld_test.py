# Cell: Install required packages into the running kernel
#
# We use sys.executable to ensure we install into the SAME Python that
# Jupyter is using. A bare `pip install` from a terminal might install
# into a different Python and Jupyter would still complain "module not found".

import sys

print(f"Installing into: {sys.executable}\n")

!{sys.executable} -m pip install --quiet python-docx pydantic openpyxl thefuzz python-Levenshtein requests

print("\n✅ Done. Verify with the next cell.")


# Cell: Verify all required libraries are importable

import sys
print(f"Python: {sys.version.split()[0]}")
print(f"Path:   {sys.executable}\n")

modules_to_check = [
    ("docx",      "python-docx"),
    ("pydantic",  "pydantic"),
    ("openpyxl",  "openpyxl"),
    ("thefuzz",   "thefuzz"),
    ("requests",  "requests"),
]

all_ok = True
for module_name, package_name in modules_to_check:
    try:
        mod = __import__(module_name)
        version = getattr(mod, "__version__", "(no version attr)")
        print(f"  ✅ {module_name:15s} {version}  (from {package_name})")
    except ImportError as e:
        print(f"  ❌ {module_name:15s} MISSING  (install: pip install {package_name})")
        all_ok = False

print()
print("🎉 All libraries ready." if all_ok else "⚠️ Install missing packages and retry.")