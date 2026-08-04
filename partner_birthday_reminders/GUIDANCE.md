# partner_birthday_reminders — Module Guidance

Version `17.0.1.0.0`. Companion to `hr_birthday_reminders` (employee
birthdays) — same idea, different audience, deliberately **not** a copy.

## What this module does

Adds a **Birthday** field to contacts and reminds the contact's
**Account Manager** — 7 days before, 1 day before, and on the day —
through a To Do activity, a private inbox notification and an email.

The single structural difference from the HR module: **there is no
roster**. Who gets a reminder is derived from data, not from an
assignment screen:

```
reminder recipient  ==  res.partner.user_id   (the "Salesperson" field,
                                               labelled Account Manager)
```

Assign a contact to someone and set a birthday — they are reminded. No
subscription to create, no group to grant.

**Nothing is ever emailed to the contact themselves.** The reminder is a
private nudge; how (and whether) to greet the client is the Account
Manager's call. This was an explicit product decision — automated
customer-facing mail would need separate sign-off.

## Who appears on the board (the eligibility rule)

`birthday_eligible` is the module's central concept. All four clauses
must hold:

1. `birthday` is set,
2. `is_company = False` — no company records,
3. **not** linked to an Odoo internal user, **current or past** — a
   `res.users` with `share = False`, *including archived ones*,
4. `active = True`.

Clause 3 is the subtle one. A plain read of `partner.user_ids` hides
archived users (`active_test`), so a former colleague would silently
pass the filter. `_compute_has_internal_user` therefore searches
`res.users` with `with_context(active_test=False)` under `sudo()`, and
declares `user_ids.active` among its dependencies. Belt and braces: the
daily cron re-runs the compute for every partner, so any dependency edge
case the ORM misses self-heals within 24 h instead of leaking a
colleague onto the client birthday board.

Portal users are **not** excluded — a portal account is a client, not a
colleague. There is a test for this.

## Main models

| Model | File | Purpose |
|---|---|---|
| `res.partner` (fields) | `models/res_partner.py` | `birthday`, plus stored computes `next_birthday`, `birthday_proximity` (`1_today` … `4_later`), `has_internal_user`, `birthday_eligible`. Also `_birthday_next_occurrence`, `_refresh_partner_birthday_helpers`, `_partners_with_birthday_on`. |
| `res.partner` (engine) | `models/res_partner_reminder.py` | Cron entry point and the three notification channels. Same model, split file — the field layer and the dispatch layer are read for different reasons. |
| `partner.birthday.pref` | `models/partner_birthday_pref.py` | Per-Account-Manager interval choices + `last_run_date` + pause flag. Auto-provisioned; see below. |
| `partner.birthday.log` | `models/partner_birthday_log.py` | Idempotency + audit. `UNIQUE(partner_id, birthday_date, interval, user_id)`. |
| `res.config.settings` | `models/res_config_settings.py` | Cron enable + UTC hour, and the interval defaults used when provisioning a new preference row. |

Constants shared by the two `res.partner` files live in
`models/constants.py` so the field layer and the engine cannot drift.

## Preference rows are provisioned, not subscribed to

Every cron tick calls `_ensure_prefs_for_users()` for the set of
internal users who are the Account Manager of at least one eligible
contact. Missing rows are created with the Settings defaults.

Consequences worth knowing:

* **Deleting** a preference row is harmless *and pointless* — the next
  run recreates it. **Pausing** (`active = False`) is the supported way
  to opt out; the lookup uses `active_test=False`, so a paused row is
  recognised as existing and never resurrected. (This is the same trap
  `hr_birthday_reminders` fell into in v17.0.2.32.0, where a
  `search_count` without `active_test=False` silently un-assigned paused
  users. Here it would silently re-subscribe them.)
* Changing the Settings defaults never rewrites existing rows — people
  who tuned their own intervals keep them.

## Cron flow

```
ir.cron "Contacts: Daily Birthday Reminders"   (daily @ cron_hour_utc, user_root)
 └ ResPartner._cron_partner_birthday_reminders()
     ├ _cleanup_overdue_birthday_activities()   ← drop our own expired To Dos
     ├ _refresh_partner_birthday_helpers()      ← next_birthday / proximity / eligibility
     ├ _ensure_prefs_for_users(account managers)
     └ for each active preference row:
          skip if last_run_date == user-local today   (res.users.tz, pytz, UTC fallback)
          for each enabled interval (7d / 1d / on-day):
             target = local_today + offset             (Feb 29 → Feb 28 in non-leap years)
             partners = eligible contacts born on target AND user_id == this user
             for each:  skip if a log row exists
                        7d/1d → mail.activity (deadline = birthday)
                        message_notify → private inbox note (inbox routing forced)
                        mail.template  → email to the Account Manager
                        create log row
          stamp last_run_date = user-local today
```

Every stage is individually wrapped in `try/except`: one broken contact,
user or preference row can never stop the batch.

## Idempotency and timezones

`partner.birthday.log` is the single source of truth for "already
notified?" — its UNIQUE constraint is the hard guarantee, the
`search_count` pre-check only avoids pointless work. A manual *Run
Manually* on the cron is therefore always safe.

`last_run_date` is keyed on the user's **local** date (`res.users.tz`,
UTC fallback), so the once-per-day promise holds even when the fixed UTC
firing straddles local midnight for managers in other timezones.

## Channel decisions

* **`message_notify`, not `message_post`.** A contact's chatter is
  customer-facing context shared with the whole team; internal birthday
  chatter does not belong there. `mail.thread.message_ids` excludes
  `user_notification` messages, so nothing appears on the record. It
  also skips follower fan-out — only the Account Manager is told.
* **Inbox routing is forced** (`_birthday_force_inbox_routing`): the
  `mail.notification` row is rewritten to `inbox` and the bare
  auto-queued `mail.mail` is unlinked, so the user sees the note in
  Discuss *and* receives exactly one (rich, templated) email.
* **No To Do on the day.** By the birthday itself there is nothing left
  to prepare; the on-day interval is notification + email only.
* Activity cleanup matches only summaries starting with
  `Contact birthday` (see `ACTIVITY_SUMMARY_PREFIX`), so other people's
  activities on the same contact are never deleted. The prefix is
  English — a multi-language deployment should switch to a dedicated
  `mail.activity.type`.

## Security

One role only. Because the audience is derived from `user_id`, there is
nothing to grant — every internal user is automatically responsible for
their own contacts.

| Group | Rights |
|---|---|
| `base.group_user` | read/write **own** preference row, read **own** log rows, Birthdays board via normal Contacts access |
| `group_partner_birthday_manager` ("Contact Birthday Manager") | read/write every preference row, read the whole log |
| `base.group_system` | listed explicitly on both manager rules |

`base.group_system` is on the manager rules **from day one** on purpose:
`hr_birthday_reminders` had to retrofit exactly this in v17.0.2.34.0,
where an admin who also matched a narrower "own rows only" rule was
blocked from editing other people's rows with a confusing AccessError.

Every field this module adds to `res.partner` carries
`groups='base.group_user'`. `res.partner` is readable by portal and
public users in several flows, and a birthday is personal data;
declaring the groups on the field also keeps them out of the ORM
prefetch batch for those users — the class of bug the HR module had to
fix retroactively in v17.0.2.35.0.

## UI

* **Contact form** — Birthday (hidden on companies) + read-only Next
  Birthday, next to Title / Job Position.
* **Contacts → Birthdays** — kanban (grouped by proximity) / tree /
  calendar over `[('birthday_eligible','=',True)]`, with filters
  Today / Tomorrow / Within 7 days / My contacts / No account manager.
  The board views carry `priority=99` so Odoo never picks them as the
  default views of `res.partner`.
* **Contacts → Birthday Reminders** — Reminder Preferences, Reminder
  Log. Deliberately *not* under Contacts → Configuration, which is gated
  to `base.group_system`; every internal user must reach their own
  preferences.
* **Settings → Contact Birthdays** — enable/disable, UTC hour, defaults
  for newly provisioned managers.

## Email templates

Three `mail.template` records on `res.partner`
(`mail_template_partner_birthday_7_days` / `_1_day` / `_today`), with
`email_to` overridden per recipient so the templates stay
audience-agnostic. Two conventions, both inherited as lessons:

1. **Never self-close a non-void HTML element.** `<strong t-out=""/>`
   survives `html_sanitize`, but the WYSIWYG editor later normalises it
   into an unclosed tag that swallows the following paragraphs — this
   silently wiped the HR greeting body twice (v17.0.2.20.0 / .25.0).
   Every `t-out` here has an explicit closing tag and a placeholder.
2. The card markup is **repeated per template rather than factored into
   a `t-call`**: admins edit these bodies in the WYSIWYG editor, which
   does not evaluate QWeb — a body consisting of one `t-call` would open
   as an empty, uneditable page.

Subjects and bodies disclose day and month only, never the year: a
reminder must not leak the contact's age.

## Tests

`tests/` — 28 tests, all green (see below for how to run).

* eligibility: plain contact, no birthday, company, current internal
  user, **archived** internal user (and the same after a cron refresh),
  portal user, archived contact
* dates: next occurrence always ≥ today, proximity buckets, Feb 29 →
  Feb 28 in non-leap years, both in `_birthday_next_occurrence` and in
  the matching helper
* engine: preference auto-provisioning, all three intervals, To Do only
  for the upcoming ones, private/inbox-forced notification, per-manager
  routing, idempotency (both the `last_run_date` guard and a forced
  re-run), disabled intervals, paused row, paused row not resurrected,
  contact with no Account Manager, ineligible contacts, activity
  housekeeping (ours deleted, foreign ones untouched), email to the
  manager and never to the contact

```bash
/home/coder/.venv/odoo17/bin/python odoo17_community/odoo-bin \
  -d odoo_dev --db_host=postgres --db_port=5432 --db_user=odoo \
  --db_password='postgres_password!1' \
  --addons-path=/home/coder/src/odoo/odoo17_community/addons,/home/coder/src/odoo/odoo17_enterprise/odoo/addons,/home/coder/src/odoo/jito_modules \
  -u partner_birthday_reminders --test-enable \
  --test-tags /partner_birthday_reminders --stop-after-init --no-http
```

## Install / upgrade notes

`post_init_hook` (`hooks.py`) pins `ir.cron.nextcall` to the configured
UTC hour at install time — `nextcall` cannot be expressed declaratively,
so without it the first batch would fire at whatever o'clock the module
was installed and stay a day out of step with the hour shown in
Settings.

**The hook runs on install only, never on `-u`.** If the module is
already installed and the cron's `nextcall` looks wrong, either change
the hour in Settings (which repositions it) or re-run the hook from a
shell:

```python
from odoo.addons.partner_birthday_reminders.hooks import post_init_hook
post_init_hook(env)
env.cr.commit()
```

## Gotchas

* Assigning `user_id` on a contact makes **Odoo itself** post a "You
  have been assigned" `user_notification`. It is not ours, follows the
  user's own `notification_type`, and any assertion about our
  notifications must filter it out (the test suite does).
* `next_birthday` is a read-only compute, so the calendar view is
  display-only (`create="0"`, no drag-to-reschedule) — dragging would
  try to write a computed field.
* The cron matches on day/month in Python over the eligible set rather
  than in SQL. Deliberate: it keeps the Feb-29 rule in one readable
  place. If the contact base grows past tens of thousands of birthdays,
  that is the spot to optimise.
