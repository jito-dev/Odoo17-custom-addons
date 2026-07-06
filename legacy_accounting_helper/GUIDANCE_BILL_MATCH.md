# Upload & Match Bills

AI-assisted attaching of **manually-downloaded** vendor bills (the ones that can't be pulled from Revolut or Gmail)
to the right `revolut.transaction`.

## Flow
1. In **Expenses Matching** select the transactions, then ⚙ **Actions → Upload & Match Bills**
   (`ir.actions.server` `action_server_upload_match_bills` → `revolut.transaction.action_open_bill_match_wizard`).
2. **Upload** up to **10** bills (PDF / image / DOCX) via the `many2many_binary` widget → **Extract & Match**.
3. The wizard **extracts** each bill's data and **proposes** a 1:1 match to the selected transactions, then lets you
   step through them one at a time with the match reasons; click **Attach** or **Skip**.
4. **Attach** links the file to that transaction's receipts (`invoice_attachment_ids`, sets `has_receipt`). It does
   **not** create a vendor bill — run the existing **Create Bills & Reconcile** action afterwards when ready.

## Models (`wizards/`)
- `revolut.bill.match.wizard` — `transaction_ids` (candidate pool from `active_ids`), `bill_attachment_ids`
  (upload), `line_ids`, `state` (`upload`/`review`/`done`), `current_index`, and computed `current_*` mirrors that
  drive the one-at-a-time stepper. Methods: `action_extract_and_match`, `action_attach_current`,
  `action_skip_current`, `_advance`, `_reload` (re-opens the same transient so the stepper re-renders).
- `revolut.bill.match.line` — one per uploaded bill: extracted fields, `proposed_transaction_id`, `confidence`,
  `match_reasons`, `status`.

## AI extraction (reused)
Reuses `jito_invoice_extract_ai`'s `InvoiceExtraction` schema + `INVOICE_EXTRACTION_PROMPT` and the
`client.responses.parse(...)` pattern (see `jito_invoice_extract_ai/models/account_move.py`).
- **PDF / image** → sent to OpenAI as `input_file` / `input_image`.
- **DOCX** → OpenAI can't read it directly, so text is extracted dependency-free (`zipfile` → `word/document.xml`
  → strip tags) and sent as `input_text`.
- **API key**: prefers `res.company.openai_api_key` / `openai_model`; falls back to this module's `openai.config`.
- Synchronous: one OpenAI call per bill inside `action_extract_and_match` (keep batches ≤10). Each call logs an
  `OPENAI DIGITIZATION:` warning.

## Matching (deterministic, explainable)
AI only extracts; the assignment is computed in Python (`_propose_matches` / `_score`) so the reasons are precise:
- **Amount** `abs(bill total)` vs `abs(tx.amount)` / `abs(tx.bill_amount)` (exact / ≤1% / ≤5%).
- **Currency** equal.
- **Date** `|invoice_date − settlement_date_local|` (≤3 / ≤7 / ≤31 days).
- **Vendor** token overlap vs `merchant_name` + `description`.
Greedy **1:1** assignment above a threshold; `confidence` = high/medium/low; bills below threshold show
**No confident match** (Skip only). More bills than txs (or vice-versa) → the leftovers are simply unmatched.

## Constraints
- Only attaches documents (no bill creation/reconciliation here — that's the separate, existing pipeline).
- Needs an OpenAI key configured; otherwise the wizard raises a clear error.
