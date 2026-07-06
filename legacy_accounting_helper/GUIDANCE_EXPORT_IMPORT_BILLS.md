# Export / Import Bills — moving the receipt corpus between environments

Receipt/invoice **documents** attached to Revolut transactions (`invoice_attachment_ids`) are tedious to rebuild
(upload from disk, Revolut fetch, Gmail lookup). These two actions move that corpus between databases (local ⇄
production) keyed on the stable **Revolut transaction id**.

## Export Bills  (`action_export_bills`, ⚙ list action)
Bundles the **selected** transactions' attached receipts into `revolut_bills_export.zip`:
```
manifest.csv                 # columns: revolut_tx_id,invoice_path  — ONE row per file
<year>/<merchant>/<file>     # human-readable tree (year = settlement_date_local.year)
```
- Files are exported **byte-for-byte** — no merging, no conversion (a `.docx` stays a `.docx`).
- A tx with N files → N rows / N files. Names/paths are sanitized and de-duplicated so the manifest is unambiguous.
- Only `invoice_attachment_ids` is exported; the `account.move` vendor bill is **not** (it is recreated on the
  target by "Inject attached Bill").
- Attachments with empty content are skipped; raises if the selection has no documents.

## Import Bills  (`revolut.bill.import.wizard`, ⚙ list action → upload wizard)
Upload the exported `.zip` and click **Import**. For each `manifest.csv` row:
- **Match** `revolut_tx_id → revolut_id` within the **current company**. No local tx → counted as *missing
  transaction*, skipped.
- **Dedupe** by content (SHA-1 vs the tx's existing `ir.attachment.checksum`) → already-present files are skipped.
  Re-importing the same zip is a **no-op**.
- Otherwise create an `ir.attachment` (mimetype guessed from bytes) and link it via `invoice_attachment_ids`.
- A summary notification reports: attached / duplicates skipped / missing transaction / missing file.

Import **never** creates or reconciles bills — it only restores the documents. Afterwards the txs show their receipts
(`accounting_stage` → "Needs bill injection" where applicable) and you run the normal Inject → Reconcile pipeline.

## Key code
- `models/revolut_transaction.py` — `action_export_bills`, `action_open_bill_import_wizard`,
  `_sanitize_path_component`, `_dedupe_path` (reuses the `action_download_documents` zip pattern).
- `wizards/revolut_bill_import_wizard.py` — `action_import` (csv + SHA-1 dedupe + `guess_mimetype`).
- `views/revolut_bill_import_wizard_views.xml` — wizard form + the two server actions.

## Notes
- The whole zip is built/decoded in memory — fine for a one-off migration.
- `manifest.csv` is UTF-8; paths use `/`; basename via `path.rsplit('/',1)[-1]`.
