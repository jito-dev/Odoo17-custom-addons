.. _changelog:

Changelog
=========

`17.0.6.0.0`
------------

- **Vacancies are no longer auto-imported from Djinni.** A Djinni vacancy is now
  connected to Odoo only by hand: create the Odoo job, **Link with Djinni**, then
  **Pull**. The scheduled job no longer creates or refreshes vacancies — it only
  pulls candidates (in the background via queue_job). ``sync_job_list`` is now
  update-only and never creates an ``hr.job``. This stops other recruiters'
  vacancies (on a shared account) from leaking into the pipeline.
- New **"Link with Djinni"** wizard with a vacancy **dropdown picker**: load your
  Djinni vacancies and pick the exact one to connect (URL paste kept as fallback).
- New **"Pull from Djinni"** action refreshes one linked vacancy's data on demand.
- New **"Unlink from Djinni"** action (single or bulk) disconnects vacancies from
  Djinni **without touching the Djinni side** — nothing is sent or deleted there.
  Use it to safely detach imported/foreign vacancies.
- **Acknowledgement email is now per-vacancy.** By default an imported candidate
  receives the New-stage acknowledgement (like any applicant). Tick
  **"Don't email candidates on import"** on a vacancy to silence it for that
  vacancy. New **"Send Acknowledgement Email"** action on candidates (single or
  bulk) sends the stage template on demand afterwards. (Replaces the previous
  always-on suppression from 17.0.5.0.0.)

`17.0.5.0.0`
------------

- Sourced candidates are no longer auto-mailed the stock stage acknowledgement
  ("Applicant: Acknowledgement") when the sync imports them. They never applied,
  so that email was spam. The sync now creates applicants with
  ``mail_notrack=True``, which skips only the create-time stage-template email
  fired by Odoo field tracking; the chatter log and recruiter subscription are
  kept, and stage emails the recruiter triggers later still fire normally.

`17.0.4.0.0`
------------

- Candidate sync is now **idempotent and non-destructive**: a candidate already
  in Odoo (matched on ``djinni_ref`` *and* ``job_id``) is skipped on every
  re-sync — never written over — so recruiter edits (name, contact, stage, the
  vacancy they were moved to) survive. Photo/CV are fetched only for newly
  created records. The same person applying to two vacancies now yields two
  independent applicant records instead of bouncing between jobs.
- New "Every 30 minutes" sync interval; it is the new default for the field.
  ``_djinni_candidate_sync_due`` gained a 2-minute grace so an interval equal to
  the 30-min apply cron actually fires every tick instead of every other one.
- One-time migration enables candidate auto-sync (``every_30min``) on all
  existing Djinni-linked vacancies. The field default stays OFF, so vacancies
  created after this rollout remain opt-in.
- Reworded the auto-sync help texts: the candidate listing pull does not consume
  Djinni data-extraction credits.

`17.0.3.0.0`
------------

- Candidate sync cron now runs in the background via OCA ``queue_job`` (one job
  per account, dedicated ``root.djinni`` channel, per-account ``identity_key``),
  so the cron tick returns immediately and a backed-up queue cannot double-pull.
  Both manual sync buttons stay synchronous (their toasts still report real
  counts). Paid-request volume is unchanged — the worker re-evaluates the
  per-vacancy opt-in and interval gates at execution time.
- New dependency: ``queue_job``. **Deploy prerequisite:** Odoo must load
  ``queue_job`` server-wide (``--load=web,queue_job``) or queued jobs never run.

`17.0.1.0.5`
------------

- Fix crash when syncing a vacancy without a quiz: the create/sync wizard no
  longer calls quiz creation on an empty ``djinni.quiz`` record
  (``Expected singleton: djinni.quiz()``).

`17.0.1.0.4`
------------

- Surface Djinni API client errors (400/403/409/422): the rejection reason from
  the API response body is now shown to the user instead of a bare
  "Invalid Operation" / "400 Bad Request".

`17.0.1.0.3`
------------

- Fix vacancy/candidate sync: fall back to a stable name for anonymous Djinni
  candidates so the required ``hr.applicant.name`` is always set.

`17.0.1.0.1`
------------

- Improve views.

`17.0.1.0.0`
------------

- Init version.


