#!/usr/bin/env python3
"""
clean_csv.py — Phase 1 of the Tai Ku CRM Import skill

Reads any CSV of contacts and outputs:
  - clean_contacts.json    : normalized, deduped-within-file contacts
  - no_email_holds.json    : contacts missing an email address
  - clean_stats.json       : summary stats and column map detected

Usage:
  python3 clean_csv.py \
    --input /path/to/contacts.csv \
    --segment cannabis \
    --tags canna_industry,vendor_prospect \
    --status MAILABLE \
    --source "MJBizCon 2025" \
    --output-dir /sessions/eager-clever-carson/
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re

# ---------------------------------------------------------------------------
# Column name normalization — maps messy CSV headers → canonical field names
# See references/column_patterns.md for the full rationale.
# ---------------------------------------------------------------------------
COLUMN_MAP = {
    # Name variants
    "name": "name", "full name": "name", "fullname": "name",
    "full_name": "name", "contact name": "name", "contact": "name",
    "display name": "name", "displayname": "name",
    # First name
    "first name": "first_name", "first_name": "first_name",
    "firstname": "first_name", "first": "first_name", "fname": "first_name",
    "given name": "first_name",
    # Last name
    "last name": "last_name", "last_name": "last_name",
    "lastname": "last_name", "last": "last_name", "lname": "last_name",
    "surname": "last_name", "family name": "last_name",
    # Email
    "email": "email", "email address": "email", "e-mail": "email",
    "email_address": "email", "emailaddress": "email",
    "primary email": "email", "work email": "email",
    # Phone
    "phone": "phone", "phone number": "phone", "phonenumber": "phone",
    "phone_number": "phone", "mobile": "phone", "cell": "phone",
    "cell phone": "phone", "telephone": "phone", "tel": "phone",
    "mobile number": "phone", "work phone": "phone",
    # Company
    "company": "company", "organization": "company", "org": "company",
    "company name": "company", "employer": "company", "business": "company",
    "firm": "company", "account": "company", "account name": "company",
    # Job title
    "title": "job_title", "job title": "job_title", "jobtitle": "job_title",
    "job_title": "job_title", "position": "job_title", "role": "job_title",
    "occupation": "job_title",
    # Notes / misc
    "notes": "notes", "note": "notes", "comments": "notes",
    "description": "notes", "bio": "notes", "memo": "notes",
    # Source / event
    "source": "primary_source", "primary source": "primary_source",
    "lead source": "primary_source", "origin": "primary_source",
    "event": "all_events", "events": "all_events", "all events": "all_events",
    "event name": "all_events", "conference": "all_events",
    # Segment / tags
    "segment": "primary_segment", "category": "primary_segment",
    "type": "primary_segment", "list type": "primary_segment",
    "tags": "tags", "tag": "tags", "labels": "tags",
    # Alt emails
    "alt email": "alt_email_1", "alternate email": "alt_email_1",
    "alt email 1": "alt_email_1", "secondary email": "alt_email_1",
    "alt email 2": "alt_email_2", "other email": "alt_email_1",
    # Vendor
    "vendor": "vendor_interest", "vendor interest": "vendor_interest",
    "is vendor": "vendor_interest",
}

# Role-based email prefixes that signal a company/generic inbox (not personal)
ROLE_PREFIXES = {
    "info", "contact", "hello", "hi", "hey", "admin", "sales", "support",
    "team", "press", "media", "pr", "marketing", "office", "general",
    "mail", "email", "noreply", "no-reply", "help", "service", "services",
    "enquiries", "enquiry", "inquiry", "inquiries", "bookings", "booking",
}

def normalize_header(h: str) -> str:
    return h.strip().lower().replace("-", " ").replace("_", " ")

def canonical_field(raw_header: str) -> str:
    key = normalize_header(raw_header)
    return COLUMN_MAP.get(key, raw_header.strip().lower().replace(" ", "_"))

def clean_encoding(text: str) -> str:
    """Remove quoted-printable artifacts and common encoding garbage."""
    if not text:
        return text
    # Quoted-printable sequences like =E2=80=9C (left double quote)
    def decode_qp(m):
        try:
            return bytes.fromhex(m.group(1)).decode("utf-8", errors="replace")
        except Exception:
            return ""
    text = re.sub(r"=([0-9A-Fa-f]{2})", decode_qp, text)
    # Strip leftover = at line endings
    text = text.replace("=\n", "").replace("=\r\n", "")
    return text.strip()

def normalize_email(email: str) -> str:
    if not email:
        return ""
    return email.strip().lower()

def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    # Keep digits, +, spaces, dashes, parens — strip everything else
    cleaned = re.sub(r"[^\d\+\-\(\)\s\.]", "", phone.strip())
    return cleaned.strip()

def domain_slug_to_name(slug: str) -> str:
    """
    Convert a domain slug to a readable company name.
    'flowerhire' -> 'Flower Hire'
    'thecannabisindustry' -> 'The Cannabis Industry'
    '420itsolutions' -> '420 IT Solutions'
    """
    # Insert space before uppercase sequences (for camelCase)
    slug = re.sub(r"([a-z])([A-Z])", r"\1 \2", slug)
    # Insert space before digit sequences
    slug = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", slug)
    slug = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", slug)
    # Title case
    return slug.replace("-", " ").replace("_", " ").title().strip()

def is_role_email(email: str) -> bool:
    """Return True if the email looks like a role/company inbox rather than a person."""
    if not email or "@" not in email:
        return False
    local = email.split("@")[0].lower()
    # Direct match on known role prefixes
    if local in ROLE_PREFIXES:
        return True
    # Pattern: local part contains only digits or is very short (≤3 chars)
    if len(local) <= 3 or local.isdigit():
        return True
    return False

def extract_company_from_email(email: str) -> str:
    """Extract a readable company name from the domain of an email address."""
    if not email or "@" not in email:
        return ""
    domain = email.split("@")[1].lower()
    # Remove TLD
    parts = domain.split(".")
    slug = parts[0] if parts else domain
    return domain_slug_to_name(slug)

def parse_name(row: dict) -> tuple[str, str, str]:
    """
    Returns (full_name, first_name, last_name).
    Handles: first+last separate, full name only, email-only (no name).
    """
    first = clean_encoding(row.get("first_name", "")).strip()
    last = clean_encoding(row.get("last_name", "")).strip()
    full = clean_encoding(row.get("name", "")).strip()

    if first and last:
        return f"{first} {last}", first, last
    elif full:
        parts = full.split(None, 1)
        return full, parts[0], parts[1] if len(parts) > 1 else ""
    elif first:
        return first, first, ""
    elif last:
        return last, "", last
    else:
        return "", "", ""

def is_domain_slug(value: str) -> bool:
    """
    Return True if a company field value looks like a raw domain slug
    (all lowercase, no spaces, no punctuation except digits).
    e.g. 'flowerhire', 'thecannabisindustry', '420itsolutions'
    """
    if not value:
        return False
    return bool(re.match(r'^[a-z0-9]+$', value))

def clean_company(value: str) -> str:
    """If company looks like a domain slug, convert to readable name."""
    if is_domain_slug(value):
        return domain_slug_to_name(value)
    return value.strip()

def merge_tags(existing_tags, new_tags):
    """Merge tag lists, preserving existing, avoiding duplicates."""
    merged = list(existing_tags)
    for t in new_tags:
        if t not in merged:
            merged.append(t)
    return merged

def process_csv(
    input_path: str,
    segment: str,
    tags: list,
    status: str,
    source: str,
    output_dir: str,
):
    # ------------------------------------------------------------------
    # 1. Read and normalize headers
    # ------------------------------------------------------------------
    with open(input_path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        raw_headers = reader.fieldnames or []
        field_map = {h: canonical_field(h) for h in raw_headers}

        rows = []
        for row in reader:
            normalized = {}
            for raw_h, val in row.items():
                canonical = field_map.get(raw_h, raw_h)
                normalized[canonical] = (val or "").strip()
            rows.append(normalized)

    detected_columns = {v for v in field_map.values()}
    total_rows = len(rows)

    # ------------------------------------------------------------------
    # 2. Process each row into a contact
    # ------------------------------------------------------------------
    contacts = []
    no_email_holds = []
    anomalies = []
    email_seen = {}  # email -> index in contacts list (for intra-CSV dedup)

    for i, row in enumerate(rows):
        # Clean encoding on all string fields
        row = {k: clean_encoding(v) for k, v in row.items()}

        email = normalize_email(row.get("email", ""))
        phone = normalize_phone(row.get("phone", ""))
        company_raw = row.get("company", "").strip()
        job_title = row.get("job_title", "").strip()
        notes = row.get("notes", "").strip()

        # Notes from source row
        row_source = row.get("primary_source", source) or source
        row_events = row.get("all_events", "").strip() or source
        row_segment = row.get("primary_segment", segment) or segment
        row_status = row.get("outreach_status", status) or status

        # Tags — merge row-level tags with import defaults
        row_tags_raw = row.get("tags", "")
        row_tags = [t.strip() for t in row_tags_raw.split(",") if t.strip()] if row_tags_raw else []
        merged_tags = merge_tags(row_tags, tags)

        # Vendor interest
        vendor_raw = row.get("vendor_interest", "").lower()
        vendor_interest = vendor_raw in ("yes", "true", "1", "x")

        # Alt emails
        alt_email_1 = normalize_email(row.get("alt_email_1", ""))
        alt_email_2 = normalize_email(row.get("alt_email_2", ""))

        # Name parsing
        full_name, first_name, last_name = parse_name(row)

        # Clean company
        company = clean_company(company_raw)

        # ------------------------------------------------------------------
        # Company email rule:
        # If email is a role/generic address OR the local part closely matches
        # the domain slug, and we have no real personal name → derive name from domain
        # ------------------------------------------------------------------
        if not full_name or full_name == email:
            if email:
                if is_role_email(email):
                    derived = company or extract_company_from_email(email)
                    full_name = derived
                    first_name = ""
                    last_name = ""
                    if not company:
                        company = derived
                    anomalies.append(f"Row {i+1}: role email '{email}' → name set to '{derived}'")
                elif not company:
                    # No name and no company — use email as name (fallback)
                    full_name = email
                    anomalies.append(f"Row {i+1}: no name found, using email as name")

        # Flag malformed names (still contain encoding artifacts)
        malformed_name = bool(re.search(r"=\w{2}", full_name or ""))
        if malformed_name:
            anomalies.append(f"Row {i+1}: possible encoding artifact in name '{full_name}'")

        # ------------------------------------------------------------------
        # No email → hold
        # ------------------------------------------------------------------
        if not email:
            no_email_holds.append({
                "reason": "No email address",
                "contact": {
                    "name": full_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "phone": phone,
                    "company": company,
                    "job_title": job_title,
                    "primary_segment": row_segment,
                    "tags": merged_tags,
                    "outreach_status": row_status,
                    "primary_source": row_source,
                    "all_events": row_events,
                    "notes": notes,
                },
            })
            continue

        # ------------------------------------------------------------------
        # Intra-CSV duplicate handling
        # ------------------------------------------------------------------
        if email in email_seen:
            existing_idx = email_seen[email]
            existing = contacts[existing_idx]
            # Merge: keep whichever has more data as primary
            def score(c):
                return sum(1 for v in c.values() if v and v != email)
            if score(row) > score(existing):
                # New row has more data — swap it in, save old email as alt
                old_email = existing.get("email", "")
                new_contact = build_contact(
                    full_name, first_name, last_name, email, phone,
                    company, job_title, merged_tags, row_status,
                    row_source, row_events, notes, vendor_interest,
                    alt_email_1, alt_email_2, row_segment, malformed_name,
                )
                if old_email and old_email != email:
                    if not new_contact["alt_email_1"]:
                        new_contact["alt_email_1"] = old_email
                    elif not new_contact["alt_email_2"]:
                        new_contact["alt_email_2"] = old_email
                contacts[existing_idx] = new_contact
            else:
                # Keep existing, store new email as alt if different
                if email and email != existing["email"]:
                    if not existing["alt_email_1"]:
                        existing["alt_email_1"] = email
                    elif not existing["alt_email_2"]:
                        existing["alt_email_2"] = email
            continue

        email_seen[email] = len(contacts)
        contact = build_contact(
            full_name, first_name, last_name, email, phone,
            company, job_title, merged_tags, row_status,
            row_source, row_events, notes, vendor_interest,
            alt_email_1, alt_email_2, row_segment, malformed_name,
        )
        contacts.append(contact)

    # ------------------------------------------------------------------
    # 3. Write outputs
    # ------------------------------------------------------------------
    os.makedirs(output_dir, exist_ok=True)

    out_contacts = os.path.join(output_dir, "clean_contacts.json")
    out_holds = os.path.join(output_dir, "no_email_holds.json")
    out_stats = os.path.join(output_dir, "clean_stats.json")

    with open(out_contacts, "w") as f:
        json.dump(contacts, f, indent=2)

    with open(out_holds, "w") as f:
        json.dump(no_email_holds, f, indent=2)

    stats = {
        "total_input_rows": total_rows,
        "contacts_with_email": len(contacts),
        "no_email_holds": len(no_email_holds),
        "intra_csv_duplicates_merged": total_rows - len(contacts) - len(no_email_holds),
        "detected_columns": sorted(detected_columns),
        "anomalies": anomalies,
        "import_defaults": {
            "segment": segment,
            "tags": tags,
            "status": status,
            "source": source,
        },
    }
    with open(out_stats, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"✓ Cleaned {total_rows} rows → {len(contacts)} contacts with email, "
          f"{len(no_email_holds)} no-email holds, "
          f"{stats['intra_csv_duplicates_merged']} intra-CSV dupes merged")
    if anomalies:
        print(f"  ⚠ {len(anomalies)} anomalies noted (see clean_stats.json)")

    return stats


def build_contact(
    name, first_name, last_name, email, phone, company, job_title,
    tags, status, source, all_events, notes, vendor_interest,
    alt_email_1, alt_email_2, segment, malformed_name,
) -> dict:
    return {
        "name": name,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "company": company,
        "job_title": job_title,
        "primary_segment": segment,
        "tags": tags,
        "outreach_status": status,
        "primary_source": source,
        "all_events": all_events,
        "notes": notes,
        "vendor_interest": vendor_interest,
        "alt_email_1": alt_email_1,
        "alt_email_2": alt_email_2,
        "malformed_name": malformed_name,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean a contacts CSV for Tai Ku CRM import")
    parser.add_argument("--input", required=True, help="Path to CSV file")
    parser.add_argument("--segment", default="general", help="Default primary_segment")
    parser.add_argument("--tags", default="", help="Comma-separated default tags")
    parser.add_argument("--status", default="MAILABLE", help="Default outreach_status")
    parser.add_argument("--source", default="", help="Primary Source label")
    parser.add_argument("--output-dir", default=".", help="Directory for output JSON files")
    args = parser.parse_args()

    tags_list = [t.strip() for t in args.tags.split(",") if t.strip()]

    process_csv(
        input_path=args.input,
        segment=args.segment,
        tags=tags_list,
        status=args.status,
        source=args.source,
        output_dir=args.output_dir,
    )
