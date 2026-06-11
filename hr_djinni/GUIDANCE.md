# hr_djinni — developer guidance

Odoo ↔ Djinni integration. This note covers the **candidate-pull subsystem**
(reworked in `v17.0.1.1.0`); see the Obsidian docs for the broader roadmap.

## What it does
Pulls candidates from Djinni into `hr.applicant` and links vacancies
(`hr.job` ↔ Djinni). Two crons (`data/ir_cron_data.xml`): applicants every
30 min (queue_job), catalogs daily.

## Vacancy lifecycle — MANUAL only (v17.0.6.0.0)
Vacancies are **never auto-imported/auto-created** from Djinni anymore. A Djinni
vacancy (possibly owned by **another recruiter** on a shared account) must be
linked to an Odoo job **by hand**, so foreign vacancies never leak into our
pipeline. Flow: create the Odoo `hr.job` → **Link to Existing Djinni Vacancy** → **Update Vacancy from Djinni**.
- `_get_sync_methods` no longer includes `sync_job_list` — the cron only
  enqueues the candidate pull. Nothing on the cron path touches vacancies.
- `djinni.account.sync_job_list(jobs=None)` is now **update-only**: it writes
  fresh metadata to vacancies **already linked** for the account and **never
  creates** an `hr.job`. A returned Djinni item with no matching linked job is
  ignored. Returns the updated recordset. `jobs=` limits it to one vacancy.
  Field mapping lives in `_djinni_job_payload_to_vals(job)` (shared with Pull).
- `hr.job.action_djinni_pull_vacancy()` — server action **"Update Vacancy from
  Djinni"** (form), refreshes one linked vacancy; warns if Djinni didn't return it.
- `hr.job.action_djinni_unlink()` — server action **"Unlink from Djinni"**
  (list+form, bulk). Clears `djinni_ref` + `djinni_account_id` +
  `djinni_auto_sync_candidates`. **Sends nothing to Djinni, deletes nothing** —
  the safe way to detach imported/foreign vacancies so no archive/delete can
  ever propagate to Djinni (`toggle_active`/`unlink` only push when the company
  flags `djinni_deactivate_vacancy`/`djinni_delete_vacancy` are on; both default off).
- **Link wizard** `djinni.set_ref` (wizard/) now offers a **dropdown picker**:
  *Load Vacancies* (`action_load_vacancies` → `account.list_djinni_vacancies()`)
  fills `djinni.set_ref.line` transient rows; the recruiter picks one by name.
  URL paste stays as a fallback (`_resolve_ref`). *Link &amp; Refresh Vacancy*
  (`action_set_and_sync`) refreshes **only** the freshly linked job's metadata
  (it does **not** import candidates — use "Import Candidates from Djinni" for that).

## Candidate sync (models/djinni_account.py)
Entry points:
- `_enqueue_applicant_sync(enforce_interval=True, trigger='cron')` — **cron path**
  (`v17.0.3.0.0`). Queues one `queue_job` per account (`with_delay`) on the
  dedicated `root.djinni` channel with `identity_key='djinni_applicant_sync_<id>'`,
  so the cron tick returns immediately and a backed-up queue can't double-pull.
  Wired into the cron through `_get_sync_methods`. Does **not** evaluate the gates
  itself — the worker does, at execution time.
- `_job_account_applicant_sync(enforce_interval, trigger)` — the queue_job
  **worker**; just calls `sync_applicant_list` on its one account.
- `sync_applicant_list(enforce_interval=True, trigger='cron')` — **synchronous core**
  used by the worker *and* by the account "Synchronization" button. Pulls
  candidates **only** for vacancies that opted in (`hr.job.djinni_auto_sync_candidates`).
  With `enforce_interval` it also skips vacancies whose `djinni_sync_interval` has
  not elapsed since `djinni_last_applicant_sync` (`hr.job._djinni_candidate_sync_due`).
  Selects the due jobs via `_candidate_jobs_to_sync`.
- `_run_applicant_sync(jobs=None, trigger='cron')` — **core loop**. Iterates
  vacancies, each isolated in its own `cr.savepoint()` + `try/except`, and writes
  one `djinni.sync.log` record per run.
- `_sync_job_candidates(job)` — **creates** one vacancy's new candidates and
  **back-fills** existing anonymous ones (see enrichment below); returns
  new/updated/skipped counters; stamps `hr.job.djinni_last_applicant_sync`.
  **Skips anonymous candidates on import (v17.0.8.0.0):** a payload with no name
  AND no email is never created (counted `skipped`) — recruiters don't want
  placeholder "Djinni #<ref>" cards. Because existence is keyed on the stable
  `djinni_ref`, once that person reveals a name/email a later sync imports them
  **exactly once**, fully formed (no duplicate). Already-imported anonymous cards
  are left as-is and still get enriched in place once they reveal contacts.
- `_iter_job_candidates(job)` — **generator** that pages the candidates endpoint
  with `limit`+`offset` until exhausted. Stops only on an **empty** or
  **all-duplicate** page (API ignoring `offset`, caught by the `seen` guard) or at
  the hard `_CANDIDATES_MAX` cap. It does **NOT** stop on a short page and advances
  `offset` by the page's **actual** length (`offset += len(items)`): Djinni caps a
  page below the requested size (~100 for a `limit=200` request), so the old
  `len(items) < PAGE_SIZE: break` capped every import at the first ~100 candidates,
  and stepping `offset` by the requested size would have skipped every other window
  (fixed v17.0.7.0.0).
- `_build_applicant_vals(applicant, job)` — maps Djinni payload → `hr.applicant`
  vals (then runs through the existing `_get_applicant_vals` hook).

### Invariants — do NOT regress
- **Non-destructive sync.** `_process_applicant(vals)` returns `(applicant, created)`.
  An existing candidate (matched on `djinni_ref` **and** `job_id`,
  `active_test=False`) is returned untouched with `created=False` — the sync
  never *overwrites* a populated field on an existing record. This is what keeps
  recruiter edits alive across the every-30-min re-syncs. Existence is job-scoped
  so one person on two vacancies → two records, no job bouncing.
- **Email-based dedup + adoption (v17.0.9.0.0).** After the `djinni_ref` lookup
  misses, `_process_applicant` does a SECONDARY match by **email** (`=ilike`,
  job-scoped) against candidates **without** a `djinni_ref` — i.e. people added by
  another channel (manual, tracking link, website form). On exactly one match it
  **adopts** that record: stamps `djinni_ref` (+ `djinni_profile_html` if empty),
  posts a chatter note, and returns it as existing (`created=False`) so the caller
  back-fills empty contacts/photo/CV via enrichment. It deliberately does NOT
  touch `stage_id` (no reset to New), `source_id`, or `applicant_origin`
  ("Candidate Source" stays the original channel — it depends on `tracker_id`
  only, so stamping `djinni_ref` does NOT recompute it; see
  [[project_candidate_source_origin]]). Because adoption goes through the
  *existing* path (not create), **no acknowledgement email is sent**. On **>1**
  ref-less email match it is ambiguous: create nothing, count it `skipped`, and
  add a note to the `djinni.sync.log` (`_sync_job_candidates` now returns a
  `notes` list that `_run_applicant_sync` folds into the log `note`).
  `_process_applicant` returns an **empty recordset** with `created=False` to
  signal this skip; the caller guards with `if not applicant_id`.
- **Contact back-fill (enrichment, v17.0.7.0.0).** Djinni reveals a candidate's
  name/contacts only once they *open* them, so candidates imported anonymously
  ("Djinni #<ref> — <job>") would otherwise stay anonymous forever (the sync
  never re-touches them). `hr.applicant._djinni_enrich_from_sync(vals, raw)` closes
  this gap **fill-only**: an incoming Djinni value is written **only into a field
  that is still empty** on our side (`_DJINNI_ENRICH_FIELDS` = partner_name,
  email_from, partner_phone, linkedin_profile, djinni_candidate_url,
  djinni_candidate_cv_url, djinni_date). The placeholder `name` is swapped for the
  real name **only while it still starts with `Djinni #<ref>`** (a recruiter
  rename survives). `stage_id`, `description` and any recruiter-edited field are
  **never** touched. On a real back-fill the candidate is counted as `updated` and
  `djinni_contacts_revealed` is set True (searchable: "Djinni: Contacts Revealed").
  Photo/CV are fetched here only when still missing. Because the back-filled
  contact fields are **not Odoo-tracked**, enrichment posts a **chatter note** on
  the candidate naming exactly which fields it filled ("Djinni sync back-filled
  … : Email, Phone") — otherwise nothing would record what changed.
- Djinni's profile blob (cover letter, skills, highlights…) is written to the
  read-only `hr.applicant.djinni_profile_html`, **never** to the native
  `description`. Shown on the applicant form's Djinni page.
- Photo + CV fetched for **newly created** records, and during enrichment for an
  existing record **only when still missing** (the CV helper also dedupes by URL).
- Stage set only on **create** (`_process_applicant`) → recruiter kanban moves
  are never reset by a re-sync **nor by enrichment**.
- **Acknowledgement email on import — per-vacancy (v17.0.6.0.0).** Default is
  now **send** (matches normal applicants). `_process_applicant(vals, job)`
  applies `mail_notrack=True` **only when** the vacancy ticks
  `hr.job.djinni_suppress_new_email` (Boolean, **default False**, on the Djinni →
  "Candidate Sync" group). The default stage `stage_job0` carries `template_id`
  (the stock "Applicant: Acknowledgement") and Odoo's create-time field tracking
  (`mail.thread` → `_track_template`, fired because `stage_id` is in the created
  values) auto-mails it; `mail_notrack=True` skips **only** that tracked-field
  template email (chatter log + follower-subscription stay). Manual stage moves
  always fire their stage emails.
  - **Manual send after suppression:** `hr.applicant.action_djinni_send_acknowledgement()`
    — server action **"Send Acknowledgement Email"** (list+form, bulk). Posts the
    current stage's `template_id` exactly the way `_track_template` does
    (`message_post_with_source`, `subtype mail.mt_note`,
    `email_layout_xmlid='hr_recruitment.mail_notification_light_without_background'`),
    so the message is identical to the automatic one. No-op (warning toast) if
    the stage has no template.
  - (Pre-v17.0.6.0.0 this was an unconditional import-only suppression for all
    sourced candidates.)
- Anonymous candidates: `name` gets a `Djinni #<id> — <job>` fallback (required
  field), `partner_name` stays empty.
- CV attachments dedupe by `url` (`hr_service_ua.hr_applicant.download_and_link_attachment`).

## Auto-sync (v17.0.2.1.0 opt-in → v17.0.4.0.0 enabled-for-all)
Candidate auto-sync is **per-vacancy** and gated by two fields on the vacancy
form's **Djinni → "Candidate Sync"** group:
- `hr.job.djinni_auto_sync_candidates` (Boolean, **field default False**) — gates the cron.
- `hr.job.djinni_sync_interval` (Selection: 30min / hourly / 4h / 12h / daily /
  weekly, **default `every_30min`**) — min delay between scheduled pulls; mapped to
  a `timedelta` by `hr.job._DJINNI_SYNC_INTERVALS`. The `_djinni_candidate_sync_due`
  check subtracts `_DJINNI_SYNC_DUE_GRACE` (2 min) so an interval equal to the
  30-min apply cron fires every tick rather than every other one.

v17.0.4.0.0 migration enables auto-sync (`every_30min`) on all **existing**
Djinni vacancies (`migrations/17.0.4.0.0/post-migration.py`); the field default
stays False so newly created vacancies remain opt-in. Note: the candidate-listing
pull does **not** consume Djinni data-extraction credits (so frequent pulls are
fine); the only paid step was Odoo IAP resume OCR, which is governed by
`res.company.recruitment_extract_show_ocr_option_selection` (set to `no_send` to
avoid charges), entirely separate from this module.

Trigger matrix (what pulls candidates):
| Trigger | Async? | Respects opt-in? | Respects interval? |
|---|---|---|---|
| Cron (`_synchronize` → `_enqueue_applicant_sync`) | **yes (queue_job)** | yes | yes |
| Account "Synchronization" button (`action_sync`) | no (sync, real toast) | yes | no (forces now) |
| Per-vacancy "Import Candidates from Djinni" button | no (sync, real toast) | no (always pulls) | no |

## queue_job (v17.0.3.0.0)
The cron's candidate pull runs in the background via OCA `queue_job` (one job per
account, channel `root.djinni`, `data/queue_job_channel_data.xml`). Only the cron
is async; **both manual buttons stay synchronous** so their notifications keep
showing real `new/updated/skipped` counts. Paid-request count is unchanged: the
worker re-resolves the opt-in + interval gates at run time, and the per-account
`identity_key` prevents concurrent double-pulls.

**⚠ Deploy prerequisite — without it, sync silently stops.** queue_job's jobrunner
only starts when the module is loaded server-wide. The launcher
`/home/coder/bin/odoo.sh` (`start` branch) now passes `--load=web,queue_job`; for
production also set `--workers=<N≥1>` (threaded mode runs jobs but is dev-only per
the queue_job README). Without `--load=web,queue_job`, `with_delay()` jobs sit in
`queue.job` state `pending` forever (no ir.cron fallback in v17.0.1.4.3). To strictly
serialize Djinni pulls, optionally set `[queue_job] channels = root:1,root.djinni:1`.

**Migration note:** after upgrade, auto-sync is OFF for every existing vacancy.
Recruiters opt in per vacancy; the manual per-vacancy button still works anytime.
The cron tick stays at 30 min (it's just a tick now — each vacancy's interval
decides whether it actually runs).

## Manual triggers (UX)
- `hr.job.action_djinni_sync_candidates()` — server action **"Import Candidates
  from Djinni"** (Action menu, manager-only) syncs one vacancy on demand and
  shows a `new/updated/skipped` notification. Always pulls (ignores opt-in/interval).
- `hr.job.action_djinni_pull_vacancy()` — **"Update Vacancy from Djinni"** refreshes
  one linked vacancy's metadata.
- `hr.job.action_djinni_unlink()` — **"Unlink from Djinni"** (bulk) detaches
  vacancies from Djinni without any Djinni-side effect.
- `hr.applicant.action_djinni_send_acknowledgement()` — **"Send Acknowledgement
  Email"** (bulk) sends the current stage template on demand.
- `djinni.account.action_open_sync_logs()` — smart button "Sync Logs".

## Observability
`djinni.sync.log` (models/djinni_sync_log.py): one row per run with
state (success/partial/error), counters, and a `note` carrying per-vacancy
errors. Menu: *Recruitment → Configuration → Djinni → Sync Logs*.

## Tests
`tests/test_applicant_sync.py` (mocks `_djinni_api_request`): pagination beyond
one page, pagination survives an API-capped page size (the ~100 fix), per-vacancy
failure isolation, the ignore-`offset` anti-infinite-loop guard, and contact
enrichment (back-fills empty fields once revealed, never overwrites a recruiter
edit or the stage). Run:
```
/home/coder/.venv/odoo17/bin/python odoo17_community/odoo-bin -d test_djinni \
  --db_host=postgres --db_user=odoo --db_password="$DB_PASSWORD" \
  --addons-path=.../odoo17_community/addons,.../odoo17_enterprise/odoo/addons,.../jito_modules \
  -i hr_djinni --test-enable --test-tags=/hr_djinni --stop-after-init --no-http --max-cron-threads=0
```

## Open / next stages (see Obsidian)
- Confirm the real pagination param name (`offset` vs `page`) on a live key.
- Stage 2: client-side `applied_at` delta, adaptive polling.
- Stage 3A (done, v17.0.2.0.0): Djinni text moved out of `description` into
  read-only `djinni_profile_html` (stops clobbering recruiter edits).
- Stage 3 remaining: dedup (lean on native "Other applications" email/phone
  button — the Djinni `linkedin` URL is only a weak optional bonus), match scoring,
  tag-based routing. See `obsidian/hr_djinni - stage 3-4 plan (...).md`.
