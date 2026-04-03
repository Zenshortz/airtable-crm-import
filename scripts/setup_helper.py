#!/usr/bin/env python3
"""
setup_helper.py — First-run configuration writer for airtable-crm-import

Called by Claude after the setup wizard (Phase -1 in SKILL.md) is complete.
Takes the user's field-mapping decisions and writes crm_config.json.

Claude writes a field_mapping.json first, then calls this script:

  python3 setup_helper.py \\
    --base-id appXXXXXXXXXXXXX \\
    --table-id tblXXXXXXXXXXXXX \\
    --table-name "My Contacts" \\
    --mapping /tmp/field_mapping.json \\
    --protected-statuses "UNSUBSCRIBED,BOUNCED" \\
    --output-dir /sessions/eager-clever-carson/

---------------------------------------------------------------------------
field_mapping.json format (Claude writes this before calling the script):

  {
    "email":           {"id": "fldXXXXXXXXXXXXX", "type": "email"},
    "name":            {"id": "fldXXXXXXXXXXXXX", "type": "singleLineText"},
    "first_name":      {"id": "fldXXXXXXXXXXXXX", "type": "singleLineText"},
    "last_name":       {"id": "fldXXXXXXXXXXXXX", "type": "singleLineText"},
    "phone":           {"id": "fldXXXXXXXXXXXXX", "type": "phoneNumber"},
    "company":         {"id": "fldXXXXXXXXXXXXX", "type": "singleLineText"},
    "job_title":       {"id": "fldXXXXXXXXXXXXX", "type": "singleLineText"},
    "primary_segment": {"id": "fldXXXXXXXXXXXXX", "type": "singleSelect", "options": ["general", "cannabis"]},
    "tags":            {"id": "fldXXXXXXXXXXXXX", "type": "multipleSelects", "options": ["tag1", "tag2"]},
    "outreach_status": {"id": "fldXXXXXXXXXXXXX", "type": "singleSelect", "options": ["MAILABLE", "UNSUBSCRIBED", "BOUNCED"]},
    "primary_source":  {"id": "fldXXXXXXXXXXXXX", "type": "singleLineText"},
    "all_events":      {"id": "fldXXXXXXXXXXXXX", "type": "singleLineText"},
    "notes":           {"id": "fldXXXXXXXXXXXXX", "type": "multilineText"},
    "alt_email_1":     {"id": null, "type": null},
    "alt_email_2":     {"id": null, "type": null}
  }

Use null for fields that don't exist in this CRM — they will be skipped.
---------------------------------------------------------------------------
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# The two fields every CRM must have for this skill to work
REQUIRED_FIELDS = {"email", "name"}

# All canonical field names this skill understands
ALL_CANONICAL_FIELDS = {
    "email", "name", "first_name", "last_name", "phone",
    "company", "job_title", "primary_segment", "tags",
    "outreach_status", "primary_source", "all_events",
    "notes", "alt_email_1", "alt_email_2",
}


def validate_mapping(mapping: dict) -> list[str]:
    """Return a list of validation error messages (empty = valid)."""
    errors = []

    for req in REQUIRED_FIELDS:
        entry = mapping.get(req, {})
        if not entry or not entry.get("id"):
            errors.append(f"Required field '{req}' has no Airtable field ID mapped.")

    for canonical, entry in mapping.items():
        if canonical not in ALL_CANONICAL_FIELDS:
            errors.append(f"Unknown canonical field name: '{canonical}'. "
                          f"Valid names are: {sorted(ALL_CANONICAL_FIELDS)}")
        if entry and entry.get("id") and not entry["id"].startswith("fld"):
            errors.append(f"Field ID for '{canonical}' looks wrong: '{entry['id']}' "
                          f"(Airtable field IDs start with 'fld')")

    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Write crm_config.json from setup wizard decisions"
    )
    parser.add_argument("--base-id",    required=True, help="Airtable base ID (appXXX...)")
    parser.add_argument("--table-id",   required=True, help="Airtable table ID (tblXXX...)")
    parser.add_argument("--table-name", default="Contacts", help="Human-readable table name")
    parser.add_argument("--mapping",    required=True, help="Path to field_mapping.json")
    parser.add_argument("--protected-statuses", default="UNSUBSCRIBED,BOUNCED",
                        help="Comma-separated outreach status values that lock a record")
    parser.add_argument("--output-dir", default=".", help="Directory to write crm_config.json")
    args = parser.parse_args()

    # Load mapping
    if not os.path.exists(args.mapping):
        print(f"✗ field_mapping.json not found: {args.mapping}", file=sys.stderr)
        sys.exit(1)

    with open(args.mapping) as f:
        mapping = json.load(f)

    # Validate
    errors = validate_mapping(mapping)
    if errors:
        print("✗ Mapping validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    # Build protected statuses list
    protected = [s.strip().upper() for s in args.protected_statuses.split(",") if s.strip()]

    # Assemble config
    config = {
        "base_id":            args.base_id,
        "table_id":           args.table_id,
        "table_name":         args.table_name,
        "fields":             mapping,
        "protected_statuses": protected,
        "dedup_key":          "email",
        "_version":           "1.0",
        "_skill":             "airtable-crm-import",
    }

    # Warn about unmapped optional fields (not errors, just FYI)
    missing_optional = [
        f for f in ALL_CANONICAL_FIELDS - REQUIRED_FIELDS
        if not mapping.get(f, {}) or not mapping.get(f, {}).get("id")
    ]
    if missing_optional:
        print(f"ℹ  Optional fields not mapped (will be skipped): {', '.join(sorted(missing_optional))}")

    # Write config
    os.makedirs(args.output_dir, exist_ok=True)
    out_path = os.path.join(args.output_dir, "crm_config.json")
    with open(out_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"✓ crm_config.json written to: {out_path}")
    print(f"  Base: {args.base_id}  |  Table: {args.table_name} ({args.table_id})")
    mapped = [k for k, v in mapping.items() if v and v.get("id")]
    print(f"  Fields mapped: {len(mapped)}/{len(ALL_CANONICAL_FIELDS)} — {', '.join(mapped)}")
    print(f"  Protected statuses: {protected}")
    print()
    print("  Setup complete. Future imports will use this config automatically.")


if __name__ == "__main__":
    main()
