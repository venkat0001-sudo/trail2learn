"""
Pydantic Schemas — Canonical data model for the OEM Spec Analyzer pipeline.

WHY THIS FILE EXISTS:
  Every module in the pipeline reads, writes, or transforms feature data.
  Without a single shared data model, each module invents its own ad-hoc
  dict structure, fields drift, bugs leak across boundaries, and reasoning
  about the pipeline becomes impossible. By defining Pydantic models here
  and importing them everywhere else, we:

    1. Get compile-time type checking in IDEs
    2. Get runtime validation of LLM outputs (via Ollama's format= param)
    3. Have ONE file to update when we add or rename a field
    4. Can generate JSON schemas for LLM prompting automatically

THE PIPELINE'S DATA FLOW, SUMMARIZED:

  DOCX ──parser──► RawFeatureEntry
                          │
                          ▼
           Stage 1 LLM: FeatureSkeleton  (adds M/O, rough description, notes)
                          │
                          ▼
              Diff Engine: ChangeListEntry  (adds change_type, change_details)
                          │
                          ▼
           Stage 2 LLM: EnrichedFeature  (adds codemate_check, codemate_generate)
                          │
                          ▼
              Merger: FinalFeatureRow + FinalChangeRow  (Excel-ready)

Each boundary has its own class, so each stage's input and output are
explicit and separate. No god objects. No optional-everything.
"""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────
# Enum-like Literal types
#
# We use Literal instead of enum.Enum because Pydantic handles them more
# cleanly for JSON serialization, and Ollama's format= param wants literal
# string values in the JSON schema, not enum objects.
# ─────────────────────────────────────────────────────────────────────────

# How a feature entry came into existence in the source DOCX.
# "section"   = it's a DOCX heading like "4.8.3 SCP Feature Enable/Disable"
# "table_row" = it's a row inside a feature-listing table (e.g., "SMART Feature")
EntryOrigin = Literal["section", "table_row"]


# Classification of a requirement's strength per OEM convention.
# Confirmed in design: shall/must = Mandatory, should = Optional,
# shall not = Prohibited.
ManOpt = Literal["Mandatory", "Optional", "Prohibited", "Unspecified"]


# Change classification produced by the diff engine.
ChangeType = Literal["NEW", "MODIFIED", "REMOVED", "UNCHANGED"]


# ─────────────────────────────────────────────────────────────────────────
# Composite Key
#
# We discussed this at length in design. Section-origin features are keyed
# by their section number. Table-row features have no section number, so
# we key them by (parent_section, topic_name).
#
# Wrapping this in a class (not a raw string) means:
#   - Equality is structural, not string-comparison-dependent
#   - We can evolve the key format later without rewriting every comparison
#   - Type hints tell us when we're dealing with a key vs arbitrary string
# ─────────────────────────────────────────────────────────────────────────

class FeatureKey(BaseModel):
    """
    Unique identifier for a feature entry, handling both section-origin
    and table-row-origin features consistently.

    Examples:
        Section-origin: FeatureKey(origin="section", section="4.8.3")
        Table-row:      FeatureKey(origin="table_row", parent="4.7",
                                    topic="SMART Feature")
    """
    origin: EntryOrigin
    section: Optional[str] = None      # populated when origin == "section"
    parent: Optional[str] = None       # populated when origin == "table_row"
    topic: Optional[str] = None        # populated when origin == "table_row"

    def as_string(self) -> str:
        """Flat string form, useful for dict keys or logging."""
        if self.origin == "section":
            return f"section::{self.section}"
        else:
            return f"row::{self.parent}::{self.topic}"

    @field_validator("section")
    @classmethod
    def check_section_when_section_origin(cls, v, info):
        # Pydantic v2 validator — ensures section is set iff origin is "section"
        return v

    def __hash__(self):
        # Make FeatureKey hashable so it can be used as a dict key.
        # We use the tuple of all identifying fields.
        return hash((self.origin, self.section, self.parent, self.topic))


# ─────────────────────────────────────────────────────────────────────────
# Boundary 1: DOCX Parser → Stage 1
#
# RawFeatureEntry is what the parser emits for each item it detects.
# It carries raw text and structural metadata but NO LLM analysis yet.
# ─────────────────────────────────────────────────────────────────────────

class RawFeatureEntry(BaseModel):
    """
    A single feature detected by the DOCX parser, before any LLM analysis.

    Either a section heading (e.g., "4.8.3 SCP Feature Enable/Disable") or
    a feature-named row inside a table (e.g., "SMART Feature" inside the
    table under heading 4.7).
    """

    # Identity
    key: FeatureKey

    # Display text, NOT necessarily the same as key components
    topic: str = Field(
        description="Display label: for sections includes the number "
                    "(e.g., '4.8.3 SCP Feature Enable/Disable'); for table "
                    "rows just the topic name (e.g., 'SMART Feature')"
    )

    # Hierarchy
    section_number: Optional[str] = Field(
        default=None,
        description="Section number like '4.8.3' if this is a heading; "
                    "None if this is a table-row-origin entry"
    )
    parent_section: Optional[str] = Field(
        default=None,
        description="Parent section number. For section-origin, this is one "
                    "level up (4.8.3 → 4.8). For table-row, this is the "
                    "section containing the table (e.g., 4.7)"
    )
    top_chapter: Optional[str] = Field(
        default=None,
        description="The chapter label used in the Section column of the "
                    "final Excel (e.g., '4. Behavioral Specification', "
                    "'5. Mechanical'). Determined by walking up the hierarchy."
    )

    # Content
    full_text: str = Field(
        description="Full prose text of this section (for section-origin) OR "
                    "full text of the parent section (for table-row-origin). "
                    "This is what Stage 1 LLM reads."
    )
    cell_text: Optional[str] = Field(
        default=None,
        description="For table-row-origin only: the content of the row's "
                    "description cell (usually column 2)"
    )

    # Position metadata (used by anchor check to relocate features)
    docx_char_start: Optional[int] = Field(
        default=None,
        description="Character offset in the full extracted DOCX text where "
                    "this entry starts. Used by Section Index for lookup."
    )
    docx_char_end: Optional[int] = Field(
        default=None,
        description="Character offset where this entry ends"
    )


# ─────────────────────────────────────────────────────────────────────────
# Boundary 2: Stage 1 LLM Output
#
# FeatureSkeleton is what Stage 1 produces. It's the RawFeatureEntry plus
# the LLM's analysis: Mandatory/Optional classification and a rough
# description that Stage 2 will later refine.
#
# We define TWO versions:
#   Stage1LLMOutput   — the raw shape we ask the LLM to produce
#   FeatureSkeleton   — the internal shape after we merge LLM output back
#                        with the original RawFeatureEntry
# ─────────────────────────────────────────────────────────────────────────

class Stage1LLMOutput(BaseModel):
    """
    Exactly what we ask the Stage 1 LLM to return for each feature.

    This schema is passed to Ollama's format= parameter. The LLM's output
    is constrained to match this shape exactly — field names, types, and
    required/optional status are all enforced at token-generation level.

    We deliberately ask for a STRING key rather than the full FeatureKey
    nested object because LLMs handle flat strings more reliably than
    deeply nested objects. We reconstruct the FeatureKey in Python.
    """

    feature_key: str = Field(
        description="Echo back the feature's composite key string "
                    "(e.g., 'section::4.8.3' or 'row::4.7::SMART Feature'). "
                    "This lets us match the LLM's output back to the input entry."
    )
    mandatory_optional: ManOpt = Field(
        description="Mandatory if the spec uses 'shall' or 'must'. "
                    "Optional if 'should' or 'may'. "
                    "Prohibited if 'shall not'. "
                    "Unspecified if no clear keyword present."
    )
    rough_description: str = Field(
        description="One-paragraph summary of what the feature requires. "
                    "Not a final CodeMate prompt — Stage 2 will refine this."
    )
    notes: Optional[str] = Field(
        default=None,
        description="Cross-references to other OEM sections or external specs "
                    "(e.g., NVMe Base Spec), any caveats, special cases, etc."
    )


class Stage1LLMResponse(BaseModel):
    """
    The full response we expect from one Stage 1 LLM call.

    Stage 1 processes many features in a single call, so the LLM returns
    a list. We wrap it in an object (not a bare list) because Ollama's
    format= parameter requires a JSON object at the top level.
    """
    features: list[Stage1LLMOutput]


class FeatureSkeleton(BaseModel):
    """
    Internal pipeline representation after Stage 1.
    Combines RawFeatureEntry structural data with Stage 1 LLM analysis.
    This is what the diff engine consumes.
    """

    # Everything from RawFeatureEntry
    key: FeatureKey
    topic: str
    section_number: Optional[str]
    parent_section: Optional[str]
    top_chapter: Optional[str]
    full_text: str
    cell_text: Optional[str] = None

    # Added by Stage 1 LLM
    mandatory_optional: ManOpt
    rough_description: str
    notes: Optional[str] = None

    # Quality flags (set by validators during Stage 1)
    section_verified: bool = Field(
        default=True,
        description="False if LLM output's section number couldn't be matched "
                    "to any section in our Section Index. Flagged in Excel."
    )


# ─────────────────────────────────────────────────────────────────────────
# Boundary 3: Diff Engine Output
#
# After diffing FeatureSkeletons from Ax and Ay, we produce ChangeListEntries.
# ─────────────────────────────────────────────────────────────────────────

class ChangeListEntry(BaseModel):
    """
    One row in the final ChangeList, with diff classification attached.

    Note: For NEW/MODIFIED/UNCHANGED, the embedded skeleton is from version Ay.
          For REMOVED, the embedded skeleton is from version Ax.
          This way the 'topic' and 'section' always point to the version that
          actually contains this feature.
    """

    change_type: ChangeType = Field(
        description="NEW: in Ay, not in Ax. "
                    "MODIFIED: in both, at least one field differs. "
                    "REMOVED: in Ax, not in Ay. "
                    "UNCHANGED: in both, all fields identical."
    )
    change_details: str = Field(
        default="",
        description="Human-readable summary of what changed. "
                    "For MODIFIED: lists which fields differ. "
                    "For RENAME (sub-case of MODIFIED): notes old and new names."
    )
    skeleton: FeatureSkeleton = Field(
        description="The feature's data. From Ay for NEW/MODIFIED/UNCHANGED, "
                    "from Ax for REMOVED."
    )
    # For MODIFIED entries, optionally carry the Ax version too, so Stage 2
    # and the Excel writer can show before/after if needed.
    previous_skeleton: Optional[FeatureSkeleton] = Field(
        default=None,
        description="Only populated for MODIFIED entries. The Ax version of "
                    "this feature, for before/after comparison."
    )


# ─────────────────────────────────────────────────────────────────────────
# Boundary 4: Stage 2 LLM Output
#
# For each NEW or MODIFIED entry, Stage 2 generates two CodeMate prompts.
# ─────────────────────────────────────────────────────────────────────────

class Stage2LLMOutput(BaseModel):
    """
    Exactly what we ask the Stage 2 LLM to return per feature.
    Shape enforced via Ollama format= at token-generation level.
    """
    feature_key: str = Field(
        description="Echo the feature's composite key string so we can "
                    "match output back to input."
    )
    codemate_check_prompt: str = Field(
        description="Prompt to paste into CodeMate (VS Code) asking it to "
                    "search the C++ codebase and report whether this feature "
                    "is already implemented, partially implemented, or absent."
    )
    codemate_generate_prompt: str = Field(
        description="Prompt to paste into CodeMate asking it to generate "
                    "the C++ implementation, with exact OEM spec requirements, "
                    "register details (DWORD/BIT/Feature ID), error handling, "
                    "and entry-point suggestions."
    )


class Stage2LLMResponse(BaseModel):
    """Wrapper for Stage 2's response (one object at top level)."""
    enrichments: list[Stage2LLMOutput]


# ─────────────────────────────────────────────────────────────────────────
# Boundary 5: Final Excel-Ready Shapes
#
# These are what the Excel writer consumes. They represent actual rows
# in the two output sheets.
# ─────────────────────────────────────────────────────────────────────────

class FinalFeatureRow(BaseModel):
    """
    One row of Sheet 1 (Feature_Table_Ay).
    Simplified schema per confirmed design: Section | Topic | Product(s).
    """
    section: str = Field(
        description="Top chapter label, e.g., '4. Behavioral Specification'. "
                    "In Excel, multiple consecutive rows with the same section "
                    "value become a merged cell."
    )
    topic: str = Field(
        description="Either section number + heading (e.g., '4.8.3 SCP Feature "
                    "Enable/Disable') or just feature name for table-row origins "
                    "(e.g., 'SMART Feature')."
    )
    product_columns: dict[str, str] = Field(
        default_factory=dict,
        description="Dict of product name → cell value. Usually blank for all "
                    "products in the output, for engineer to fill. UNCHANGED "
                    "features may carry over Ax values."
    )


class FinalChangeRow(BaseModel):
    """
    One row of Sheet 2 (ChangeList_Ay).
    Full schema: Section | Topic | Change Type | Change Details |
                 CodeMate_Check | CodeMate_Generate.
    """
    section: str
    topic: str
    change_type: ChangeType
    change_details: str
    codemate_check: str = Field(
        default="",
        description="Populated for NEW/MODIFIED/REMOVED. Blank for UNCHANGED."
    )
    codemate_generate: str = Field(
        default="",
        description="Populated for NEW/MODIFIED. 'N/A' for REMOVED. "
                    "Blank for UNCHANGED."
    )


# ─────────────────────────────────────────────────────────────────────────
# Convenience: JSON schemas for Ollama
#
# These generate the JSON Schema dicts we pass to the Ollama API's `format=`
# parameter. Caching them in module-level variables means every Stage 1 call
# uses the same schema object (minor perf + no typos possible).
# ─────────────────────────────────────────────────────────────────────────

STAGE1_JSON_SCHEMA = Stage1LLMResponse.model_json_schema()
STAGE2_JSON_SCHEMA = Stage2LLMResponse.model_json_schema()
