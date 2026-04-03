# Column Name Patterns

This reference documents how `clean_csv.py` normalizes messy CSV column headers
into the 15 canonical field names. It also explains how to extend the mapping.

---

## How Column Normalization Works

Before matching, every header is:
1. Stripped of leading/trailing whitespace
2. Lowercased
3. Hyphens replaced with spaces
4. Underscores replaced with spaces

The result is looked up in `COLUMN_MAP`. If not found, the original header is
lowercased and spaces replaced with underscores (passed through as-is).

---

## Recognized Variants

### Email
`email`, `email address`, `e-mail`, `email_address`, `emailaddress`,
`primary email`, `work email`

### Name (full)
`name`, `full name`, `fullname`, `full_name`, `contact name`, `contact`,
`display name`, `displayname`

### First name
`first name`, `first_name`, `firstname`, `first`, `fname`, `given name`

### Last name
`last name`, `last_name`, `lastname`, `last`, `lname`, `surname`, `family name`

### Phone
`phone`, `phone number`, `phonenumber`, `phone_number`, `mobile`, `cell`,
`cell phone`, `telephone`, `tel`, `mobile number`, `work phone`

### Company
`company`, `organization`, `org`, `company name`, `employer`, `business`,
`firm`, `account`, `account name`

### Job title
`title`, `job title`, `jobtitle`, `job_title`, `position`, `role`, `occupation`

### Notes
`notes`, `note`, `comments`, `description`, `bio`, `memo`

### Primary source
`source`, `primary source`, `lead source`, `origin`

### All events
`event`, `events`, `all events`, `event name`, `conference`

### Primary segment
`segment`, `category`, `type`, `list type`

### Tags
`tags`, `tag`, `labels`

### Alt email 1
`alt email`, `alternate email`, `alt email 1`, `secondary email`, `other email`

### Alt email 2
`alt email 2`, `other email` (second occurrence)

### Vendor interest
`vendor`, `vendor interest`, `is vendor`

---

## Source-Specific Quirks

### Eventbrite exports
- Uses "Attendee #" prefix on some columns — the normalizer strips these
- "Order #" columns are ignored
- "Ticket Type" maps to `primary_segment` if the skill is configured to use it

### LinkedIn exports
- "Connected On" → stored in `notes` as "LinkedIn connection: <date>"
- "Position" → `job_title`
- "Company" → `company`

### Mailchimp exports
- "FNAME", "LNAME" → `first_name`, `last_name`
- "EMAIL" → `email`
- "TAGS" → `tags` (comma-separated)

### Google Contacts exports
- "Given Name" → `first_name`
- "Family Name" → `last_name`
- "E-mail 1 - Value" → `email`
- "Phone 1 - Value" → `phone`
- "Organization 1 - Name" → `company`
- "Organization 1 - Title" → `job_title`
- "Notes" → `notes`

---

## Adding New Column Variants

Edit `COLUMN_MAP` in `clean_csv.py`. The format is:
```python
"your new variant": "canonical_name",
```

Example — adding "biz email" as a recognized email header:
```python
"biz email": "email",
```

Column names are normalized before lookup (lowercased, hyphens/underscores → spaces),
so `"Biz-Email"`, `"biz email"`, and `"biz_email"` all resolve to `"biz email"` before
the lookup — you only need to add the normalized (lowercase, space-separated) version.
