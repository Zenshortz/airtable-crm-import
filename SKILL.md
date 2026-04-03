---
name: airtable-crm-import
description: >
  Import contacts from any CSV into an Airtable CRM. Use this skill whenever the user
  provides a CSV file and wants to import, upload, add, or sync contacts into Airtable.
  Also triggers on: "add these contacts", "import this list", "put this in the CRM",
  "sync this guest list", "load this CSV into Airtable". Handles first-run setup,
  deduplication, field mapping, conflict detection, and batch pushing — all automatically.
---

# Airtable CRM CSV Importer

Import any CSV of contacts into any Airtable CRM. Works with any table structure —
uses a one-time setup wizard to learn the user's specific field layout, then runs
every future import automatically.

---

## Overview of Phases

| Phase | What happens |
|---|---|
| **-1 (first run only)** | Setup wizard: connect to Airtable, map fields, write `crm_config.json` |
| **0** | Detect import context (segment, tags, source) from filename + CSV content |
| **1** | Clean CSV → `clean_contacts.json` |
| **2** | Dedup against Airtable → `creates.json`, `updates.json`, `conflict_holds.json` |
| **3** | Generate batch files |
| **4–5** | Push creates and updates to Airtable |
| **6** | Deliver import report |

---

## FIRST THING: Check for crm_config.json

Before doing anything else, check if `crm_config.json` exists in the working directory
(`/sessions/eager-clever-carson/crm_config.json` or a user-specified location).

- **If it exists:** skip Phase -1 entirely and go to Phase 0.
- **If it does not exist:** run Phase -1 now.

---

## Phase -1 — First-Run Setup Wizard

*Runs once. Connects to Airtable, discovers the user's CRM structure, and writes
crm_config.json. All future imports skip this phase.*

### Step -1a: List available bases

Call `list_bases`. Present the results:
> *"I found these Airtable bases. Which one contains your contacts?*
> *(A) Marketing CRM  (B) Sales Pipeline  (C) Events Master  …"*

Wait for the user to pick one. Save `base_id`.

### Step -1b: List tables in the chosen base

Call `list_tables_for_base` with the selected `base_id`. Present results:
> *"Which table in [Base Name] holds your contacts?*
> *(A) Contacts  (B) Leads  (C) Master List  …"*

Wait for selection. Save `table_id` and `table_name`.

### Step -1c: Get field schema

Call `get_table_schema` with `base_id` and `table_id`. This returns all fields
with their IDs, types, and (for select fields) their option values.

### Step -1d: Auto-map fields with confidence scoring

For each of the 15 canonical field slots, scan the schema and score confidence:

| Canonical name | High-confidence signals (≥80%) | Medium-confidence signals (51–79%) |
|---|---|---|
| `email` | Airtable type is `email`; or name contains "email", "e-mail" | Name contains "address" + no "street" nearby |
| `name` | Name is exactly "name", "full name", "contact name", "display name" | Name is "contact" alone |
| `first_name` | Name contains "first" | Name is "given name", "fname" |
| `last_name` | Name contains "last", "surname" | Name is "lname", "family" |
| `phone` | Airtable type is `phoneNumber`; name contains "phone", "mobile", "cell" | Name contains "tel" alone |
| `company` | Name contains "company", "organization", "employer", "business", "firm" | Name is "account" alone |
| `job_title` | Name contains "title", "position", "job", "role", "occupation" | Name is "role" alone (could be tags) |
| `primary_segment` | Name contains "segment", "category", "list type" | Name is "type" alone |
| `tags` | Name contains "tags", "labels" | Name is "groups" |
| `outreach_status` | Name contains "status", "outreach" | Name is "state" |
| `primary_source` | Name contains "source", "lead source", "origin" | — |
| `all_events` | Name contains "event", "events", "conference" | Name contains "campaign" |
| `notes` | Name contains "notes", "comments", "description", "memo" | Name is "bio" |
| `alt_email_1` | Name contains "alt email", "secondary email", "other email", "alt email 1" | Name contains "email 2" |
| `alt_email_2` | Name contains "alt email 2", "email 3", "tertiary email" | — |

**Auto-map** any field at ≥51% confidence without asking.

**Ask the user** for any field below 51% confidence OR where two CRM fields score
equally for the same canonical slot. Use multiple choice:

> *"Which field in your Airtable is the contact's primary email address?*
> *(A) Email  (B) Work Email  (C) Contact Email  (D) Not in my CRM → skip"*

Ask all uncertain fields in **one grouped message** (not one question at a time).
Fields answered with "Not in my CRM" get `{"id": null, "type": null}` — they're skipped
on every import.

### Step -1e: Ask about protected statuses

> *"If a contact has one of these outreach statuses, should imports skip updating them?
> (These protect your unsubscribes and bounces from being accidentally re-activated.)
> Detected options in your Status field: [list from schema]. Which should be locked?*
> *(Leave blank to use default: UNSUBSCRIBED, BOUNCED)"*

If the user says "default" or leaves blank, use `UNSUBSCRIBED,BOUNCED`.

### Step -1f: Write crm_config.json

Write the field mapping to `/tmp/field_mapping.json`:
```json
{
  "email":           {"id": "<fid>", "type": "<type>"},
  "name":            {"id": "<fid>", "type": "<type>"},
  ...
  "alt_email_2":     {"id": null,    "type": null}
}
```

Then run:
```bash
python3 "$SKILL_DIR/scripts/setup_helper.py" \
  --base-id "<base_id>" \
  --table-id "<table_id>" \
  --table-name "<table_name>" \
  --mapping /tmp/field_mapping.json \
  --protected-statuses "UNSUBSCRIBED,BOUNCED" \
  --output-dir /sessions/eager-clever-carson/
```

Announce:
> *"✓ Setup complete. crm_config.json saved — I'll use this for all future imports.
> Now let's import your CSV…"*

---

## Phase 0 — Detect Import Context

Read the CSV filename and peek at the first 5 rows. Infer the defaults to apply to new records.

| Signal in filename or first rows | Infer |
|---|---|
| "cannabis", "canna", "dispensary", "420", "mjbiz", "leafly" | segment=`cannabis`, tags=`["canna_industry"]` |
| "vendor", "supplier", "brand" (+ cannabis signals) | add tag `vendor_prospect` |
| "web3", "nft", "crypto", "dao", "blockchain", "defi" | segment=`web3`, tags=`["web3"]` |
| "wrestling", "combat sports", "mma" | segment=`sports_entertainment` |
| "art", "creative", "gallery", "music" | segment=`art_creative` |
| "media", "press", "journalist" | add tag `media` |
| A clear event name in the filename | primary_source = that event name |
| Generic / no clear category | segment=`general`, tags=`[]` |

**If ≥51% confident:** state inference in one line and proceed.
> *"Detected: cannabis event import — segment=cannabis, tags=[canna_industry]. Continuing…"*

**If <51% confident:** ask one multiple-choice question:
> *"What type of list is this? (A) Cannabis industry  (B) Web3/Crypto  (C) Fitness/Sports
> (D) Art/Music/Creative  (E) General networking  (F) Other — tell me"*

Also check if the import has a clear source/event name. If not obvious from the filename, ask:
> *"What event or source should I record for these contacts? (Or type 'skip' to leave blank)"*

Default outreach_status for all new records: `MAILABLE`

---

## Phase 1 — Clean the CSV

Run `clean_csv.py` from `SKILL_DIR`. Replace `$SKILL_DIR` with the absolute path of
the directory where this SKILL.md was read from.

```bash
python3 "$SKILL_DIR/scripts/clean_csv.py" \
  --input /path/to/uploaded.csv \
  --segment "cannabis" \
  --tags "canna_industry" \
  --status "MAILABLE" \
  --source "MJBizCon 2025" \
  --output-dir /sessions/eager-clever-carson/
```

Read `clean_stats.json` and confirm briefly:
> *"Cleaned 847 rows → 801 with email, 46 without. 12 intra-CSV dupes merged. Continuing…"*

---

## Phase 2 — Smart Dedup Against Airtable

### Step 2a — Extract emails

```python
import json
with open('/sessions/eager-clever-carson/clean_contacts.json') as f:
    contacts = json.load(f)
emails = list({c['email'].lower() for c in contacts if c.get('email')})
print(f"{len(emails)} unique emails to look up")
```

### Step 2b — Query Airtable (batches of 50, 5 in parallel)

Load `crm_config.json` to get `base_id`, `table_id`, and the email field ID:
```python
import json
with open('/sessions/eager-clever-carson/crm_config.json') as f:
    cfg = json.load(f)
email_fid = cfg['fields']['email']['id']
```

For each batch of 50 emails, call `list_records_for_table`:
```
baseId  = <from config>
tableId = <from config>
filterByFormula = OR(
  LOWER({<email_fid>})='email1@example.com',
  LOWER({<email_fid>})='email2@example.com',
  ... up to 50 ...
)
```

For each returned record, build an entry:
```json
{"id": "recXXX", "email": "<email field value lowercased>", "fields": {...all returned fields...}}
```

Run 5 lookup batches in parallel per turn. Print progress:
> *"Dedup lookups: 250/801 ✓"*

Once complete, write all results to `/sessions/eager-clever-carson/airtable_matches.json`.

### Step 2c — Run dedup.py

```bash
python3 "$SKILL_DIR/scripts/dedup.py" \
  --contacts /sessions/eager-clever-carson/clean_contacts.json \
  --matches  /sessions/eager-clever-carson/airtable_matches.json \
  --config   /sessions/eager-clever-carson/crm_config.json \
  --output-dir /sessions/eager-clever-carson/
```

Brief status:
> *"Dedup complete: 312 new | 489 updates | 22 conflicts held. Generating batches…"*

---

## Phase 3 — Generate Batch Files

```bash
python3 "$SKILL_DIR/scripts/generate_batches.py" \
  --creates    /sessions/eager-clever-carson/creates.json \
  --updates    /sessions/eager-clever-carson/updates.json \
  --config     /sessions/eager-clever-carson/crm_config.json \
  --output-dir /sessions/eager-clever-carson/ \
  --segment    "cannabis" \
  --tags       "canna_industry" \
  --status     "MAILABLE" \
  --source     "MJBizCon 2025"
```

Outputs numbered `cb_NNN.json` (creates) and `ub_NNN.json` (updates) files,
plus `batch_manifest.json` and `progress.json`.

---

## Phase 4 — Push Creates

Read `progress.json` to find the resume point. Push 5 batches in parallel (50 records/turn).
After each group of 5, update `progress.json`.

For each `cb_NNN.json`, call `create_records_for_table`:
- `baseId`:   from `crm_config.json`
- `tableId`:  from `crm_config.json`
- `records`:  the batch array (max 10)

Print progress:
> *"Creates: 150/312 ✓"*

---

## Phase 5 — Push Updates

Same pattern using `update_records_for_table` and `ub_NNN.json` files.
Each batch contains `{"id": "recXXX", "fields": {...}}` — only blank fields are set.

Print progress:
> *"Updates: 200/489 ✓"*

---

## Phase 6 — Deliver Report

Save `CRM_Import_Report.md` to the outputs folder. Include:
- Total creates, updates, no-email holds, conflict holds
- Conflict table: Name | Email | Field | Airtable value (kept) | CSV value (ignored)
- No-email holds count with recommendation
- Any encoding anomalies or malformed names flagged during cleaning

---

## Resume Logic

If `progress.json` exists in the working directory:
1. Read it and announce:
   > *"Resuming import — creates: 150/312 done, updates: 0/489 done. Continuing from cb_015…"*
2. Continue pushing from where it left off
3. Skip Phases -1 through 3 entirely — batch files on disk are the source of truth

---

## Key Rules

**Company email rule:** If an email is a role/generic address (`info@`, `contact@`, `hello@`,
`admin@`, `sales@`, `support@`, `team@`, `press@`, `marketing@`, `noreply@`) AND no personal
name is available → derive name from the domain slug. `flowerhire.com` → name = "Flower Hire",
company = "Flower Hire". Handled automatically by `clean_csv.py`.

**Conflict rule:** Never overwrite an existing non-blank CRM value. Route to `conflict_holds`
with both values shown. Exception: if the existing value is a raw domain slug (all lowercase,
no spaces) and the CSV value is more complete, CSV wins — that's not a conflict.

**Intra-CSV duplicate rule:** If two rows share the same email, keep the row with more data.
Store the other email (if different) in `alt_email_1`/`alt_email_2`. Handled by `clean_csv.py`.

**Status protection rule:** Never update a record whose outreach_status is in the
`protected_statuses` list from `crm_config.json`. Add to conflict_holds instead.

**Tags merge rule:** When updating existing records, always ADD new tags rather than
replacing. Handled automatically by `dedup.py`.
