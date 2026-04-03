#!/usr/bin/env python3
"""
dedup.py — Phase 2 (post-lookup) of the airtable-crm-import skill

Takes clean_contacts.json and airtable_matches.json (records found in Airtable
via filterByFormula queries) and splits them into three files:

  - creates.json        : contacts not yet in CRM (new records)
  - updates.json        : existing records where blank fields can be filled
  - conflict_holds.json : records where CRM has conflicting non-blank values

Requires crm_config.json (written by setup_helper.py on first run).

Usage:
  python3 dedup.py \\
    --contacts /sessions/work/clean_contacts.json \\
    --matches  /sessions/work/airtable_matches.json \\
    --config   /sessions/work/crm_config.json \\
    --output-dir /sessions/work/

---------------------------------------------------------------------
airtable_matches.json format (Claude writes this after filterByFormula lookups):
  [
    {
      "id": "recXXXXXXXXXXXXX",
      "email": "user@example.com",
      "fields": {
        "<field_id>": <value>,
        ...
      }
    }
  ]

updates.json format (consumed by generate_batches.py):
  [
    {
      "record_id": "recXXXXXXXXXXXXX",
      "fields_to_set": {
        "company": "Acme Corp",
        "job_title": "CEO",
        "notes": "...",
        "primary_source": "...",
        "all_events": "...",
        "tags": ["tag1", "tag2"]
      }
    }
  ]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Fields always written on updates (provenance — safe to overwrite)
ALWAYS_UPDATE = {"notes", "primary_source", "all_events"}

# Fields that only fill blank CRM cells (never overwrite existing data)
FILL_IF_BLANK = {"first_name", "last_name", "phone", "company", "job_title",
                 "alt_email_1", "alt_email_2"}


def load_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        print(f"✗ crm_config.json not found at: {config_path}", file=sys.stderr)
        print("  Run the setup wizard first — see SKILL.md Phase -1", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def get_field_id(config: dict, logical_name: str) -> str | None:
    entry = config.get("fields", {}).get(logical_name)
    return entry.get("id") if entry else None


def get_field_type(config: dict, logical_name: str) -> str:
    entry = config.get("fields", {}).get(logical_name) or {}
    return entry.get("type", "singleLineText")


def is_multi_select(config: dict, logical_name: str) -> bool:
    return get_field_type(config, logical_name) in ("multipleSelects", "multiSelect", "multipleLookupValues")


def get_crm_field(record: dict, field_id: str):
    """Read a field value from a raw Airtable record by field ID."""
    return record.get("fields", {}).get(field_id)


def is_domain_slug(value: str) -> bool:
    """Return True if value looks like a raw domain slug (all lowercase + digits, no spaces)."""
    return bool(value and re.match(r"^[a-z0-9]+$", value.strip()))


def is_more_authoritative(existing: str, csv_val: str) -> bool:
    """
    Return True if the existing CRM value should be kept over the CSV value.
    A raw domain slug is never more authoritative — CSV always wins in that case.
    """
    existing = (existing or "").strip()
    csv_val = (csv_val or "").strip()
    if not existing:
        return False
    if is_domain_slug(existing):
        return False  # raw slug < any human-readable value
    if " " in existing or len(existing) > len(csv_val):
        return True
    return False


def normalize_tags(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    return [t.strip() for t in str(value).split(",") if t.strip()]


def main():
    parser = argparse.ArgumentParser(description="Dedup contacts against Airtable matches")
    parser.add_argument("--contacts",   required=True, help="Path to clean_contacts.json")
    parser.add_argument("--matches",    required=True, help="Path to airtable_matches.json")
    parser.add_argument("--config",     required=True, help="Path to crm_config.json")
    parser.add_argument("--output-dir", default=".",   help="Directory for output files")
    args = parser.parse_args()

    config = load_config(args.config)
    protected_statuses = {s.upper() for s in config.get("protected_statuses", ["UNSUBSCRIBED", "BOUNCED"])}

    with open(args.contacts) as f:
        contacts = json.load(f)
    with open(args.matches) as f:
        matches_raw = json.load(f)

    # Build lookup: lowercase email → CRM record
    crm_by_email: dict[str, dict] = {}
    for record in matches_raw:
        email_key = (record.get("email") or "").lower().strip()
        if email_key:
            crm_by_email[email_key] = record

    email_fid    = get_field_id(config, "email")
    status_fid   = get_field_id(config, "outreach_status")
    tags_fid     = get_field_id(config, "tags")

    creates:        list[dict] = []
    updates:        list[dict] = []
    conflict_holds: list[dict] = []

    for contact in contacts:
        email = (contact.get("email") or "").lower().strip()
        if not email:
            continue

        crm = crm_by_email.get(email)

        # ----------------------------------------------------------------
        # No match → new record
        # ----------------------------------------------------------------
        if crm is None:
            creates.append(contact)
            continue

        # ----------------------------------------------------------------
        # Match found — check protected status first
        # ----------------------------------------------------------------
        existing_status = ""
        if status_fid:
            existing_status = (get_crm_field(crm, status_fid) or "").strip().upper()
        if existing_status in protected_statuses:
            conflict_holds.append({
                "email":     email,
                "name":      contact.get("name", ""),
                "record_id": crm["id"],
                "reason":    f"Outreach status is {existing_status} — record locked, skipping update",
                "conflicts": [],
            })
            continue

        # ----------------------------------------------------------------
        # Build update payload + detect conflicts
        # ----------------------------------------------------------------
        record_id   = crm["id"]
        fields_to_set: dict = {}
        conflicts:    list[dict] = []

        # Provenance fields — always write
        for field in ALWAYS_UPDATE:
            if get_field_id(config, field) is None:
                continue
            csv_val = (contact.get(field) or "").strip()
            if csv_val:
                fields_to_set[field] = csv_val

        # Fill-blank fields — only if CRM cell is empty
        for field in FILL_IF_BLANK:
            fid = get_field_id(config, field)
            if fid is None:
                continue
            existing_val = (get_crm_field(crm, fid) or "").strip()
            csv_val      = (contact.get(field) or "").strip()
            if not existing_val and csv_val:
                fields_to_set[field] = csv_val
            elif existing_val and csv_val and existing_val != csv_val:
                if is_more_authoritative(existing_val, csv_val):
                    conflicts.append({
                        "field":     field,
                        "crm_value": existing_val,
                        "csv_value": csv_val,
                    })
                else:
                    # CSV is more complete (e.g. CRM had a domain slug) → use it
                    fields_to_set[field] = csv_val

        # Tags — always merge (never replace)
        if tags_fid:
            existing_tags = normalize_tags(get_crm_field(crm, tags_fid))
            import_tags   = normalize_tags(contact.get("tags", []))
            merged_tags   = list(existing_tags)
            for t in import_tags:
                if t not in merged_tags:
                    merged_tags.append(t)
            if merged_tags:
                fields_to_set["tags"] = merged_tags

        # ----------------------------------------------------------------
        # Route to hold or update
        # ----------------------------------------------------------------
        if conflicts:
            conflict_holds.append({
                "email":               email,
                "name":                contact.get("name", ""),
                "record_id":           record_id,
                "reason":              "Field value conflict — CRM value kept",
                "conflicts":           conflicts,
                "safe_fields_applied": fields_to_set,
            })
        elif fields_to_set:
            updates.append({
                "record_id":    record_id,
                "fields_to_set": fields_to_set,
            })
        # else: CRM already has everything — nothing to do

    # ----------------------------------------------------------------
    # Write outputs
    # ----------------------------------------------------------------
    os.makedirs(args.output_dir, exist_ok=True)

    for filename, data in [
        ("creates.json",        creates),
        ("updates.json",        updates),
        ("conflict_holds.json", conflict_holds),
    ]:
        with open(os.path.join(args.output_dir, filename), "w") as f:
            json.dump(data, f, indent=2)

    print(f"✓ Dedup: {len(creates)} creates | {len(updates)} updates | {len(conflict_holds)} conflicts held")
    print(f"  Output written to: {args.output_dir}")


if __name__ == "__main__":
    main()
