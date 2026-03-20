# AI Invoice Data Extraction (`jito_invoice_extract_ai`)

## Purpose
Replaces the Odoo Enterprise IAP-based invoice OCR with OpenAI-powered extraction.
Automatically reads vendor bill PDFs and populates invoice fields.

## Dependencies
- `account` — base accounting
- `hr_recruitment_extract_openai` — provides `openai_api_key` / `openai_model` on `res.company`

## Configuration
Settings > Accounting > "AI Invoice Extraction (OpenAI)" section:
- **Mode**: Do not extract / Extract on demand / Extract automatically
- **OpenAI API Key** and **Model** (shared with recruitment module)
- Info panel shows all fields the AI extracts

## Models
- `res.company` — adds `ai_invoice_extract_mode` selection field
- `res.config.settings` — exposes settings via related fields
- `account.move` — adds `ai_extract_state`, `ai_extract_error`, extraction logic
- `ir.attachment` — hooks into `register_as_main_attachment()` for auto-extract

## Extraction Flow
1. PDF uploaded to vendor bill → attachment registered
2. If auto mode: extraction triggers immediately
3. If manual mode: user clicks "Extract with AI" button
4. PDF sent to OpenAI as base64 with structured output prompt
5. Response parsed into: partner, dates, reference, currency, lines
6. Fields populated on the draft bill

## Fields Extracted
- Vendor name & VAT → partner matching
- Invoice number → `ref`
- Invoice/due dates → `invoice_date`, `invoice_date_due`
- Currency → `currency_id`
- Payment reference → `payment_reference`
- Line items → `invoice_line_ids` (description, qty, unit_price, tax)

## Important Patterns
- Uses Pydantic models for structured OpenAI output (`openai_prompts.py`)
- Partner matched by VAT first, then name
- Taxes matched by percentage against company's purchase taxes
- Never overwrites existing data (only populates empty fields)
