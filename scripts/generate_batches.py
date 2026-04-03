#!/usr/bin/env python3
"""
generate_batches.py — Phase 3 of the airtable-crm-import skill

Reads creates.json and updates.json (output of dedup.py) and splits them
into numbered batch files of 10 records each, ready for the Airtable API.

Also writes batch_manifest.json and initializes progress.json for resume support.

Requires crm_config.json (written by setup_helper.py on first run).

Usage:
  python3 generate_batches.py \\
    --creates    /sessions/work/creates.json \\
    --updates    /sessions/work/updates.json \\
    --config     /sessions/work/crm_config.json \\
    --output-dir /sessions/work/ \\
    --segment    general \\
    --tags       "tag1,tag2" \\
    --status     MAILABLE \\
    --source     "Event Name 2025"
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

BATCH_SIZE = 10

# Optional fields — skip if blank (don't send empty string to Airtable)
SKIP_IF_BLANK = {
    "first_name", "last_name", "phone", "company", "job_title",
    "notes", "alt_email_1", "alt_email_2",
}


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


def contact_to_airtable_fields(contact: dict, config: dict, defaults: dict) -> dict:
    """
    Map a cleaned contact dict to Airtable field IDs using crm_config.
    Merges import-level defaults for segment/tags/status/source where contact
    doesn't supply its own values.
    """
    fields = {}

    def set_field(logical_name: str, value):
        fid = get_field_id(config, logical_name)
        if not fid:
            return  # field not mapped in this CRM — skip
        if logical_name in SKIP_IF_BLANK and not value:
            return
        if is_multi_select(config, logical_name):
            if isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            value = list(value) if value else []
            if not value:
                return
        fields[fid] = value

    # Required: name + email
    name  = (contact.get("name") or "").strip()
    email = (contact.get("email") or "").strip()
    if not name:
        name = email  # fallback: use email as name
    set_field("name", name)
    set_field("email", email)

    # Optional personal fields
    set_field("first_name", (contact.get("first_name") or "").strip())
    set_field("last_name",  (contact.get("last_name")  or "").strip())
    set_field("phone",      (contact.get("phone")      or "").strip())
    set_field("company",    (contact.get("company")    or "").strip())
    set_field("job_title",  (contact.get("job_title")  or "").strip())

    # Segment (singleSelect) — contact value takes priority over import default
    segment = contact.get("primary_segment") or defaults.get("segment", "general")
    set_field("primary_segment", segment)

    # Tags (multipleSelect) — merge contact tags with import defaults
    contact_tags = contact.get("tags", [])
    if isinstance(contact_tags, str):
        contact_tags = [t.strip() for t in contact_tags.split(",") if t.strip()]
    default_tags = defaults.get("tags", [])
    if isinstance(default_tags, str):
        default_tags = [t.strip() for t in default_tags.split(",") if t.strip()]
    merged_tags = list(contact_tags)
    for t in default_tags:
        if t not in merged_tags:
            merged_tags.append(t)
    set_field("tags", merged_tags)

    # Status (singleSelect)
    status = contact.get("outreach_status") or defaults.get("status", "MAILABLE")
    set_field("outreach_status", status)

    # Provenance
    source = contact.get("primary_source") or defaults.get("source", "")
    events = contact.get("all_events")     or defaults.get("source", "")
    if source:
        set_field("primary_source", source)
    if events:
        set_field("all_events", events)

    # Notes + alt emails
    set_field("notes",      (contact.get("notes")      or "").strip())
    set_field("alt_email_1", (contact.get("alt_email_1") or "").strip())
    set_field("alt_email_2", (contact.get("alt_email_2") or "").strip())

    return fields


def update_to_airtable_record(update: dict, config: dict) -> dict:
    """
    Convert an update entry to Airtable update format.

    Input format:
    {
      "record_id": "recXXXXXXXXXXXXXXX",
      "fields_to_set": {
        "notes": "...",
        "primary_source": "...",
        "company": "...",    # only if existing CRM value was blank
        ...
      }
    }
    """
    record_id = update["record_id"]
    fields = {}
    for logical_name, value in update.get("fields_to_set", {}).items():
        fid = get_field_id(config, logical_name)
        if not fid:
            continue
        if logical_name in SKIP_IF_BLANK and not value:
            continue
        if is_multi_select(config, logical_name):
            if isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            value = list(value) if value else []
            if not value:
                continue
        fields[fid] = value
    return {"id": record_id, "fields": fields}


def write_batches(records: list, prefix: str, output_dir: str) -> int:
    """Write records into numbered batch files. Returns total batch count."""
    n_batches = math.ceil(len(records) / BATCH_SIZE) if records else 0
    for i in range(n_batches):
        batch = records[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        path  = os.path.join(output_dir, f"{prefix}_{i:03d}.json")
        with open(path, "w") as f:
            json.dump(batch, f)
    return n_batches


def main():
    parser = argparse.ArgumentParser(description="Generate Airtable batch files for CRM import")
    parser.add_argument("--creates",    required=True,  help="Path to creates.json")
    parser.add_argument("--updates",    required=True,  help="Path to updates.json")
    parser.add_argument("--config",     required=True,  help="Path to crm_config.json")
    parser.add_argument("--output-dir", default=".",    help="Directory for batch files")
    parser.add_argument("--segment",    default="general")
    parser.add_argument("--tags",       default="")
    parser.add_argument("--status",     default="MAILABLE")
    parser.add_argument("--source",     default="")
    args = parser.parse_args()

    config = load_config(args.config)
    os.makedirs(args.output_dir, exist_ok=True)

    defaults = {
        "segment": args.segment,
        "tags":    [t.strip() for t in args.tags.split(",") if t.strip()],
        "status":  args.status,
        "source":  args.source,
    }

    # Creates — convert contacts to Airtable field-ID format
    with open(args.creates) as f:
        creates_raw = json.load(f)

    create_records = []
    for contact in creates_raw:
        fields = contact_to_airtable_fields(contact, config, defaults)
        if fields:
            create_records.append({"fields": fields})

    n_create_batches = write_batches(create_records, "cb", args.output_dir)

    # Updates — already have record IDs from dedup step
    with open(args.updates) as f:
        updates_raw = json.load(f)

    update_records = []
    for upd in updates_raw:
        record = update_to_airtable_record(upd, config)
        if record["fields"]:  # skip if nothing to update
            update_records.append(record)

    n_update_batches = write_batches(update_records, "ub", args.output_dir)

    # Manifest + progress tracker
    manifest = {
        "total_creates":  len(create_records),
        "total_updates":  len(update_records),
        "create_batches": n_create_batches,
        "update_batches": n_update_batches,
        "batch_size":     BATCH_SIZE,
    }
    with open(os.path.join(args.output_dir, "batch_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    progress = {
        "creates_done":  0,
        "updates_done":  0,
        "total_creates": n_create_batches,
        "total_updates": n_update_batches,
        "last_updated":  "",
    }
    with open(os.path.join(args.output_dir, "progress.json"), "w") as f:
        json.dump(progress, f, indent=2)

    print(f"✓ Create batches: {n_create_batches} ({len(create_records)} records)")
    print(f"✓ Update batches: {n_update_batches} ({len(update_records)} records)")
    if n_create_batches:
        print(f"  Creates: cb_000.json … cb_{n_create_batches-1:03d}.json")
    if n_update_batches:
        print(f"  Updates: ub_000.json … ub_{n_update_batches-1:03d}.json")


if __name__ == "__main__":
    main()
