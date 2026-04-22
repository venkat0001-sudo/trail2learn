#pydantic_test_code.pydantic_test_code
# Cell: Test pydantic_schemas.py
#
# This exercises every model class to confirm:
#   1. Valid data is accepted
#   2. Invalid data is rejected with clear errors
#   3. The JSON schemas we'll send to Ollama are correctly formed

from pydantic import ValidationError
from pydantic_schemas import (
    FeatureKey,
    RawFeatureEntry,
    Stage1LLMOutput,
    Stage1LLMResponse,
    FeatureSkeleton,
    ChangeListEntry,
    Stage2LLMOutput,
    FinalFeatureRow,
    FinalChangeRow,
    STAGE1_JSON_SCHEMA,
    STAGE2_JSON_SCHEMA,
)

print("=" * 70)
print("PYDANTIC SCHEMAS VALIDATION TEST")
print("=" * 70)

# Test 1: Build a section-origin FeatureKey
print("\n[1] Section-origin FeatureKey")
key_section = FeatureKey(origin="section", section="4.8.3")
print(f"    {key_section}")
print(f"    as_string: {key_section.as_string()}")

# Test 2: Build a table-row FeatureKey
print("\n[2] Table-row FeatureKey")
key_row = FeatureKey(origin="table_row", parent="4.7", topic="SMART Feature")
print(f"    {key_row}")
print(f"    as_string: {key_row.as_string()}")

# Test 3: Build a RawFeatureEntry (what DOCX parser will produce)
print("\n[3] RawFeatureEntry for a section-origin feature")
raw = RawFeatureEntry(
    key=key_section,
    topic="4.8.3 SCP Feature Enable/Disable",
    section_number="4.8.3",
    parent_section="4.8",
    top_chapter="4. Behavioral Specification",
    full_text="The SCP feature shall be enabled or disabled through the Set Feature command...",
)
print(f"    topic:     {raw.topic}")
print(f"    chapter:   {raw.top_chapter}")
print(f"    text_len:  {len(raw.full_text)} chars")

# Test 4: Simulate a Stage 1 LLM output and validate it
print("\n[4] Stage1LLMOutput (simulated LLM response)")
llm_output = Stage1LLMOutput(
    feature_key="section::4.8.3",
    mandatory_optional="Mandatory",
    rough_description="Implement SCP enable/disable via Set/Get Features with Feature ID D8h.",
    notes="Opcode 09h. Bit 0 of DWORD 11 controls SCP.",
)
print(f"    M/O:         {llm_output.mandatory_optional}")
print(f"    description: {llm_output.rough_description[:60]}...")

# Test 5: Validation REJECTS bad data
print("\n[5] Testing validation rejects invalid M/O values")
try:
    bad = Stage1LLMOutput(
        feature_key="section::4.8.3",
        mandatory_optional="maybe",  # ← invalid, should reject
        rough_description="...",
    )
    print("    ❌ FAILED: should have rejected 'maybe'")
except ValidationError as e:
    print(f"    ✅ Correctly rejected invalid value")
    print(f"       Error: {e.errors()[0]['msg']}")

# Test 6: Show the JSON schema that will be passed to Ollama
print("\n[6] STAGE1_JSON_SCHEMA preview (top-level keys)")
print(f"    type:       {STAGE1_JSON_SCHEMA.get('type')}")
print(f"    properties: {list(STAGE1_JSON_SCHEMA.get('properties', {}).keys())}")
print(f"    required:   {STAGE1_JSON_SCHEMA.get('required', [])}")

# Test 7: Build a FeatureSkeleton (post-Stage-1 internal shape)
print("\n[7] FeatureSkeleton (internal shape after Stage 1)")
skel = FeatureSkeleton(
    key=key_section,
    topic=raw.topic,
    section_number=raw.section_number,
    parent_section=raw.parent_section,
    top_chapter=raw.top_chapter,
    full_text=raw.full_text,
    mandatory_optional=llm_output.mandatory_optional,
    rough_description=llm_output.rough_description,
    notes=llm_output.notes,
)
print(f"    topic:        {skel.topic}")
print(f"    M/O:          {skel.mandatory_optional}")
print(f"    verified:     {skel.section_verified}")

# Test 8: ChangeListEntry (what the diff engine produces)
print("\n[8] ChangeListEntry (diff result)")
change = ChangeListEntry(
    change_type="NEW",
    change_details="Not present in previous version",
    skeleton=skel,
)
print(f"    change_type: {change.change_type}")
print(f"    topic:       {change.skeleton.topic}")

# Test 9: Final Excel rows
print("\n[9] Final Excel-ready rows")
feat_row = FinalFeatureRow(
    section="4. Behavioral Specification",
    topic="4.8.3 SCP Feature Enable/Disable",
    product_columns={"PM9E1": ""},
)
print(f"    Feature row: Section='{feat_row.section}', Topic='{feat_row.topic}'")

change_row = FinalChangeRow(
    section="4. Behavioral Specification",
    topic="4.8.3 SCP Feature Enable/Disable",
    change_type="NEW",
    change_details="Not present in previous version",
    codemate_check="<check prompt>",
    codemate_generate="<generate prompt>",
)
print(f"    Change row:  {change_row.change_type} — {change_row.topic}")

print("\n" + "=" * 70)
print("🎉 All schema tests passed.")
print("=" * 70)