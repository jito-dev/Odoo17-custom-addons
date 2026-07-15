# Export / Import Bills — moving the receipt corpus between environments

Receipt/invoice **documents** attached to Revolut transactions (`invoice_attachment_ids`) are tedious to rebuild
(upload from disk, Revolut fetch, Gmail lookup). These two actions move that corpus between databases (local ⇄
production) keyed on the stable **Revolut transaction id**.

## Export Bills  (`action_export_bills`, ⚙ list action)
Bundles the **selected** transactions' attached receipts into `revolut_bills_export_<stamp>.zip` as a **flat,
self-describing** set of files (17.0.1.116.0 — no manifest, no folders):
```
<revolut_id>.<attachment_id>.<ext>     # one entry per attachment
  e.g.  65f8c1a2-...-9d.4821.pdf
```
- `<revolut_id>` is the tx's stable Revolut id (filename-sanitized); `<attachment_id>` is the source-env
  `ir.attachment.id`, present only to disambiguate multiple receipts on one tx — every name is therefore unique.
- `<ext>` comes from `_attachment_ext(att)` (attachment name, else mimetype).
- Files are exported **byte-for-byte** — no merging, no conversion (a `.docx` stays a `.docx`).
- Only `invoice_attachment_ids` is exported; the `account.move` vendor bill is **not** (it is recreated on the
  target by "Inject attached Bill").
- Attachments with empty content are skipped; raises if the selection has no documents.

## Import Bills  (`revolut.bill.import.wizard`, ⚙ list action → upload wizard)
Upload the exported `.zip` and click **Import**. For each file entry (a stray `manifest.csv` is ignored):
- **Parse** the basename as `<revolut_id>.<attachment_id>.<ext>` via `rsplit('.', 2)` (from the right, so a
  revolut_id containing dots stays intact). A name that doesn't split into 3 parts → counted as *unparseable*.
- **Match** `revolut_id` within the **current company**. No local tx → counted as *missing transaction*, skipped.
  (`<attachment_id>` is **not** used for matching — only the tx id is.)
- **Dedupe** by content (SHA-1 vs the tx's existing `ir.attachment.checksum`) → already-present files are skipped.
  Re-importing the same zip is a **no-op**.
- Otherwise create an `ir.attachment` (name = the zip basename, mimetype guessed from bytes) and link it via
  `invoice_attachment_ids`.
- A summary notification reports: attached / duplicates skipped / no matching transaction / unparseable filenames.

Import **never** creates or reconciles bills — it only restores the documents. Afterwards the txs show their receipts
(`accounting_stage` → "Needs bill injection" where applicable) and you run the normal Inject → Reconcile pipeline.

## Key code
- `models/revolut_transaction.py` — `action_export_bills`, `action_open_bill_import_wizard`,
  `_sanitize_path_component`, `_attachment_ext`.
- `wizards/revolut_bill_import_wizard.py` — `action_import` (filename parse + SHA-1 dedupe + `guess_mimetype`).
- `views/revolut_bill_import_wizard_views.xml` — wizard form + the two server actions.

## Notes
- The whole zip is built/decoded in memory — fine for a one-off migration.
- The filename scheme is the entire contract: no manifest, no folder layout. Old manifest-based exports are no
  longer importable — re-export from the source env.
