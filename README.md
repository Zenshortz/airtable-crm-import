# airtable-crm-import

A Claude skill that imports any CSV of contacts into an Airtable CRM — automatically.

Drop in a CSV, and Claude handles the rest: cleaning messy data, deduplicating against
existing records, filling blank fields, protecting unsubscribes, and pushing everything
in optimized batches.

---

## What it does

- **Works with any Airtable table** — a one-time setup wizard maps your specific field layout
- **Handles any CSV format** — Eventbrite, LinkedIn, Mailchimp, Google Contacts, or a custom spreadsheet
- **Smart dedup** — queries Airtable directly by email (no full-table download), handles 10k+ record CRMs efficiently
- **Conflict-safe** — never overwrites existing data; flags disagreements for review
- **Protects unsubscribes** — locked statuses (BOUNCED, UNSUBSCRIBED) are never touched
- **Merges tags** — adds new tags to existing records instead of replacing them
- **Resumes after interruption** — batch files + progress tracking mean a session reset never loses work
- **Cleans encoding artifacts** — handles quoted-printable garbage from mbox exports and CSV encoding issues
- **Role email detection** — `info@company.com` becomes "Company Name" contact, not a blank-name record

---

## Requirements

- [Claude](https://claude.ai) (Cowork mode or Claude Code)
- Airtable MCP connected to Claude
- An Airtable base with a contacts table (any field structure works)

---

## Installation

Download `airtable-crm-import.skill` and install it in Claude's skills directory, or
install via the Cowork plugin interface.

---

## First-time setup

The first time you use the skill, Claude runs a setup wizard:

1. Lists your Airtable bases → you pick the one with your contacts
2. Lists tables in that base → you pick your contacts table
3. Reads the field schema → auto-maps fields by name and type
4. Asks about any fields it can't confidently identify (≥51% confidence = auto, <51% = asks you)
5. Confirms which status values protect records from updates (default: UNSUBSCRIBED, BOUNCED)
6. Saves everything to `crm_config.json` — all future imports skip setup entirely

Total setup time: ~2 minutes.

---

## Usage

Just give Claude your CSV:

> *"Import this CSV into my CRM"*
> *"Add these contacts to Airtable"*
> *"Sync this event list"*

Claude detects the import context (industry, event name, tags) from the filename and
content. If it's not obvious, it asks one quick multiple-choice question.

---

## License

MIT
