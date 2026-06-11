# HR Recruitment Trackers — guidance

Advanced link-tracking for job positions, plus a coarse **Candidate Source**
(origin) classification on every applicant.

## What it does
- **Tracking links** (`hr.recruitment.tracker`): shortened `/t/TOKEN` URLs per
  job, carrying UTM campaign/source/medium + custom params. When a candidate
  applies through such a link, the controller drops a cookie; `hr.applicant.create`
  reads it and stamps `tracker_id` + the native UTM fields + custom params.
- **Candidate Source** (`applicant_origin`): a 3-way provenance of *how the
  record entered the system* — distinct from the marketing UTM `source_id`.

## Main models / fields
- `models/hr_recruitment_tracker.py` — the tracker (token, target_url, job_id, UTM, params).
- `models/hr_applicant.py`:
  - `tracker_id`, `tracking_value_ids`, dynamic `tracker_properties` + 15 grouping slots.
  - **`applicant_origin`** — `Selection(djinni / tracking_link / manual)`, label
    **"Candidate Source"**, `compute='_compute_applicant_origin'`, **stored + indexed**.

## Candidate Source — how it is computed (v17.0.2.0.0)
`_compute_applicant_origin` (depends on `tracker_id`):
```
tracker_id present              -> 'tracking_link'
djinni_ref present (hr_djinni)  -> 'djinni'
otherwise                       -> 'manual'
```
Key points / invariants:
- **Soft dependency on hr_djinni.** `djinni_ref` is contributed by `hr_djinni`;
  the compute guards with `'djinni_ref' in self._fields`, so trackers keeps
  working (nothing is ever classified Djinni) when hr_djinni is absent. Do **not**
  add `djinni_ref` to `@api.depends` or a hard module dependency.
- **Why `@api.depends('tracker_id')` is enough.** Both `tracker_id` and
  `djinni_ref` are set once at create and never change; stored computed fields are
  always evaluated on create regardless of the trigger set, so create-time
  classification is correct. On module upgrade Odoo recomputes all existing rows,
  so the field back-fills retroactively — **no migration script needed**.
- Distinct from UTM `source_id` (Djinni/LinkedIn/Facebook/…). Never overload
  `source_id` for origin. See hr_djinni's `[[project_djinni_skip_anonymous]]`
  context for how Djinni candidates are created (each gets a stable `djinni_ref`).

## Views
- Kanban: small colored tag via `widget="label_selection"`
  (djinni=info, tracking_link=success, manual=secondary).
- Form: shown in the "Tracking Data" page → "Source" group.
- Search: "Candidate Source" Group By added to both inherited search views.

## Tests
`tests/test_applicant_origin.py` — manual / tracking_link / djinni / tracker-wins.
The Djinni cases self-skip when hr_djinni is not installed.
