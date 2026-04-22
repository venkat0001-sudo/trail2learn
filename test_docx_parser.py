# Cell: Test docx_parser.py on the real OEM document
#
# This is the first real data you'll see from the pipeline.
# Upload your OEM Ax.docx to the OEM Automation folder first.

from pathlib import Path
from docx_parser import parse_oem_docx

# ─── UPDATE THIS PATH to your actual uploaded DOCX ─────────────────
DOCX_PATH = Path("./OEM_Requirement.docx")  # adjust if your filename differs
# ──────────────────────────────────────────────────────────────────

if not DOCX_PATH.exists():
    print(f"❌ File not found: {DOCX_PATH.resolve()}")
    print("   Upload your OEM DOCX to the OEM Automation folder first,")
    print("   then update DOCX_PATH above.")
else:
    print(f"📄 Parsing: {DOCX_PATH.name}")
    print(f"   Size: {DOCX_PATH.stat().st_size / 1024:.1f} KB\n")
    
    entries = parse_oem_docx(DOCX_PATH)
    
    print(f"✅ Extracted {len(entries)} feature entries.\n")
    
    # Summary by origin
    section_entries = [e for e in entries if e.key.origin == "section"]
    row_entries = [e for e in entries if e.key.origin == "table_row"]
    print(f"   Section-origin:    {len(section_entries)}")
    print(f"   Table-row-origin:  {len(row_entries)}")
    
    # Summary by top chapter
    print(f"\n📚 Breakdown by chapter:")
    from collections import Counter
    chapters = Counter(e.top_chapter or "(no chapter)" for e in entries)
    for chap, count in sorted(chapters.items()):
        print(f"   {count:4d}  {chap}")
    
    # Show first 10 entries in detail
    print(f"\n🔍 First 10 entries:")
    for i, e in enumerate(entries[:10], 1):
        origin_marker = "📋" if e.key.origin == "section" else "  └─"
        print(f"\n  [{i}] {origin_marker} {e.topic}")
        print(f"       chapter:  {e.top_chapter}")
        print(f"       parent:   {e.parent_section}")
        if e.cell_text:
            preview = e.cell_text[:100].replace('\n', ' ')
            print(f"       cell:     {preview}...")
        else:
            preview = e.full_text[:100].replace('\n', ' ')
            print(f"       text:     {preview}...")
    
    # Sanity checks
    print(f"\n🔎 Sanity checks:")
    print(f"   Entries with chapter set:       "
          f"{sum(1 for e in entries if e.top_chapter)}/{len(entries)}")
    print(f"   Section entries w/ section#:    "
          f"{sum(1 for e in section_entries if e.section_number)}/{len(section_entries)}")
    print(f"   Row entries w/ cell_text:       "
          f"{sum(1 for e in row_entries if e.cell_text)}/{len(row_entries)}")
    print(f"   Row entries w/ parent_section:  "
          f"{sum(1 for e in row_entries if e.parent_section)}/{len(row_entries)}")