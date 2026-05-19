# Project Velocity

Project Velocity is a deployed media operations and invoice automation web app built to help advertising teams process invoice PDFs, validate media plans, prepare Prisma-ready import files, and deliver organised client folders through ZIP download or Google Drive sync.

The app uses deterministic Python logic first, with Google Gemini used only as a controlled fallback when invoice or media-plan fields are missing, weak, or unclear.

---

## Overview

Project Velocity automates repetitive media operations tasks including:

- Invoice data extraction
- Invoice renaming and folder sorting
- Master Invoice Tracker updates
- Media plan parsing
- Buying Guide validation
- Prisma import file generation
- Buying Guide gap reporting
- ZIP export
- Google Drive sync

The goal is to reduce manual work while keeping human review checkpoints in place before final outputs are approved.

---

## Key Features

### Invoice Automation

- Upload PDF invoices through the dashboard
- Extract invoice text and tables locally
- Detect supplier from invoice content or filename
- Extract key fields such as:
  - Client
  - Market
  - Month
  - Year
  - Supplier
  - Invoice number
  - Currency
  - Amount
- Update the Master Invoice Tracker
- Detect and skip duplicate invoice numbers
- Rename invoices using a standard naming convention
- Sort invoices into client folders

Example folder structure:

```text
Clients/[Client]/[Market]/[Year]/[Month]/
```

Example renamed file:

```text
CLIENT_Supplier_MARKET_MONYY_InvoiceNo.pdf
```

---

### Media Plan Automation

- Upload media plan files
- Parse placement-level data
- Detect client and campaign information
- Normalise partner/channel names
- Match placements against the Buying Guide
- Generate Prisma-ready import files
- Flag unmatched partners or missing mappings

Supported canonical partners include:

- Meta
- TikTok
- Google
- Google Search
- Google PMAX
- Google Display
- Google Demand Gen
- Google Youtube
- Apple Search
- Reddit
- The Trade Desk
- Moloco
- Jampp

---

### Buying Guide Gap Report

If a media-plan partner or placement cannot be matched to the approved Buying Guide, Project Velocity generates a gap report instead of auto-approving the row.

The gap report can include:

- Client
- Missing partner
- Suggested aliases
- Suggested placement booking type
- Suggested cost method
- Confidence level
- Required human action
- Finance approval status

Unmatched rows are marked as requiring human review and are not automatically exported as final approved data.

---

### Google Drive Sync

Project Velocity can sync sorted invoice folders to Google Drive.

Supported authentication methods:

1. **OAuth**
   - Best for local use
   - Opens browser sign-in on first sync
   - Saves `token.json` for future syncs

2. **Service Account**
   - Best for automation or server deployment
   - No browser sign-in required
   - Target Drive folder must be shared with the service account email

The app auto-detects whether the uploaded `credentials.json` is OAuth or Service Account credentials.

---

## AI Usage

Project Velocity uses Google Gemini API as a fallback, not as the primary processor.

The app first uses:

- Python parsing
- Supplier-specific rules
- Regex extraction
- Local PDF text/table extraction
- Canonical partner mapping
- Buying Guide matching

Gemini is only called when data is missing, weak, invalid, or unclear.

### Gemini is used for:

- Resolving missing invoice fields
- Reading native PDFs when extracted text is insufficient
- Enriching unclear media-plan rows
- Suggesting Buying Guide gap recommendations

### Gemini is not allowed to:

- Invent supplier codes
- Invent supplier names
- Invent finance fields
- Auto-approve Buying Guide rows
- Return free-form text when structured JSON is required

---

## Safety & Governance

Project Velocity includes multiple controls to reduce hallucination and protect data quality.

### Hallucination Controls

- Deterministic rules run before Gemini
- Gemini only fills missing or weak fields
- Prompts require strict JSON output
- Empty string is preferred over guessing
- Output is parsed and validated before use
- Partner values must match an approved list
- Invalid or malformed Gemini responses are ignored

### Data Privacy Controls

- Files are processed locally first
- Gemini is used only as fallback enrichment
- Invoice text sent to Gemini is capped
- Media-plan enrichment uses row and batch limits
- Native PDF fallback is selective
- API keys are stored as environment variables

### Compliance Controls

- Duplicate invoice numbers are skipped
- Human review checkpoints are built into the workflow
- Buying Guide gaps require finance approval
- Final files are renamed and sorted consistently
- Outputs can be reviewed before ZIP download or Drive sync

---

## Tech Stack

- **Backend:** Python, Flask
- **Data Processing:** pandas, openpyxl
- **PDF Parsing:** pdfplumber
- **AI Fallback:** Google Gemini API
- **Google Integration:** Google Drive API
- **Frontend:** HTML, Tailwind CSS, JavaScript
- **File Outputs:** Excel, CSV, PDF, ZIP
- **Deployment:** Web app deployment URL

---

## Project Structure

```text
project-velocity/
├── app.py
├── requirements.txt
├── .env.example
├── README.md
├── invoices/
├── Clients/
├── Output/
├── uploads/
├── static/
├── templates/
├── credentials.json
├── token.json
└── modules/
```

Depending on deployment setup, some generated folders may be created automatically at runtime.

---

### Optional Google Drive credentials

Google Drive sync requires uploading a valid `credentials.json` through the app dashboard.

Do not commit real credentials or tokens to GitHub.

---

## Usage

### Invoice Workflow

1. Open the Project Velocity dashboard.
2. Upload invoice PDF files.
3. Run invoice extraction.
4. Review extracted values in the tracker.
5. Confirm client, market, month, amount, and currency.
6. Run invoice sorting.
7. Review renamed files and folder structure.
8. Download the sorted output as ZIP or sync to Google Drive.

---

### Media Plan Workflow

1. Upload the media plan file.
2. Upload or confirm the Buying Guide.
3. Run media-plan parsing.
4. Review matched and unmatched placements.
5. Generate the Buying Guide gap report if required.
6. Generate Prisma-ready import file.
7. Review output before uploading into Prisma.

---

### Google Drive Sync Workflow

1. Open the Google Drive Sync setup guide in the app.
2. Upload `credentials.json`.
3. Set the target Google Drive folder ID.
4. Click **Sync to Drive**.
5. Review the destination folder after sync.

---

## Output Files

Project Velocity can generate:

```text
Master Invoice Tracker.xlsx
invoice_sort_report.csv
Buying Guide Gap Report.xlsx
Prisma Import File.xlsx
Sorted invoice folders
ZIP download
Google Drive synced folders
```

---

## Mapping Audit Trail

Key data points are traceable back to source documents.

| Data Point | Source | Validation |
|---|---|---|
| Invoice number | Supplier invoice text or filename | Used for duplicate detection |
| Client / Market | Campaign names, invoice text, filename, or media plan rows | Normalised into standard codes |
| Amount / Currency | Invoice totals | Cleaned into decimal and ISO currency |
| Partner / Channel | Media-plan placement rows | Mapped to canonical partner list |
| Buying Guide match | Approved Buying Guide | Unmatched rows become gap report items |

---

## Human Review Checkpoints

Project Velocity does not treat AI output as automatically final.

Human review is expected at these points:

1. After invoice extraction
2. Before tracker finalisation
3. After invoice sorting
4. Before Google Drive sync or ZIP delivery
5. After media-plan parsing
6. Before Prisma import upload
7. Before adding any new Buying Guide row

---

## Security Notes

- Do not commit `.env`
- Do not commit `credentials.json`
- Do not commit `token.json`
- Store API keys as environment variables
- Review all extracted financial data before final use
- Revoke Google credentials if accidentally exposed

Recommended `.gitignore` entries:

```gitignore
.env
credentials.json
token.json
invoices/
Clients/
Output/
uploads/
__pycache__/
*.pyc
```

---

## Limitations

- Output accuracy depends on invoice quality and supplier formatting
- Scanned or image-heavy PDFs may require Gemini PDF fallback
- Buying Guide gaps still require human finance approval
- Prisma output should be reviewed before upload
- Google Drive sync requires valid credentials and folder permissions

---

## One-Line Summary

Project Velocity is a local-first, AI-assisted media operations app that turns raw invoice PDFs and media plans into verified trackers, sorted folders, Prisma-ready files, and Google Drive deliverables.
