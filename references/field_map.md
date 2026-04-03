# Field Map Reference

This file documents the 15 canonical field names this skill understands and how they
map to CRM concepts. The actual Airtable field IDs are stored in `crm_config.json`
(written by the setup wizard on first run) — not hardcoded here.

---

## Canonical Field Names

| Canonical name | Purpose | Airtable type(s) | Required? |
|---|---|---|---|
| `email` | Primary email — dedup key | `email`, `singleLineText` | **Yes** |
| `name` | Full display name | `singleLineText` | **Yes** |
| `first_name` | First name only | `singleLineText` | No |
| `last_name` | Last name only | `singleLineText` | No |
| `phone` | Phone number | `phoneNumber`, `singleLineText` | No |
| `company` | Company / organization | `singleLineText` | No |
| `job_title` | Job title / position | `singleLineText` | No |
| `primary_segment` | Industry/category classification | `singleSelect` | No |
| `tags` | Multi-value labels | `multipleSelects` | No |
| `outreach_status` | Email deliverability status | `singleSelect` | No |
| `primary_source` | Where this contact came from | `singleLineText` | No |
| `all_events` | Events the contact attended | `singleLineText` | No |
| `notes` | Free-text notes | `multilineText`, `singleLineText` | No |
| `alt_email_1` | Secondary email address | `email`, `singleLineText` | No |
| `alt_email_2` | Tertiary email address | `email`, `singleLineText` | No |

---

## Field Behavior: Creates vs Updates

| Field | On Create | On Update |
|---|---|---|
| `email` | Always set | Never changed (it's the dedup key) |
| `name` | Always set | Never changed (conflict-safe) |
| `first_name`, `last_name` | Set if available | Only fills blank CRM cells |
| `phone`, `company`, `job_title` | Set if available | Only fills blank CRM cells |
| `alt_email_1`, `alt_email_2` | Set if available | Only fills blank CRM cells |
| `primary_segment` | Set from import default | Never changed |
| `tags` | Set from contact + defaults | **Always merged** (new tags added, existing kept) |
| `outreach_status` | Set from import default | Never changed |
| `primary_source` | Set from import default | Always overwritten (provenance) |
| `all_events` | Set from import default | Always overwritten (provenance) |
| `notes` | Set if available | Always overwritten (provenance) |

---

## Conflict Detection Logic

A conflict occurs when:
1. The CRM cell is **non-blank**, AND
2. The CSV value **differs** from the CRM value, AND
3. The CRM value **looks more authoritative** (has spaces, longer, properly cased)

Not a conflict:
- CRM cell is blank → CSV fills it
- CRM value is a raw domain slug (`flowerhire`) and CSV has a readable name → CSV wins
- Field is in the "always overwrite" group (provenance fields)

---

## crm_config.json Structure (for reference)

```json
{
  "base_id": "appXXXXXXXXXXXXX",
  "table_id": "tblXXXXXXXXXXXXX",
  "table_name": "Contacts",
  "fields": {
    "email": {
      "id": "fldXXXXXXXXXXXXX",
      "type": "email"
    },
    "name": {
      "id": "fldXXXXXXXXXXXXX",
      "type": "singleLineText"
    },
    "primary_segment": {
      "id": "fldXXXXXXXXXXXXX",
      "type": "singleSelect",
      "options": ["general", "cannabis", "web3", "sports_entertainment", "art_creative"]
    },
    "tags": {
      "id": "fldXXXXXXXXXXXXX",
      "type": "multipleSelects",
      "options": ["canna_industry", "vendor_prospect", "media", "web3", "art_creative"]
    },
    "alt_email_1": {
      "id": null,
      "type": null
    }
  },
  "protected_statuses": ["UNSUBSCRIBED", "BOUNCED"],
  "dedup_key": "email",
  "_version": "1.0",
  "_skill": "airtable-crm-import"
}
```

Fields with `"id": null` are skipped on every import.
