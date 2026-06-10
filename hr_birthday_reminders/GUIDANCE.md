# hr_birthday_reminders — Module Guidance

## What this module does

Automates employee birthday reminders driven by `hr.employee.birthday`.
A daily cron compares only **day and month** (ignoring the year), so
the module works reliably across year boundaries (Dec → Jan) and for
Feb 29 birthdays in non-leap years (it falls back to Feb 28).

Each Responsible has their **own subscription record** with their **own
subset of intervals** (7 days before, 1 day before, on the day). The
cron runs once per UTC day at the configured hour (default 06:00 UTC)
and iterates every active subscription, processing each one whose
`last_run_date` is not the user's local today.

The exact UTC hour at which the daily cron fires is exposed as a
system-wide setting under **Settings → Birthday Reminders**, alongside
a master enable/disable toggle.

## Roles

The module defines its own permission tier — it deliberately does
**not** depend on `hr.group_hr_user` / `hr.group_hr_manager` for access.

| Group | Purpose |
|---|---|
| `group_birthday_responsible` (Responsible for Greetings) | Receives the per-user reminders. Can read every subscription, edit own subscription, create new subscriptions (assigning others as Responsibles). Cannot delete. |
| `group_birthday_manager` (Birthday Reminders Manager) | Implies Responsible. Full CRUD on subscriptions and the audit log. Manager **does not** auto-receive reminders — they need a subscription of their own to receive them. |
| (none) | Regular employees see no menu, no records. |

Both groups are placed in the dedicated `module_category_birthday_reminders`
so they appear under Settings → Users → "Birthday Reminders" as a
single-select dropdown.

## Notification channels per Responsible

Every interval delivers **both** a private inbox notification and an
email (a friendly templated one — not just a system "Activity assigned"
auto-message). 7-day and 1-day intervals also create a `mail.activity`
(To Do) so the Responsible has a tangible task in their dashboard.

| Interval | Audience | Channels |
|---|---|---|
| 7 days before | Responsibles | `mail.activity` (To Do, deadline = birthday) **+** private inbox notification (`message_notify`) **+** email rendered from `mail_template_birthday_7_days`. |
| 1 day before | Responsibles | `mail.activity` (To Do, deadline = birthday) **+** private inbox notification (`message_notify`) **+** email rendered from `mail_template_birthday_1_day`. |
| On the day | Responsibles | Private inbox notification (`message_notify`) **+** email rendered from `mail_template_birthday_today`. (No activity — the day-of has no actionable "todo".) |
| Greeting (on the day) | **Employee themselves** | Email rendered from `mail_template_birthday_to_employee` sent to `work_email` → `private_email`. Result is logged with `greeting_status='sent'`/`'failed'` and surfaced as a chip in the Employees views. Independent of subscriptions — runs even with zero Responsibles. |
| Greeting failed | All active Responsibles | Private inbox notification (`message_notify` + forced inbox routing) **+** email rendered from `mail_template_birthday_greeting_failed`. Triggered when the employee greeting could not be delivered (no email, or SMTP error). |

Per-interval template lookup happens through the `EMAIL_TEMPLATE_XMLIDS`
dict at the top of `models/hr_employee.py`. The same dispatch path (the
`for emp in employees` loop in `_process_birthday_interval`) calls
`_notify_birthday_user(emp, target_date, user, interval_key)` and
`_send_birthday_email(emp, user, interval_key)` for every interval —
so adding a new interval is a one-line change in the loop plus a new
template entry in the dict.

The inbox notification is **forced into the Odoo UI for every
Responsible**, including users whose
`res.users.notification_type='email'` (e.g. `base.user_admin`).
After `message_notify` returns, `_birthday_force_inbox_routing`
rewrites the resulting `mail.notification` row to
`notification_type='inbox'` and unlinks the bare auto-queued
`mail.mail` so there is exactly one email per dispatch (the rich
templated one from `_send_birthday_email`).

Each Responsible gets independent idempotency: their own activity, own
private inbox notification, own email — all gated by the per-user log
row `(employee_id, birthday_date, interval, user_id)`.

### No system activity auto-notification

Since v17.0.2.13.0, `_schedule_birthday_activity` passes
`with_context(mail_activity_quick_update=True)` to `activity_schedule`.
Odoo skips its standard "<record_name>: <summary> assigned to you"
auto-notify in this case (see `mail_activity.py:333-337`). The
activity is still created and visible in the assignee's Activities
widget, but the redundant system message is suppressed — every
Responsible's Discuss → Inbox shows only our friendly emoji
notification per dispatch.

### Why `message_notify` rather than `message_post`

Posting via `message_post` puts a public chatter message on the
employee record. Two side effects we explicitly do **not** want:

1. **Visible to every reader of the record.** Any user with read access
   to `hr.employee` (HR Officers, Settings, every Responsible via the
   ACL) sees the message in the chatter UI.
2. **Duplicated per Responsible.** Because the per-user dedup key
   (`user_id`) is part of the log, every Responsible's subscription
   independently re-posts the same chatter message — N Responsibles =
   N identical posts on the same employee.

`message_notify` solves both:

- Odoo's `mail.thread.message_ids` One2many filters out
  `user_notification` messages (`mail/models/mail_thread.py:99`), so the
  message never appears on the public chatter.
- It does no follower fan-out (`mail/models/mail_followers.py:145`
  short-circuits for `user_notification`); only the partner listed in
  `partner_ids` is notified, routed via that user's own
  `notification_type` (inbox / email).
- Each Responsible therefore sees their own one-to-one notification in
  Discuss → Inbox, and **only their own** — never anyone else's.

## Main models

| Model | File | Purpose |
|---|---|---|
| `birthday.reminder.subscription` | `models/birthday_reminder_subscription.py` | Per-user record: `user_id`, three interval booleans, `last_run_date`, `active`. CREATE/WRITE(user_id)/UNLINK sync `group_birthday_responsible.users`. UNIQUE(user_id). UI label is "Responsible" — model name is kept as `subscription` to avoid a major-bump rename migration. |
| `birthday.reminder.log` | `models/birthday_reminder_log.py` | Idempotency log. UNIQUE(employee, date, interval, **user**). |
| `hr.employee` (extension) | `models/hr_employee.py` | Cron entry-point, per-subscription matching/scheduling/posting/emailing, plus the v17.0.2.15.0 employee-greeting flow. Three stored compute fields drive the Employees views: `next_birthday` (Date), `birthday_proximity` (Selection: today/tomorrow/this_week/later) and `birthday_greeting_state` (Selection: sent/failed — today-only). The first two depend on "today" and are refreshed at the start of every cron tick via `_refresh_birthday_helpers()`. `birthday_greeting_state` echoes the latest greeting Log row and is refreshed by `_refresh_greeting_state_today(today)` after the greeting send completes. Read paths use `sudo()` so Responsibles (no `hr.group_hr_user`) can render kanban/tree/calendar without AccessError. |
| `res.config.settings` (extension) | `models/res_config_settings.py` | Five-field settings page: reminders cron enable/disable toggle (mirrors `ir.cron.active` on `ir_cron_birthday_reminders`), reminders daily run hour in UTC (`hr_birthday_reminders.cron_hour_utc`, default 6), v17.0.2.15.0 "Send greeting email to employees" master toggle (`hr_birthday_reminders.greeting_enabled`, default True), v17.0.2.16.0 separate greeting hour in UTC (`hr_birthday_reminders.greeting_hour_utc`, default 6, mirrored to `ir_cron_birthday_greetings.nextcall`), and v17.0.2.17.0 optional banner image (Binary, stored as base64 in `hr_birthday_reminders.greeting_banner_b64`; empty → fallback to `res.company.logo`). `set_values` syncs both cron records' `nextcall` only when the corresponding hour actually changed, and persists the banner to ICP. An extra "Edit greeting template..." button on the settings page opens the underlying `mail.template` for full WYSIWYG editing. |

## Cron flow

Since v17.0.2.16.0 the module ships **two** independent daily crons.
Each one has its own configurable UTC hour and `nextcall` so the
Responsible-reminders and the employee-greeting flows can be
scheduled separately (or pinned to the same hour to preserve the
v17.0.2.15.0 single-batch behaviour).

```
ir.cron #1  (daily at cron_hour_utc — default 06:00 UTC)
  └─ HrEmployee._cron_birthday_reminders()
       ├─ _cleanup_overdue_birthday_activities()   ← drop stale "Upcoming birthday" todos
       ├─ _refresh_birthday_helpers()              ← recompute next_birthday / birthday_proximity
       │                                              (also re-fires @api.depends → birthday_greeting_state,
       │                                              so the chip stays consistent with greeting Log rows)
       └─ for each active birthday.reminder.subscription:
            └─ _birthday_maybe_run_for_subscription(sub)
                 ├─ skip if last_run_date == user-local today
                 └─ _birthday_process_subscription(sub, today):
                      └─ for each enabled interval (7d/1d/0d):
                           └─ _process_birthday_interval(target_date, interval, sub)
                                ├─ _employees_with_birthday_on(target_date)   ← sudo + Feb-29 fallback
                                └─ for each matched employee:
                                     ├─ skip if log row exists
                                     ├─ if 7d/1d → _schedule_birthday_activity(emp, …, user)
                                     ├─ _notify_birthday_user(emp, …, user, interval_key)
                                     ├─ _send_birthday_email(emp, user, interval_key)
                                     └─ create log row (with user_id)
                 └─ stamp sub.last_run_date = user-local today

ir.cron #2  (daily at greeting_hour_utc — default 06:00 UTC; v17.0.2.16.0)
  └─ HrEmployee._cron_birthday_greetings_to_employees()
       ├─ _refresh_birthday_helpers()              ← keep proximity in sync
       ├─ _send_employee_greetings(today)          ← independent of subscriptions
       │    └─ for each today-birthday employee:
       │         ├─ skip if greeting log row exists for (emp, today, 'greeting', root)
       │         ├─ email_to = _pick_employee_greeting_email(emp)  ← work_email → private_email
       │         ├─ if email_to: _send_employee_birthday_email(emp, email_to)
       │         │                + log row (greeting_status='sent')
       │         └─ else: log row (greeting_status='failed', reason='no_email')
       │                + _notify_responsibles_greeting_failed(emp, today, reason)
       │                    └─ for each active Responsible: inbox + email
       └─ _refresh_greeting_state_today(today)     ← re-projects greeting Log rows onto the chip
```

## Idempotency

`birthday.reminder.log` is the single source of truth for "did we
already notify for this?", with UNIQUE(employee, date, interval, user).

A dedicated table is safer than:
- searching `mail.activity` (user-deletable, can be marked done),
- a boolean flag on `hr.employee` (birthdays repeat yearly, no good reset signal),
- searching chatter / `mail.message` (messages can be edited or removed; emails leave no row at all).

## Timezone & DST handling

The cron fires at one fixed UTC hour globally (default 06:00 UTC).
Each Responsible's `last_run_date` is keyed on their **own local
date**, taken from `res.users.tz` — so the per-user "have we already
processed today?" check stays correct even when the global firing
straddles local midnight.

Implications:
- A Responsible east of UTC sees notifications during their morning;
  one west of UTC sees them late on their previous calendar evening
  (still pinned to their local date for idempotency).
- DST transitions in the user's own timezone are handled by `pytz`
  automatically when the per-subscription code converts UTC `now` to
  user-local time for the date computation. They no longer affect
  *when* the cron fires (it is UTC-anchored), only how a user's
  "today" is computed.
- An empty `user.tz` falls back to UTC.

To shift the global firing time (e.g. 06:00 UTC ≈ 09:00 Kyiv → choose
03:00 UTC for an earlier 06:00 Kyiv arrival), use **Settings →
Birthday Reminders → Daily run hour (UTC)**.

## Activity housekeeping

`_cleanup_overdue_birthday_activities()` runs at the start of every cron
tick. It deletes `mail.activity` rows on `hr.employee` whose summary
starts with `Upcoming birthday` and whose `date_deadline <= today`. The
intent: by the time the deadline reaches today, the on-day chatter+email
takes over — the residual activity is dashboard noise. Match is by
English-summary prefix; multi-lang deployments need a stronger marker
(custom activity type or flag field).

## Constraints / patterns to be aware of

- `hr.employee.birthday` is `groups="hr.group_hr_user"`. The cron runs
  as root, but every helper still calls `sudo()` explicitly so reads
  remain correct when called from any context.
- The `next_birthday` computed field has **no `groups=` restriction** —
  Responsibles can see the upcoming-birthday calendar even though they
  do not have `hr.group_hr_user`. The compute itself runs `sudo()`.
- Booleans on `birthday.reminder.subscription` default to `True` —
  fresh subscriptions immediately do something sensible. The cron's
  UTC hour is governed by the system-wide setting
  (`ir.config_parameter` `hr_birthday_reminders.cron_hour_utc`,
  default `6`). The cron's enabled/disabled state mirrors
  `ir.cron.active`, exposed as a master toggle in Settings.
- Subscription `create()` flips `res.users.notification_type` to `inbox`
  for the new Responsible (Odoo's default 'email' would skip Discuss).
  Existing Responsibles are backfilled by the v17.0.2.7.0 migration.
  Users can still revert via Preferences → Notification = "Handle by
  Emails" if they really only want email.
  **Exceptions (since v17.0.2.9.0):** the auto-flip is skipped for
  `base.user_root` (`__system__`), `base.user_admin` (`admin`), and any
  `share=True` user. Reason: the `mail` SQL constraint
  `CHECK (notification_type='email' OR NOT share)` rejects share users
  with 'inbox', and `base/data/res_users_data.xml` reloads admin's
  `groups_id` to `[Command.set([])]` during `-u base`, momentarily
  turning admin share=True. With 'inbox' set, that flush fails and the
  registry load aborts (workspace fails to boot). The same filter is
  applied in the v17.0.2.7.0 migration. The v17.0.2.9.0 migration
  cleans up any system / share user that was switched to 'inbox' by an
  earlier version.
- `group_birthday_responsible` gets read-only access on `hr.employee`
  (ACL row in `ir.model.access.csv`), so all Responsibles can open the
  Birthday Reminders → Employees menu without `hr.group_hr_user`.
  Field-level groups still apply: private fields like `birthday`
  itself stay hidden for non-HR users; the `next_birthday` and
  `birthday_proximity` we add are intentionally not gated.
- Group-membership semantics: `group_birthday_responsible` tracks the
  **existence** of a subscription (active or paused), not its `active`
  flag. Pausing (`active=False`) keeps the user in the group so they
  can read/edit their own subscription and un-pause later. Only
  `unlink()` (or reassigning `user_id`) actually leaves the group.
- All XML data files except `security/birthday_security.xml` are inside
  `<data noupdate="1">` so admins can edit cron / template / rules at
  runtime without `-u` undoing their changes. The groups themselves are
  loaded with `noupdate="0"` so role definitions update on upgrade.

## v17.0.2.34.0 — System admin record-rule fix on subscription + log

**Bug reproduced by user:** admin opens `Birthday Reminders →
Responsibles`, tries to toggle `Active` (or any of the three notify
flags) on someone else's row inline from the tree, and gets:

```
AccessError: Sorry, Administrator (id=2) doesn't have 'write' access to:
  Birthday Reminder Subscription, John Doe1 (birthday.reminder.subscription: 17)
Blame the following rules:
  birthday.reminder.subscription: responsible write own
```

**Root cause.** Admin holds three relevant groups:
- `base.group_system` ✓
- `group_birthday_responsible` ✓ (via own subscription + the daily
  self-heal cron added in v17.0.2.31.0)
- `group_birthday_manager` ✗

The Manager rule `rule_subscription_manager_all` was scoped to
`group_birthday_manager` only — admin didn't qualify. The only
write-rule that *did* match admin's groups was the Responsible
"write own" rule, with domain `[('user_id', '=', user.id)]`. So
inline edits on rows belonging to other users hit AccessError on
flush, even though the form widgets rendered as editable. The same
asymmetry quietly narrowed admin's `Reminders Log` view to
"own + greetings" — admin couldn't see log rows belonging to other
Responsibles.

**Fix.** Add `base.group_system` to the two Manager rule's `groups`:
- `rule_subscription_manager_all`
- `rule_log_manager_read_all`

With these two two-line edits, system admins get the full-CRUD /
read-all rule alongside the per-Responsible restriction. Manager
users (without `base.group_system`) are unchanged — they still get
the same Manager rule via `group_birthday_manager`. Non-system
Responsibles are still bound to their per-user write/read scopes.

**ACL is unaffected** — admin already had `1,1,1,1` on subscription
via `access_birthday_reminder_subscription_system`. ACL is the
outer gate; record rules are the inner filter. The fix tunes the
inner filter only.

**No migration** — `security/birthday_security.xml` lives in
`<data>` (not `noupdate`), so `-u hr_birthday_reminders` re-loads
the rule records with the broadened `groups` set.

---

## v17.0.2.33.0 — Revert Manager-facing menus, configuration is admin-only again

v17.0.2.30.0 introduced two new menu entries under **Birthday
Reminders** to give Birthday Reminders Managers a self-service
configuration surface:

- **Configuration** (sequence=2) — banner, hours, alert settings
- **Alert History** (sequence=15) — audit trail of watchdog alerts

After operating with that for a while the decision was to **revert
both menus**: all module configuration is admin-only again, available
exclusively via **Settings → Birthday Reminders**. The sidebar is back
to its lean four-menu layout (Health Check, Responsibles, Reminders
Log, Employees).

### What was removed

- `views/birthday_reminder_config_views.xml` — file deleted
- `views/birthday_reminder_alert_views.xml` — file deleted
- `models/birthday_reminder_config.py` — TransientModel deleted (was a
  facade over the same ICP keys Settings already manages — pure dead
  code without a UI)
- Three ACL rows for `birthday.reminder.config` in `ir.model.access.csv`

### What was kept

- `models/birthday_reminder_alert.py` — the model **stays** because
  `_send_birthday_health_alert` (in `hr_employee.py`) anchors its
  `message_notify` call to a `birthday.reminder.alert` record. Without
  a persistent thread anchor the Discuss Inbox link would orphan as
  soon as the auto-vacuum cleared TransientModel rows. The model is
  no longer browsable from the sidebar — view it via Settings →
  Technical → Database Structure → Models if needed.
- `mail_template_health_alert.xml` — both templates intact.
- Watchdog cron — fires every 6 hours, emails admins + Managers when
  the dashboard turns red.
- `group_birthday_manager.implied_ids` still includes
  `mail.group_mail_template_editor`. Per user decision: Managers can
  still edit `mail.template` records via the standard Settings →
  Technical → Email Templates path, even without the deleted
  Configuration page.
- Health Check menu — still in the sidebar (read-only for
  Responsibles; the Manager-only Run-Now buttons in the header remain
  Manager-gated).

### How to configure now (admin)

`Settings → Birthday Reminders` exposes every knob that used to be
on the Configuration page — same persistent state (ICP keys + cron
records), single source of truth, admin-only:

- Reminders block: enable + hour
- Greeting block: enable + hour + banner upload + "Edit greeting
  template..." button
- Alert block (added in v17.0.2.30.0): enable + repeat-hours

---

## v17.0.2.32.0 — Fix paused-subscription removed from group on cron tick

A dormant bug in `_sync_responsible_group`
(`models/birthday_reminder_subscription.py:162`) became visible after
v17.0.2.31.0 added daily self-heal. The helper used
`Sub.search_count(...)` to ask "does this user have any subscription
at all?", but Odoo's default `active_test=True` quietly excluded
paused (`active=False`) rows from the count. So a paused subscription
made `has_any=0` → the user was removed from the group on the next
cron tick, even though the docstring explicitly promises:

> `active=True/False → group membership unchanged`

Before v17.0.2.31.0 the bug was harmless because the create/write
hooks only called `_sync_responsible_group` when `user_id` changed —
not when the user toggled their own `active` flag — so the helper
was never invoked on a pause. The new daily self-heal **does** invoke
it on every cron tick, which exposed the contract violation.

**Fix:** one-line. `Sub.sudo()` → `Sub.sudo().with_context(active_test=False)`.
The helper now counts both active and paused rows, matching the
documented contract.

**User-visible effect:** an admin (or any Responsible) can pause
their subscription from the Responsibles tree without losing access
to the Birthday Reminders menu. They stay in the group, the cron
skips them per the existing `_birthday_maybe_run_for_subscription`
logic, and they can flip `active=True` back at any time. Deletion
(unlink) of the subscription is the only way to actually leave the
group — which matches the visible Delete vs. Pause distinction in
the tree view.

---

## v17.0.2.31.0 — Daily self-heal of `group_birthday_responsible`

**Problem.** v17.0.2.29.0 introduced a defensive migration that
re-syncs `group_birthday_responsible` membership against the set of
subscription holders, fixing the `-u base` drift (where
`base/data/res_users_data.xml` does `Command.set([])` on
`base.user_admin.groups_id` and strips custom groups). v17.0.2.30.0
added a similar resync in its own migration. **But Odoo migrations
only run on version-bump**, so any `-u base` that happens **between**
module upgrades leaves admin out of the group until the next bump or
a manual shell command.

The Manager → `mail.group_mail_template_editor` link auto-restores on
every `-u hr_birthday_reminders` (it lives in the XML `implied_ids`
which Odoo data-loads on every upgrade), but the subscription →
group_birthday_responsible link cannot — it is computed dynamically
in `_sync_responsible_group`, not declared in XML.

**Fix.** Call `_sync_responsible_group` from the daily reminders cron
itself, via a new tiny helper `_birthday_self_heal_group_membership`.
Idempotent — if no drift, zero writes and nothing logged. If drift
exists, the cron heals it within 24 hours and logs one INFO line for
audit. Wrapped in try/except so a self-heal failure can never cascade
into the rest of the reminders cron.

**Why daily, why in reminders cron**:
- Daily resolution is enough: drift is triggered by `-u base`, which
  is rare (once per Odoo core upgrade).
- The reminders cron already iterates subscriptions; group membership
  is the same source-of-truth view on those subs. Same code locality.
- Greetings cron does not touch subscriptions, so adding self-heal
  there would be incidental.
- Health watchdog runs every 6h — overkill for a once-per-month drift
  event, and watchdog is about alerting, not maintenance.

**Code locality**: `models/hr_employee.py:_birthday_self_heal_group_membership`
(new helper, ~25 lines) + one-line call from
`_cron_birthday_reminders` after `_refresh_birthday_helpers` and
before the subscription loop. No new schema, no new data, no new ACL,
no new view, no migration script.

**Operational consequence.** Admins no longer need to remember the
"after `-u base`, run `-u hr_birthday_reminders` to restore admin's
groups" rule from v17.0.2.30.0's GUIDANCE — the daily cron handles it
silently. If you want immediate recovery without waiting for the next
cron tick (e.g., right after `-u base`), the watchdog cron-button
`Run Reminders Cron Now` on the Health Dashboard triggers a manual
fire which also runs the self-heal.

---

## v17.0.2.30.0 — Health Watchdog Alerting + Manager-level Configuration

Two related additions, bundled into one version because they share an
audience (admins + Birthday Reminders Managers).

### Part A — Health Watchdog Alerting

**Problem:** Health Dashboard existed since v17.0.2.26.0, but **nobody
was told** when status turned red. Manager had to manually open the
page. In production this meant outages could sit unnoticed for days.

**Solution:** A new cron, `ir_cron_birthday_health_watchdog`, fires
every 6 hours. It creates a fresh `birthday.reminder.health` record,
reads `overall_status`, and:

- **`ok → danger`** → emits one **degraded** alert
- **`danger → danger`** with `last_alert_at` older than `repeat_hours`
  → emits another **degraded** alert (escalation nag)
- **`danger → ok`** → emits one **recovered** alert (one-shot
  confirmation)
- All other transitions → no-op

Each emission persists a `birthday.reminder.alert` row (new model)
with the kind, status snapshot, message, and notified partners. This
serves two purposes:

1. `message_notify` anchors to a stable record (TransientModel rows
   are auto-vacuumed and would orphan inbox links)
2. Managers can open **Birthday Reminders → Alert History** and see
   the audit trail — when the system flagged something, what it
   said, whom it told.

Channels per alert:

- **Inbox** notification (subtype `mail.mt_note`) to every admin +
  manager partner
- **Email** via `mail_template_birthday_health_alert` (for `degraded`)
  or `mail_template_birthday_health_recovered` (for `recovered`)

Anti-spam state lives in two ICP keys:

- `hr_birthday_reminders.alert_last_status` — `'ok'` / `'danger'` /
  `'none'`
- `hr_birthday_reminders.alert_last_at` — ISO Datetime of last
  degraded emission

Severity threshold is hardcoded as `('danger',)` for v1 — `warning`
is intentionally below threshold because a one-cycle hiccup is not
worth waking anybody. The Settings knob to relax this can come
later.

Audience: union of `base.group_system` users + `group_birthday_manager`
users, deduplicated by `partner_id`. `base.user_root` is filtered out
(it's a cron-only account with no inbox to read). If both groups are
empty, the watchdog logs a warning and does nothing.

Two Settings knobs (also exposed on the new Configuration page):

- `birthday_alert_enabled` — master switch (default True)
- `birthday_alert_repeat_hours` — escalation interval (default 24h)

### Part B — Manager-level Configuration page

**Problem:** All knobs (banner, hours, enable flags, alert settings)
were behind `Settings → Birthday Reminders`, which is gated to
`base.group_system`. Managers couldn't change the greeting banner or
text without administrator help.

**Solution:** A new `birthday.reminder.config` (TransientModel) and
menu entry `Birthday Reminders → Configuration` (sequence=2). Form
mirrors the Settings card with three blocks: Reminder Schedule,
Employee Greeting (incl. banner upload + Edit template shortcut),
Health Alerts. Both UI surfaces (Settings and Configuration) read and
write the **same** ICP keys + `ir.cron` records — single source of
truth, no duplicate persistence.

Write access for the Configuration page:

- `group_birthday_manager` and `base.group_system` → full
- `group_birthday_responsible` (without Manager) → read-only (fields
  rendered `readonly="not is_editable_by_current_user"`)
- Defense-in-depth: each inverse method calls `_assert_writable()`
  and raises `AccessError` if the caller is neither Manager nor
  admin — so XML-RPC bypass of the UI gate is also blocked.

To make the **"Edit greeting template..."** shortcut actually work
(it opens the underlying `mail.template` form for full WYSIWYG
editing), we widened `group_birthday_manager.implied_ids` to also
include `mail.group_mail_template_editor`. This auto-propagates to
every current Manager at upgrade time.

### Files added / modified

Added: `models/birthday_reminder_alert.py`,
`models/birthday_reminder_config.py`,
`views/birthday_reminder_alert_views.xml`,
`views/birthday_reminder_config_views.xml`,
`data/mail_template_health_alert.xml`,
`migrations/17.0.2.30.0/post-init-alert-state.py`.

Modified: `models/hr_employee.py` (watchdog + send_alert methods),
`data/ir_cron_data.xml` (new watchdog cron),
`models/res_config_settings.py` (2 alert fields),
`views/res_config_settings_views.xml` (Alerting block),
`security/birthday_security.xml` (Manager implies
`mail_template_editor`), `security/ir.model.access.csv` (6 new ACL
rows for the 2 new models), `__manifest__.py`, `GUIDANCE.md`.

### Operational note

After running `-u base` (which strips custom groups from
`base.user_admin` / `base.user_root` — see v17.0.2.29.0 for context),
follow with `-u hr_birthday_reminders` — the v17.0.2.30.0 migration
re-runs the defensive group resync AND re-asserts the manager →
`mail_template_editor` implication so Managers don't lose the
edit-greeting capability silently.

---

## v17.0.2.29.0 — Defensive group re-sync after `-u base`

Bug-fix uncovered while debugging v17.0.2.28.0: **Admin had an active
subscription but was missing from `group_birthday_responsible`** —
so the Birthday Reminders menu hid in spite of the existing
subscription. Cross-check confirmed a parallel drift: **Tester HR
Officer was in the group without any subscription**.

### Root cause

`-u base` reloads `base/data/res_users_data.xml`, which contains:

```xml
<field name="groups_id" eval="[Command.set([])]"/>
```

for `base.user_root` and `base.user_admin`. That XML expression
**clears every custom group** on these two users for the duration
of the flush; standard base groups are re-added immediately, but
custom groups like `group_birthday_responsible` are not. Admin
silently drops out of the Responsibles group even though their
subscription record is untouched. (Tester HR Officer's drift in
the opposite direction was likely manual fiddling at some point —
group membership added without a subscription — which had not been
cleaned up.)

The v17.0.2.8.0 migration that originally re-synced the group
runs only on the one-time bump to .8.0; every subsequent `-u base`
re-strips admin without anyone re-adding them.

### Fix

New migration `migrations/17.0.2.29.0/post-resync-groups-defensive.py`
walks the union of (current group members) + (every subscription
user) and lets `_sync_responsible_group` (the same idempotent
helper used by `create`/`write`/`unlink`) decide who should be
in or out. Both drift directions are corrected.

### Operational recommendation

If you ever run `-u base` (or `-u all`), follow it with
`-u hr_birthday_reminders` — the v17.0.2.29.0 migration will
re-run and patch admin (or anyone else whose custom groups got
flushed) back into `group_birthday_responsible`. This is now a
re-usable pattern: any future version can include the same
migration body to mop up after a base reload.

---

## v17.0.2.28.0 — Health Dashboard: ACL for base.group_system

Bug-fix on top of v17.0.2.27.0. Administrators (`base.user_admin`,
holding `base.group_system` but not necessarily
`group_birthday_responsible` — group membership is gated by having an
active subscription, and some installs strip system users from the
auto-managed group) could not see the **Health Check** menu, while
regular Responsibles could.

Cause: the new `birthday.reminder.health` model shipped without a
`base.group_system` ACL row, matching the asymmetry already corrected
on `birthday.reminder.log` and `birthday.reminder.subscription` (both
have a `_system` access row). Without an ACL entry for admins, Odoo
hides the menu whose underlying server action targets an
inaccessible model — exactly what the user saw.

Fix: one extra line in `security/ir.model.access.csv`:

```
access_birthday_reminder_health_system,birthday.reminder.health system,
  model_birthday_reminder_health,base.group_system,1,1,1,1
```

Same triplet pattern (`_responsible` / `_manager` / `_system`) the
other two models in the module already follow.

The deeper question of *why admin isn't in `group_birthday_responsible`
despite an active subscription* is a separate concern — group
membership management lives in `_sync_responsible_group` and may have
been side-effected by earlier migrations (v17.0.2.7.0–9.0 dealt with
system/share user handling). Not addressed here — the ACL fix is
enough to unblock the dashboard for admins.

---

## v17.0.2.27.0 — Health Dashboard: sudo() for ir.cron read

Bug-fix on top of v17.0.2.26.0. Opening **Birthday Reminders → Health
Check** as a Birthday Reminders Responsible (without `base.group_system`)
raised:

```
AccessError: You are not allowed to access 'Scheduled Actions' (ir.cron) records.
```

`ir.cron` is restricted to `base.group_system` system-wide, so the
compute method's read of `cron.active`/`lastcall`/`nextcall` was denied
even though the dashboard's own ACL grants Responsibles read access to
`birthday.reminder.health`. Fix: promote the cron browse-record to
`sudo()` for the four status-display reads only (`_populate_cron_fields`
in `models/birthday_reminder_health.py`). Does not grant any write
access — pure display promotion, same pattern the cron-flow methods
already use throughout `hr.employee`.

Managers (`base.group_system` implied) were unaffected — they could
read `ir.cron` directly.

---

## v17.0.2.26.0 — Health Dashboard

One-screen operational view of the module: opens at **Birthday
Reminders → Health Check** (top of the menu, sequence=1). Visible to
both Responsibles and Managers; the "Run Cron Now" buttons in the
header are gated to Managers only.

### Model

`birthday.reminder.health` is a `TransientModel` — every menu open
creates a fresh record, every field is a non-stored compute. No
persistent schema, no migration script, auto-vacuum cleans the leftover
rows on the standard `_transient_max_hours` schedule.

Source of every signal:

| Field | Reads from |
|-------|-----------|
| `reminders_cron_*` | `ir.cron` (xmlid `ir_cron_birthday_reminders`) |
| `greetings_cron_*` | `ir.cron` (xmlid `ir_cron_birthday_greetings`) |
| `today_birthdays` | `hr.employee._employees_with_birthday_on(today)` |
| `today_reminders_sent` | `birthday.reminder.log` (intervals 7d/1d/on-day, notified_at >= today) |
| `today_greetings_sent` / `_failed` | `birthday.reminder.log` (interval=greeting, status=sent\|failed, notified_at >= today) |
| `subscriptions_active` | `birthday.reminder.subscription` (active=True) |
| `subscriptions_stale` | active subs whose `last_run_date != local-today-in-user-tz` |
| `recent_failures_30d` | failed greeting log rows in last 30 days |

### Cron-status thresholds

User-facing rule: "красним якщо довше за notification period". The
notification period is 24h (daily cron), buffered by 2h of normal
scheduler drift:

| Age since `lastcall` | Status | Colour |
|----------------------|--------|--------|
| `active=False` or `lastcall is None` | `danger` | red |
| ≤ 26h | `ok` | green |
| (26h, 30h] | `warning` | yellow |
| > 30h | `danger` | red |

Side-check: if `nextcall < now − 2h` the scheduler itself is stuck →
`danger` regardless of lastcall. Constants live at the top of
`models/birthday_reminder_health.py` (`CRON_AGE_OK_HOURS`,
`CRON_AGE_WARNING_HOURS`, `CRON_NEXTCALL_OVERDUE_HOURS`).

### Overall status

Worst-of aggregation:
- Cron `danger` → overall `danger`.
- `today_greetings_failed > 0` → overall `danger`.
- `subscriptions_stale > 0` → overall at least `warning` (single
  missed run is recoverable on the next cron tick — not yet
  red).
- Otherwise inherit the worst sub-status.

`overall_message` lists every non-OK signal so the user sees *why*
the banner is red without scrolling.

### Header actions

- **Refresh** — re-opens the dashboard with a freshly-created
  transient record so every compute re-runs against the latest data.
- **Run Reminders Cron Now / Run Greetings Cron Now** — Manager-only
  shortcuts that call the same cron entry-points as the scheduler.
  Safe to mash repeatedly: the log's UNIQUE constraint guarantees no
  duplicate notifications. Both buttons emit a confirm-dialog before
  firing.

### Drill-downs

- `subscriptions_stale > 0` → "View stale →" opens a filtered
  Responsibles tree.
- `recent_failures_30d > 0` → "View failed greetings →" opens a
  filtered Reminders Log (uses the existing v17.0.2.24.0 rule that
  lets Responsibles read greeting rows).

### Troubleshooting checklist

When `overall_status != ok`:

1. **Cron `danger`** → open
   *Settings → Technical → Scheduled Actions* and check
   `HR: Daily Birthday Reminders` / `HR: Daily Birthday Greetings`:
   is `active` checked? Is `nextcall` in the past? Has any traceback
   landed in the Odoo log around the configured UTC hour?
2. **Greeting `failed` today** → click "View failed greetings"; the
   `greeting_failure_reason` field is either `no_email` (employee
   has neither `work_email` nor `private_email`) or `send_error`
   (SMTP raised). Fix the underlying cause; the next cron tick
   re-attempts because failed rows still count as "logged" — re-emit
   manually by deleting the row and clicking "Run Greetings Cron
   Now".
3. **Subscriptions stale** → user's `tz` is set to a value that
   crosses midnight differently from the cron-hour user. Either
   correct the tz on the user, or wait for the next cron tick.

### Shell snippet (for monitoring scripts / CI)

```python
# Read overall health from outside the UI
rec = env['birthday.reminder.health'].create({})
print(rec.overall_status, rec.overall_message)
# Exit non-zero from a CI job if not green
exit(0 if rec.overall_status == 'ok' else 1)
```

### Out of scope (deferred)

- Email/inbox auto-alert when `overall_status` flips to danger —
  separate cron + `mail.template`, planned for a later version.
- `board.board` integration ("Add to My Dashboard") — possible from
  the UI once the form view exists, no extra code required.
- Trend graph (greetings/day over 90 days) — a `<graph>` view on
  `birthday.reminder.log` would answer "what happened", not
  "are we healthy now".

---

## v17.0.2.25.0 — Fix `<strong t-out/>` self-close corruption

Same class of bug as v17.0.2.20.0 (`<t t-set/>` self-close). HTML
sanitisation strips the trailing slash from self-closing non-void
elements like `<strong/>` (HTML5 doesn't recognise these as
self-closing). On its own that produced a harmless empty `<strong>`
that QWeb's `t-out` directive overwrote correctly.

**But** when admin opens the body in Odoo's WYSIWYG editor (Settings
→ "Edit greeting template…"), the editor normalises the malformed
structure unpredictably. In our case it wrapped subsequent paragraphs
inside the unclosed `<strong>`, which QWeb then **replaced** with
`object.name` value — wiping out the 4 body paragraphs.

### Observed corruption

```html
<!-- before (clean) -->
<p>Hi <strong t-out="object.name"/>,</p>
<p>Wishing you a wonderful Happy Birthday!</p>
...

<!-- after (corrupted by WYSIWYG) -->
<p>Hi <strong t-out="object.name">,</strong></p>
<strong t-out="object.name">
    <p>Wishing you a wonderful Happy Birthday!</p>
    <p>Today is all about you...</p>
    <p>Enjoy your special day...</p>
    <p>Best regards, <strong>Jito Team</strong></p>
</strong>
```

Rendered output: only `Hi Dmytro Poltavets` + footer. The 4 body
paragraphs lost — t-out replaced them with the name value.

This was caught when running real SMTP delivery to Mailpit and
inspecting actual rendered HTML in email client (the prior shell
tests used `_render_field` which exposed the same content but the
issue wasn't visible because we only string-matched for marker
phrases — they were in body_html as raw text, just not in the
rendered output).

### Fix: explicit-close pattern

```html
<p>Hi <strong t-out="object.name">NAME</strong>,</p>
```

The `NAME` placeholder is overwritten by QWeb at render-time with
`object.name`. The explicit `</strong>` close prevents future
WYSIWYG normalisation from mangling siblings — the tag is now
unambiguously closed.

### Migration

`migrations/17.0.2.25.0/post-fix-strong-tout.py` detects the
corrupted (or pre-v25) body and rewrites with the safe pattern.
Idempotent — re-running detects the v25 marker `<strong t-out…>NAME</strong>`
and skips.

### Lessons (combined with v20)

For mail.template body_html:
- **Never self-close non-void HTML elements** like `<strong/>`,
  `<span/>`, `<div/>`, `<t/>`. HTML5 doesn't recognise these — they
  become open tags that swallow siblings during sanitisation /
  WYSIWYG edit.
- Use **void elements** like `<img>`, `<br>`, `<input>` self-closed.
- Use **`<t t-out="...">PLACEHOLDER</t>`** with explicit close for
  text substitution wrappers.
- Use **`t-att-NAME`** on void elements (e.g. `<img t-att-src="…"/>`)
  rather than wrapping `<t t-if>` blocks for conditional rendering.

These rules survive both `html_sanitize` on write AND Odoo's WYSIWYG
editor opening/saving the template.

## v17.0.2.24.0 — Responsibles see greeting log rows

Until now `rule_log_responsible_read_own` (record rule on
`birthday.reminder.log`) had domain `[('user_id', '=', user.id)]`,
so a Responsible only saw rows where they were the recipient.
Greeting rows are stored with `user_id = base.user_root.id` and
`interval = 'greeting'` (system-emitted, not per-Responsible) —
which made them invisible to Responsibles. A Responsible looking
at Reminders Log had no way to verify "did the system already
greet today's birthday employee?"

### Domain now

```
['|',
  ('user_id', '=', user.id),
  ('interval', '=', 'greeting')]
```

Responsibles still see only their own per-user reminder rows OR
any system-emitted greeting row. No other Responsible's rows
become visible. Manager rule (`rule_log_manager_read_all`)
unchanged — managers always see everything.

### Read-only

`perm_read` only — `perm_write/create/unlink` stay False. Even
with broader visibility, Responsibles cannot edit/delete log
rows. Greeting rows are exclusively system-managed.

### Migration

`migrations/17.0.2.24.0/post-extend-log-rule.py` rewrites the
existing rule's `domain_force`. The XML lives in
`<data noupdate="1">`, so on `-u` Odoo does NOT auto-import
changes to the rule fields — explicit migration is required.
Conservative: only overwrites if the current domain matches the
old v23-and-earlier shape; admin-customised domains are
preserved.

### Why this matters operationally

In a typical Jito-deploy: a Responsible opens Reminders Log
each morning to plan personal greetings (cards, treats). Before
this change they'd see only their own reminders (e.g. "you'll be
reminded for John on Friday") — but not the fact that the
automated greeting email had already gone out today to Anna. Now
they see Anna's greeting row with `interval='greeting'`,
`greeting_status='sent'` — and can plan accordingly.

## v17.0.2.23.0 — Per-row editability on Responsibles views

DB-level security on `birthday.reminder.subscription` was already
correct (record rules in `security/birthday_security.xml`):

- Responsible can **read** every subscription (so they see who else
  is on the roster).
- Responsible can **write** only on rows where `user_id == user.id`
  (their own).
- Manager / `base.group_system` admin can write anywhere.

But the **UI** misled them: opening a colleague's subscription
showed all fields as normal editable inputs. A Responsible who
didn't notice the row wasn't theirs would tweak a checkbox, hit
Save, and get an `AccessError`. Functionally safe, visually
confusing.

### Fix — `is_editable_by_current_user` compute Boolean

New non-stored compute field on `birthday.reminder.subscription`:

```python
is_editable_by_current_user = fields.Boolean(
    compute='_compute_is_editable_by_current_user',
    compute_sudo=False,
)

@api.depends('user_id')
def _compute_is_editable_by_current_user(self):
    user = self.env.user
    uid = self.env.uid
    is_admin = (user.has_group('hr_birthday_reminders.group_birthday_manager')
                or user.has_group('base.group_system'))
    for rec in self:
        rec.is_editable_by_current_user = is_admin or rec.user_id.id == uid
```

`compute_sudo=False` is **critical** — with sudo the compute would
run as root and always return True. `store=False` because the
answer depends on the current request's `env.user`, not on any
row state.

### Bound to views via `readonly="not is_editable_by_current_user"`

**Tree view:** all 4 editable fields (`active`, 3 × `notify_*`)
get `widget="boolean_toggle"` for inline click-to-toggle plus the
readonly binding. Other Responsibles' rows render with greyed-out
toggles that don't respond to click. A hidden
`<field name="is_editable_by_current_user" column_invisible="True"/>`
makes the field available for the readonly expression.

**Form view:** the same 4 editable fields plus `user_id` are
readonly-bound. The view embeds the field invisibly via
`<field name="is_editable_by_current_user" invisible="1"/>`.
`user_tz` and `last_run_date` were already display-only — no
change.

### Defence in depth

Two independent layers now:

1. **UI** (this release): non-editable fields look non-editable.
2. **DB** (existing): record rules still throw `AccessError` if
   anyone bypasses the UI and attempts a write.

Even if a Responsible somehow tweaks the DOM in their browser and
sends a write request, the record rule rejects it server-side.

### No migration needed

`is_editable_by_current_user` is a non-stored compute — no
schema change, no data migration. The view changes are auto-applied
on `-u hr_birthday_reminders` (XML data files are re-imported with
the new arch on every module update — `<data>` block is not
`noupdate="1"` for views).

## v17.0.2.22.0 — Static Jito banner as WYSIWYG-visible default

v17.0.2.21.0 made the banner render correctly in actual emails
(via PNG/JPEG MIME detection) and in the Preview wizard (since
that evaluates QWeb). But the **WYSIWYG editor** in the Email
Templates form — which is what admins see when they click
"Edit greeting template…" from Settings — does **not** evaluate
QWeb directives. It shows `body_html` verbatim. So the
`<img t-att-src="...">` element had no real `src` attribute,
and the editor showed a broken-image placeholder.

This made the body look incomplete in the editor even though
real outgoing emails were perfect, confusing admins.

### Fix — static `src` placeholder pointing to a module asset

The Jito banner is now shipped as a module asset at
`static/src/img/banner.png` (13 KB PNG, 360×160 px). The
`<img>` element has both a static `src` and a dynamic
`t-att-src`:

```xml
<img alt="Jito banner"
     src="/hr_birthday_reminders/static/src/img/banner.png"
     style="…"
     t-att-src="(custom-banner data URI if uploaded else /hr_birthday_reminders/static/src/img/banner.png)"/>
```

QWeb-rendered output (sent emails, Preview wizard):
`t-att-src` evaluates and overrides the static `src` — uploaded
custom banner wins if present; otherwise the same Jito static
asset.

QWeb-unaware contexts (WYSIWYG editor, raw HTML inspection,
unprocessed template body): the static `src` is what the browser
sees → it renders the shipped Jito banner.

### Fallback simplification

Previous fallback was `/web/image/res.company/<id>/logo` —
useful for a generic deployment. The module is now Jito-specific
(signature reads "Jito Team", banner ships with the module), so
the company-logo fallback no longer makes sense. Both the static
`src` and the QWeb fallback inside `t-att-src` point at the same
module asset URL.

### Static asset registration

The PNG sits under `static/src/img/` — Odoo's standard location.
No need to declare it anywhere; Odoo's HTTP layer serves
`/<module>/static/**` automatically.

### Migration

`migrations/17.0.2.22.0/post-static-banner.py` overwrites the
body when it detects any of the pre-v22 markers
(`<t t-set="banner_b64">` from v17–19, `data:image/*` from v20,
or `startswith('iVBOR')` from v21). Already-migrated bodies are
identified by the static-asset URL marker. Admin-customised
bodies are preserved.

## v17.0.2.21.0 — Fix banner MIME type

v17.0.2.20.0 fixed the QWeb evaluation issue (banner `<img>` was
finally produced in the rendered body). But the embedded data URI
used MIME type `image/*` (with an asterisk) — **not a valid MIME
per RFC 6838**. Browsers and email clients refuse to render an
image with an unknown / wildcard MIME, so the banner showed as a
blank space / broken-image icon both in Email Templates Preview
and in actual outgoing emails.

### Fix — detect MIME from base64 prefix

Inline detection in the `t-att-src` ternary:

| Base64 prefix | Real MIME | Source format |
|---|---|---|
| `iVBOR…` | `image/png` | PNG |
| `/9j/…` | `image/jpeg` | JPEG |
| (other) | `image/png` (default) | unknown — most common is PNG |

The detection runs at render time via a Python `startswith` check
on the ICP-stored base64 string. No new helper function or computed
field — the entire expression sits in `t-att-src` (ugly multi-line
ternary but self-contained).

### Bonus fix — fallback URL safety

The fallback URL `'/web/image/res.company/%s/logo' % object.company_id.id`
would interpolate `None` when `object` is None (Email Templates
Preview without a selected record). Wrapped with a guard:
`object.company_id.id if object and object.company_id else 1` —
falls back to company id 1 so the URL is always well-formed.

### Migration

`migrations/17.0.2.21.0/post-banner-mime-fix.py` detects the
v17.0.2.20.0 broken-MIME marker (`data:image/*;base64`) and
overwrites. Idempotent via the detection-logic marker
(`startswith('iVBOR')`).

### What this means for outgoing emails

PNG and JPEG uploads now render correctly in:

- Email Templates Preview (in Odoo backend)
- Outlook desktop / web
- Gmail web / mobile
- Apple Mail
- Most other modern clients

GIF / WebP uploads fall back to `image/png` MIME — modern clients
typically handle the mismatch via content-sniffing (you'll see the
image), but for strict clients (e.g., some old Outlook versions)
PNG/JPEG is safer.

## v17.0.2.20.0 — Fix banner rendering (HTML-sanitiser bug)

A silent rendering bug has been present since v17.0.2.17.0: the
banner band rendered **empty** in actual emails even though static
inspections of `body_html` showed the correct `<t t-set>` /
`<t t-if>` / `<t t-else>` structure. Symptoms:

- `tmpl.body_html` contains `data:image/*;base64`, `<img t-attf-src=…>`,
  the company-logo fallback URL — everything looks right.
- But `tmpl._render_field('body_html', [emp_id])` produces an empty
  banner `<td>` — no `<img>` tag at all in the rendered output.
- Users would receive emails with a blank banner area despite
  uploading a custom banner.

### Root cause

The `body_html` field is stored as **HTML** and passes through
`html_sanitize` on write. The sanitiser strips the trailing slash
from self-closing non-void tags like `<t t-set="x" t-value="y"/>`,
turning it into `<t t-set="x" t-value="y">` — an open tag with the
rest of the conditional (`<t t-if>` / `<t t-else>`) sitting inside
as its body. QWeb then evaluates `t-set` with that body **as the
variable's value** rather than evaluating `t-value`, so `banner_b64`
got bound to the entire conditional HTML, not to the ICP string. The
conditional itself never ran, and the `<img>` never made it into the
output.

This was undetectable by string-presence tests on the stored body —
all the markup looked correct, the structure just didn't *evaluate*.

### Fix

Replace the wrapped `<t>` conditional with a single `<img>` element
whose `src` is computed via `t-att-src=` and a Python ternary
expression:

```xml
<img alt="Company banner" style="…"
     t-att-src="('data:image/*;base64,' + env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64')) if env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64') else ('/web/image/res.company/%s/logo' % object.company_id.id)"/>
```

`<img>` is a void HTML element — the sanitiser preserves its
attributes verbatim, and the QWeb evaluator runs the ternary at
render time. The ICP lookup is duplicated (once for the condition,
once for the value) but that's a single dictionary read; acceptable
trade-off for a robust fix.

### Migration

`migrations/17.0.2.20.0/post-banner-render-fix.py` detects the
broken-`<t t-set>` marker, overwrites the body, and short-circuits
on already-fixed installs. Admin-customised bodies (no broken marker)
are preserved as-is.

### Lessons learned

- HTML fields in Odoo apply `html_sanitize` on every write —
  non-standard tags (`<t>`) survive but their self-closing slash
  does not, which silently breaks QWeb evaluation.
- For conditional logic in `mail.template.body_html`, prefer single
  void elements with `t-att-*` directives over wrapped `<t t-if>` /
  `<t t-else>` blocks. Less elegant, but reliably renders.
- Verification of mail templates must include a render check
  (`_render_field('body_html', [id])`) — static string inspection
  of `tmpl.body_html` is necessary but not sufficient.

## v17.0.2.19.0 — Greeting visual polish

After the user uploaded a custom banner via Settings, a small round
of visual tweaks to make the email feel more "designed" out of the
gate (no copy change, no structural rework — purely layout polish):

| Element | v17.0.2.18.0 | v17.0.2.19.0 |
|---|---|---|
| Banner td alignment | implicit left | `align="center"` |
| Banner td padding | `24px 32px 16px` | `32px 32px 24px` |
| Banner img max-height | 64 px | 96 px (more room for designed banners) |
| Banner img display | `block` | `inline-block` (works with centered td) |
| Body td padding | `32px` | `36px 40px 24px` (wider horizontal, more top breathing) |
| Body line-height | 1.6 | 1.65 |
| Body paragraph margin | 16 px | 14 px (tighter) |
| Sign-off | `<em>Jito Team</em>` plain | `<strong style="color:#2c3e50;">Jito Team</strong>` after muted "Best regards" |

Subject, copy, banner-conditional logic, footer band — unchanged.

`migrations/17.0.2.19.0/post-banner-polish.py` follows the same
conservative pattern as the earlier body-rewrites: detects the
v17.0.2.18.0 banner-td signature
(`padding:24px 32px 16px;border-bottom:1px solid #eef0f2`) and
overwrites only that. Already-polished installs short-circuit on the
v19 signature; admin-customized bodies are left alone.

## v17.0.2.18.0 — Jito-branded greeting copy

v17.0.2.17.0 redesigned the *layout* of the employee-facing greeting
(Clean Corporate, banner band + table card). v17.0.2.18.0 keeps that
layout intact and **changes the wording** to a warmer copy signed by
**"Jito Team"** (this deployment's owning company):

> Hi {{ object.name }},
>
> Wishing you a wonderful Happy Birthday!
>
> Today is all about you. We hope your day is filled with joy, great
> surprises, and the company of people you love. May the year ahead
> be your best one yet, full of inspiration and happiness.
>
> Enjoy your special day to the fullest!
>
> Best regards,
> Jito Team

The subject is reformatted to **"Happy Birthday, {{ object.name }}! 🎂"**
(emoji moved to the end — Jito copy convention).

### Why "Jito Team" is hardcoded, not `object.company_id.name`

The previous body used `<em t-out="object.company_id.name"/>` in the
signature so a multi-company deployment could display whichever
company the employee belonged to. For *this* deployment we prefer a
guaranteed brand line: even if an admin renames the default company
record in res.company to something stray, the greeting still says
"Jito Team". This is a conscious coupling of the template to the
deployment's brand. If you fork the module for a different company,
either edit `data/mail_template_data.xml` directly or override the
literal via the Email Templates UI (Settings → Birthday Reminders →
"Edit greeting template…").

### Migration

`migrations/17.0.2.18.0/post-jito-greeting.py` conservatively replaces
both `subject` and `body_html` only when the body still carries the
v17.0.2.17.0 marker phrase (`"Today is your special day"`). It
recognises its own marker (`"Wishing you a wonderful Happy Birthday!"`)
on re-run and short-circuits.

| State on upgrade | Migration behaviour |
|---|---|
| Body still on v17.0.2.17.0 default | Overwrite subject + body |
| Body already on v17.0.2.18.0 | Skip (idempotent) |
| Body customized via UI (no v17.0.2.17.0 marker) | Preserve as-is |

### Nothing else changes

The 4 other mail.templates (`7_days`, `1_day`, `today`,
`greeting_failed`), the Settings field-list (banner upload +
"Edit greeting template…" button from v17.0.2.17.0), the cron records,
and all `hr.employee` / `birthday.reminder.log` logic are untouched.

## v17.0.2.17.0 — Clean Corporate greeting template + Settings banner

v17.0.2.15.0 / 16.0 shipped a minimal placeholder body for the
employee greeting — just a plain `<div>` with a few `<p>` tags. It
worked, but it looked like a developer placeholder, not a polished
company greeting. v17.0.2.17.0 redesigns the body and adds a
discoverable, low-friction config surface in Settings.

### Body redesign — "Clean Corporate"

The new body uses a **table-based layout** (email-client safe — Outlook
breaks on `<flex>`/`<grid>`, but renders `<table>` cleanly) with all
styles **inline** (Gmail strips `<style>` blocks). Structure:

```
gray page background
  ↳ white card (600px, thin gray border, rounded corners)
       ↳ banner band (logo at top, thin divider below)
       ↳ body text (16px line-height, dark slate text)
       ↳ footer disclaimer (gray, subtle)
```

The banner band is **conditional via QWeb** in the template body:

```xml
<t t-set="banner_b64" t-value="env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64')"/>
<t t-if="banner_b64">
    <img t-attf-src="data:image/*;base64,{{ banner_b64 }}" .../>
</t>
<t t-else="">
    <img t-attf-src="/web/image/res.company/{{ object.company_id.id }}/logo" .../>
</t>
```

— if the admin uploaded a custom banner in Settings, render it from
the ICP-stored base64 blob; otherwise fall back to the standard
`res.company.logo` URL. No code path change needed in
`_send_employee_birthday_email`; `mail.template.send_mail` already
provides `env` and `object` to the QWeb context.

### Settings — banner upload + "Edit advanced..." button

A new **"Greeting Template"** block under **Settings → Birthday
Reminders** exposes two controls:

1. **"Custom banner image"** — a `widget="image"` Binary field that
   stores its base64 payload in `ir.config_parameter`
   `hr_birthday_reminders.greeting_banner_b64`. Empty → fall back to
   `res.company.logo`. Recommended size 600×80 px, PNG/JPG, under
   100 KB. Storage as a base64 string in the ICP text column avoids
   creating an attachment-management UI for a single image.
2. **"Edit greeting template..."** — a button that opens the
   underlying `mail.template` form (`mail_template_birthday_to_employee`)
   with full WYSIWYG, live preview, and translation overlays. For
   any tweak beyond banner-swap (subject, sign-off, language-specific
   bodies, snippets) admins use this standard Odoo editor.

The Binary field cannot use the `config_parameter=` automation
(Odoo's CP helper only handles text/numeric primitives), so persistence
is hand-rolled in `get_values()` / `set_values()`:

```python
def get_values(self):
    res = super().get_values()
    res['birthday_greeting_banner'] = self.env['ir.config_parameter'].sudo().get_param(GREETING_BANNER_PARAM) or False
    return res

def set_values(self):
    super().set_values()
    # …existing cron sync…
    ICP.set_param(GREETING_BANNER_PARAM, self.birthday_greeting_banner or '')
```

### Migration — conservative body replacement

`data/mail_template_data.xml` is `<data noupdate="1">`, so the XML
body_html does **not** auto-overwrite on `-u`. Existing installs need
the post-migration `migrations/17.0.2.17.0/post-greeting-body.py` to
bring the new design forward:

1. If body already contains the new marker (`data:image/*;base64`) →
   no-op (already migrated or fresh install).
2. Else, if body still has the v17.0.2.15.0 footer paragraph
   (`<p style="color:#aaa;font-size:11px;margin-top:24px;">— Sent automatically on your birthday.</p>`) →
   overwrite with the new layout.
3. Else (admin customized via UI; markers absent) → preserve.

Idempotent. Safe to re-run.

### Other 4 templates untouched

Only `mail_template_birthday_to_employee` is redesigned. The 4
Responsible-facing templates (`7_days`, `1_day`, `today`,
`greeting_failed`) keep their existing minimal bodies — they're
internal-only and didn't motivate the redesign.

## v17.0.2.16.0 — Separate greeting-hour knob

v17.0.2.15.0 emitted both the per-Responsible reminders **and** the
employee-greeting from the same daily cron tick — admin had a single
`cron_hour_utc` ручка driving both audiences. For multi-tz teams or
companies that simply prefer different timing for "internal action"
vs. "outward-facing congratulation", that single hour is too coarse.

v17.0.2.16.0 splits the work across **two `ir.cron` records**:

| XML id | Calls | Schedule param | Default |
|---|---|---|---|
| `ir_cron_birthday_reminders` | `_cron_birthday_reminders()` (Responsibles) | `hr_birthday_reminders.cron_hour_utc` | 6 UTC |
| `ir_cron_birthday_greetings` (NEW) | `_cron_birthday_greetings_to_employees()` (employee) | `hr_birthday_reminders.greeting_hour_utc` | 6 UTC |

Same-hour deployments are functionally equivalent to v17.0.2.15.0 —
both crons fire back-to-back, the Log table's UNIQUE constraint keeps
everything idempotent. Different-hour deployments stagger the two
audiences.

### What moved

`_cron_birthday_reminders` no longer calls `_send_employee_greetings`
nor the trailing `_refresh_greeting_state_today`. Those two calls
moved to the new entry point `_cron_birthday_greetings_to_employees`
on `hr.employee`. Chip-marker stays consistent across the two crons
because `birthday_greeting_state` has
`@api.depends('birthday_proximity')` — every `_refresh_birthday_helpers()`
(called by both crons) triggers a recompute of the chip from the
latest Log row.

### Enable-toggle is unchanged

`birthday_greeting_to_employee_enabled` (read inside
`_send_employee_greetings` via the `greeting_enabled` ICP key)
continues to be the single feature gate. When OFF, the greeting cron
still wakes up but `_send_employee_greetings` returns immediately —
the wake-up cost is negligible (one DB read per day), and exposing
*two* enable-toggles for one feature would be confusing UX.

If an admin truly wants the greeting cron to never wake up, they can
deactivate it directly via **Settings → Technical → Scheduled Actions
→ "HR: Daily Birthday Greetings to Employees"**.

### Migration

`migrations/17.0.2.16.0/post-greeting-hour.py`:

1. Seeds `ir.config_parameter` `hr_birthday_reminders.greeting_hour_utc = '6'`
   if absent — so the Settings page renders the field as `6` from the
   first open after upgrade.
2. Pins `ir_cron_birthday_greetings.nextcall` to the next future
   occurrence of the configured hour. The XML `<record>` creates the
   cron without an explicit `nextcall`, so Odoo would default it to
   ≈ now and the cron would fire immediately on the next scheduler
   tick — not what we want. The post-migration fixes that.

The cron's `active` flag is intentionally **not** touched on upgrade:
admins who pre-disabled the cron via Scheduled Actions keep that
state.

### Pre-existing greeting Log rows survive

Schema is unchanged in v17.0.2.16.0. All `birthday.reminder.log` rows
with `interval='greeting'` (whether written by v17.0.2.15.0's combined
cron or by the new dedicated cron) work the same way — same UNIQUE
constraint, same `(employee_id, today, 'greeting', base.user_root.id)`
key. Idempotency carries across the upgrade.

## v17.0.2.15.0 — Personal greeting email to the employee

Before this release the only audience of the daily cron was the
Responsibles. The employee whose birthday it actually was received no
message at all from the module. v17.0.2.15.0 adds a separate, parallel
channel: a friendly company-signed greeting email **sent to the
employee themselves** on the day of their birthday, with a chip-marker
in the Employees views recording the outcome.

### What runs

`_send_employee_greetings(today)` is invoked from
`_cron_birthday_reminders` after `_refresh_birthday_helpers()` and
**before** the per-subscription loop. It is independent of
`birthday.reminder.subscription` — it runs even when there are zero
active Responsibles. Inside, for each today-birthday employee:

1. **Address pick:** `_pick_employee_greeting_email(emp)` returns
   `work_email`, falling back to `private_email` (via `sudo()` since
   the field is gated on `hr.group_hr_user`). Returns `None` if both
   are empty.
2. **Send:** `_send_employee_birthday_email(emp, email_to)` renders
   `mail_template_birthday_to_employee` (lang = employee user's lang
   → company partner lang → `en_US`) and calls
   `template.send_mail(emp.id, force_send=True, raise_exception=True,
   email_values={'email_to': email_to})`. `raise_exception=True` is
   what lets the caller log `greeting_status='failed'` instead of
   `'sent'` on SMTP errors.
3. **Log:** one row in `birthday.reminder.log` per attempt, regardless
   of outcome. `interval='greeting'`, `user_id=base.user_root.id`
   (deliberate, see "Why root for greeting rows" below),
   `greeting_status` in `('sent','failed')`, `greeting_failure_reason`
   = `'no_email'` / `'send_error'` for failures.
4. **Failure broadcast:** on no-email or send-error,
   `_notify_responsibles_greeting_failed(emp, today, reason)` sends a
   per-Responsible inbox notification (forced via
   `_birthday_force_inbox_routing`) **plus** an email rendered from
   `mail_template_birthday_greeting_failed`. Every active subscription
   user gets both channels — same mix as the existing reminders so the
   experience is consistent.

### The chip-marker

`hr.employee.birthday_greeting_state` is a stored Selection
(`('sent', '✅ Sent')`, `('failed', '⚠️ Failed')`) with
`compute='_compute_birthday_greeting_state'` and `compute_sudo=True`.
The compute returns `False` for any employee whose
`birthday_proximity != '1_today'`, so badge widgets naturally render
nothing for non-today rows — no column-level `invisible` attribute is
required.

For today-employees the compute reads the latest
`birthday.reminder.log` row keyed on
`(employee_id, today, interval='greeting')` and echoes its
`greeting_status`. `sudo()` is required because the per-user record
rule on the log hides system-owned rows (`user_id = base.user_root`)
from Responsibles.

Refresh is performed twice per cron tick:

- During `_refresh_birthday_helpers()` — proximity recompute triggers
  the `@api.depends('birthday_proximity')` chain. At this point Log
  rows for today's greetings do not yet exist, so the value resets
  to `False`.
- After the per-subscription loop, `_refresh_greeting_state_today(today)`
  flushes the Log model, then explicitly invalidates and recomputes
  `birthday_greeting_state` for the small set of today-employees. The
  ORM cannot track Log-row creation as a dependency, so this manual
  refresh is what flips the chip from empty → sent/failed within the
  same cron transaction.

Views:

- **Kanban** — a `badge rounded-pill text-bg-success` / `text-bg-warning`
  chip rendered inside `oe_kanban_details`, conditional on
  `record.birthday_proximity.raw_value === '1_today'`.
- **Tree** — an extra column `birthday_greeting_state` with
  `widget="badge"`, `decoration-success` / `decoration-warning`, and
  `optional="show"`. Naturally empty for non-today rows.
- **Calendar** — included as `<field name="birthday_greeting_state"/>`
  so the Selection label (with emoji prefix) appears under the event
  title for today-employees only.

### Why root for greeting rows

The UNIQUE constraint on `birthday.reminder.log` is
`(employee_id, birthday_date, interval, user_id)`. PostgreSQL treats
`NULL` as distinct in UNIQUE constraints — using `user_id=NULL` would
allow multiple "greeting" rows for the same employee on the same day,
breaking idempotency. `base.user_root.id` is stable, non-null, and
unambiguously denotes "system-owned" — the existing constraint then
gives us exactly-one-attempt-per-employee-per-day for free, no schema
change.

### Settings

A new toggle **"Send greeting email to employees"** lives under
**Settings → Birthday Reminders → Employee Greeting**, backed by
`ir.config_parameter` `hr_birthday_reminders.greeting_enabled`
(default `True`). When OFF, `_send_employee_greetings` returns
immediately — no log rows, no emails, no broadcasts. The per-Responsible
reminders (7d/1d/on-day) are unaffected.

### Retry policy

A failure row keeps `greeting_status='failed'` until the next calendar
day's birthday (i.e. effectively never for the same person — birthdays
are yearly). The cron does **not** auto-retry the same day after a
failure: re-running the cron the same day re-checks the log and
short-circuits. Rationale: if SMTP is down all morning, we should not
spam Responsibles with N "failure" notifications. Admin retry happens
by deleting the log row manually (Settings → Technical → Birthday
Reminder Log) — but the typical action is to fix `work_email` and
wait for next year, or fix SMTP and trigger a manual re-run.

### Migration

`migrations/17.0.2.15.0/post-greeting-feature.py`:

1. Seeds `ir.config_parameter` `hr_birthday_reminders.greeting_enabled = 'True'`
   if absent. The `res.config.settings` default callable already
   returns `True` when the param is missing, but persisting a value
   makes the Settings UI render the toggle as ON immediately after
   upgrade — no first-save surprise.
2. Calls `_refresh_greeting_state_today(today)` to warm up the chip
   for today-employees. New stored column gets the column-default
   (False/NULL) for every row after `-u`; the warm-up projects any
   existing Log row onto the chip so the UI is correct from the very
   first page load (typically a no-op on upgrade day since the new
   `interval='greeting'` rows don't exist yet).

Schema additions (`interval` Selection extension, two nullable columns
on `birthday_reminder_log`, one Selection column on `hr_employee`)
are handled by Odoo's auto schema-sync — no manual ALTER TABLE.

### Edge cases worth knowing

- **Archived employee:** `_employees_with_birthday_on` does not return
  `active=False` records (Odoo's default search behaviour). No greeting,
  no log row, no broadcast — silent skip.
- **Employee with no linked `res.users`:** still works — the address
  pick uses `work_email`/`private_email` directly, never `user.email`.
- **Multi-company:** the email-from template renders via
  `object.company_id.email`; greeting body uses `object.company_id.name`.
  One greeting per employee per day regardless of company count.
- **SMTP outage:** every today-employee logs `failed/send_error`,
  every active Responsible gets a broadcast (so the failure is
  surfaced loud and clear). Same-day retries are suppressed by the
  log; resolution is to fix SMTP and (if needed) manually delete the
  failed log rows.

## v17.0.2.14.0 — Daily cron + admin-configurable run hour

Before this release the cron ran every hour and each subscription
gated on a per-user `notification_hour` (0..23 in the user's local
timezone). That design was a hold-over from the v1 era and had two
problems:

1. **Implicit configuration.** "Cron checks data every hour" was a
   hidden setting buried in `ir.cron`. Admins who wanted to tune it
   had to dig into Technical → Scheduled Actions.
2. **Excessive frequency.** Once-per-day is sufficient; hourly was
   wasted work.

v17.0.2.14.0 fixes both:

- The cron is set to **interval_type='days', interval_number=1**.
- **`Settings → Birthday Reminders`** exposes two knobs:
  - **"Enable daily reminders"** (Boolean). Mirrors
    `ir.cron.active` — toggle from the settings page is identical to
    toggling the Scheduled Action, but lives next to the hour. Source
    of truth is the cron record itself; the field has no
    `config_parameter=` and uses a `default` callable to read
    `cron.active` on each settings-page open.
  - **"Daily run hour (UTC)"** (Integer 0..23, default 6). Backed by
    `ir.config_parameter` `hr_birthday_reminders.cron_hour_utc`.
    Saving the page recomputes `ir.cron.nextcall` to the next future
    occurrence of the chosen UTC hour — but only when the value
    actually changed, so re-saving without changes does not push the
    next firing forward by a day.
- The per-user `notification_hour` field on
  `birthday.reminder.subscription` is **removed**. With one global
  daily firing, the gate `now_local.hour < notification_hour`
  actively harmed users in timezones west of the cron-firing UTC
  hour — they could miss entire days.
- Idempotency is unchanged: `last_run_date` (in user-local time) is
  the only gate the cron needs, and it is sufficient.

### Migration

`migrations/17.0.2.14.0/post-daily-cron.py` does three things, all
idempotent:

1. `ALTER TABLE birthday_reminder_subscription DROP COLUMN IF EXISTS notification_hour`.
2. Seed `ir.config_parameter` `hr_birthday_reminders.cron_hour_utc` to
   `'6'` if absent.
3. Normalise the cron record: `interval_number=1`, `interval_type='days'`,
   `name='HR: Daily Birthday Reminders'`, `nextcall=` next future
   occurrence of the configured UTC hour.

The cron's `active` flag is intentionally **not** touched by the
migration — admins who explicitly disabled the cron keep that state
through the upgrade. They can re-enable it via the Settings toggle
afterwards.

### UX-shift caveat

Pre-14.0, every Responsible saw notifications around 09:00 *their*
local time. Post-14.0, the cron fires at one global UTC hour, so the
wall-clock time varies per Responsible's timezone:

- Default 06:00 UTC ≈ 09:00 Kyiv (UTC+3) — close to the pre-14.0
  default for Ukrainian users.
- 06:00 UTC = 22:00 LA (previous day) / 02:00 NYC / 15:00 Tokyo.

Pick a UTC hour that lands in early-morning for the dominant
timezone of your Responsibles.

## v17.0.2.13.0 — Suppress system activity auto-notify

`mail.activity.create` runs `action_notify` (`mail/models/mail_activity.py:457`)
which posts a thin "<record_name>: <summary> assigned to you" message
on the assignee. With our friendly explicit notification already
delivering full information, this system message was just noise — and
worse, it routed per the recipient's own `notification_type`, so
inbox-pref users saw it in Discuss while email-pref users (admin) saw
it only in email. The result was an inconsistent inbox count across
Responsibles for the same dispatch.

v17.0.2.13.0 passes `mail_activity_quick_update=True` to
`activity_schedule` (Odoo flag checked at `mail_activity.py:333-337`),
which skips `action_notify` entirely. The activity itself is still
created and shows up in the assignee's Activities widget — only the
post-create notify message is suppressed.

After this release every Responsible (admin included) sees exactly:
- 5 friendly inbox notifications per cron-run (2 on-day + 2 1d + 1 7d).
- 5 rich-template emails per cron-run.
- 3 To Do activities (2 1d + 1 7d).

No `mail.template`, schema or data file changed. Behaviour-only edit.

## v17.0.2.12.0 — Force inbox routing for every Responsible

`message_notify` normally routes notifications according to the
recipient's `res.users.notification_type` preference. A user at
`notification_type='email'` (e.g. `base.user_admin`) therefore only
received the email copy and never saw a badge in Discuss → Inbox —
which contradicted the spec's "email AND in-Odoo notifications for
every Responsible" requirement.

v17.0.2.12.0 introduces `_birthday_force_inbox_routing` which runs
right after `message_notify` and:

1. Locates the `mail.notification` row for the recipient partner.
2. Unlinks any auto-queued `mail.mail` tied to the message (the rich
   template email is sent separately by `_send_birthday_email`, so
   keeping the bare `message_notify` email would just duplicate).
3. Rewrites the notification to
   `notification_type='inbox', notification_status='sent', is_read=False`
   so it shows up in Discuss → Inbox regardless of the user's
   personal preference.

`message_notify` itself is called with
`with_context(mail_notify_force_send=False)` so the bare email stays
in `outgoing` state (instead of being sent inline) until our cleanup
step unlinks it.

**Side effect:** the user's `notification_type` is **not** modified —
their preference still controls routing for non-birthday Odoo
messages. This sidesteps the `-u base` SQL-constraint saga (see
v17.0.2.7.0–v17.0.2.9.0): admin and any `share=True` user keep their
`'email'` setting, while still seeing birthday reminders in the Odoo
UI alongside the email.

**No migration script** is shipped: behaviour-only change, no schema
or data migration.

## v17.0.2.11.0 — Inbox + email for 7-day and 1-day intervals

Before this release, only on-day reminders shipped both an explicit
private inbox notification and a templated email. The 7-day and 1-day
intervals only created a `mail.activity`, so a Responsible with
`notification_type='inbox'` never received an email at all for the
upcoming-birthday reminders, and a Responsible with
`notification_type='email'` got just the bare "Activity assigned to
you" auto-notification rather than a friendly birthday email.

v17.0.2.11.0 adds two new `mail.template` records and an
`EMAIL_TEMPLATE_XMLIDS` dict in `models/hr_employee.py`:

| Template (XML id) | Trigger |
|---|---|
| `mail_template_birthday_7_days` | 7 days before the birthday |
| `mail_template_birthday_1_day` | 1 day before the birthday |
| `mail_template_birthday_today` | on the day (existing) |

`_process_birthday_interval` now calls `_notify_birthday_user` and
`_send_birthday_email` for every interval, with the activity creation
kept exclusively for 7d/1d. The two side-effect helpers were
parameterised on `interval_key`; `_notify_birthday_user` builds an
appropriate body (`in 7 days` / `tomorrow` / `today` wording) and
`_send_birthday_email` looks up the matching template in the dict.

**No migration script** is shipped: only data records and behaviour
changes; existing log rows remain valid; existing activities and
mail.message rows are untouched. Schema unchanged.

## v17.0.2.10.0 — On-day notifications switched to `message_notify`

Before this release, the on-day reminder was a public chatter message
posted on `hr.employee` via `message_post`. Two problems followed:

1. The message was visible to every user with read access to the
   employee record — which, by design, includes every Birthday
   Responsible (the module grants `group_birthday_responsible` read on
   `hr.employee`). Responsibles ended up seeing each other's
   notifications.
2. Per-user dedup logged `(employee, date, on_day, user_id)`, so each
   active subscription re-posted its own copy of the chatter — N
   Responsibles produced N identical chatter posts on the same
   employee on the same day.

v17.0.2.10.0 replaces `_post_birthday_message` with
`_notify_birthday_user`, which uses `mail.thread.message_notify`. The
resulting `mail.message` row carries `message_type='user_notification'`,
which Odoo hides from the chatter UI and excludes from the
`message_ids` One2many. Only the partner in `partner_ids` is notified,
routed through their own `notification_type`. The per-user log key is
unchanged — dedup keeps working without modification.

**No migration script** is shipped: the schema is unchanged; existing
log rows remain valid; historical public chatter messages from earlier
releases are left intact (deleting them would also drop the recipient
notification rows tied to them, with no clear win).

## Migration to v17.0.2.9.0

`migrations/17.0.2.9.0/post-revert-system-inbox.py` runs on upgrade. It
sweeps the database and reverts `notification_type` back to `'email'`
on:

- `base.user_root` / `base.user_admin` (system users),
- any `share=True` user.

Earlier versions of this module (≤ v17.0.2.8.0) flipped every
Responsible to `'inbox'` unconditionally — including admin and
`__system__` if either was assigned. That state survived in the
database and broke the next `-u base` because the mail SQL constraint
`CHECK (notification_type='email' OR NOT share)` refused the row when
`res_users_data.xml` momentarily turned the user share=True via
`<field name="groups_id" eval="[Command.set([])]"/>`. The v17.0.2.9.0
cleanup, combined with the new guard in `create()` and the v17.0.2.7.0
backfill, stops this from happening again.

## Migration from v17.0.1.6.0

`migrations/17.0.2.0.0/post-create-subscriptions.py` runs on upgrade
(skipped on fresh install). It:

1. Reads the legacy `ir.config_parameter` keys
   `hr_birthday_reminders.notification_user_ids`,
   `hr_birthday_reminders.hr_user_ids`, plus the three booleans.
2. Unions the two CSV id lists, filters to active users.
3. Creates one subscription per unique user with the legacy boolean
   defaults and `notification_hour=9` (the column existed at that
   migration's schema; it was dropped in v17.0.2.14.0). The `create()`
   hook adds them to `group_birthday_responsible`.
4. Deletes all five legacy `ir.config_parameter` rows.

Existing `birthday.reminder.log` rows from v1 keep `user_id = NULL` —
the new UNIQUE constraint allows NULL for backward compatibility.

## Setup & installation

1. Place this folder in `jito_modules/`.
2. Restart Odoo with `jito_modules/` on the addons path.
3. Enable developer mode → Apps → Update Apps List.
4. Search **Birthday Reminders** → Install (or Upgrade).
5. **Birthday Reminders → Responsibles** → click **New** to assign an
   existing user as Responsible. Each Responsible can then edit their
   own row to choose which of the three intervals (7d / 1d / on-day)
   they want.

   **A Responsible must already be a `res.users`** — only users can
   receive `mail.activity` / chatter / email. To onboard someone who
   exists only as an `hr.employee`, an admin first creates the login
   via *Settings → Users*; then they can be assigned here. The module
   intentionally does not include user-creation UI — that privilege
   stays where Odoo expects it (Settings).

   The "Employees" sub-menu is read-only — it browses HR data so
   Responsibles can plan ahead. CRUD on `hr.employee` belongs to the
   HR module, not this one.
6. (Optional) **Settings → Birthday Reminders** → adjust the daily
   run hour (UTC), disable the cron entirely, or toggle off the
   per-employee greeting via "Send greeting email to employees"
   (the latter is ON by default).
7. (Optional) **Settings → Technical → Scheduled Actions →
   "HR: Daily Birthday Reminders" → Run Manually** to dry-run
   immediately.

## Quick verification

```python
# In an Odoo shell
self.env['hr.employee']._cron_birthday_reminders()

# Inspect what was emitted
self.env['birthday.reminder.log'].search([])

# Inspect the cron schedule after a settings save
self.env.ref('hr_birthday_reminders.ir_cron_birthday_reminders').read(
    ['name', 'interval_number', 'interval_type', 'nextcall', 'active'])

# Inspect the configured UTC hour
self.env['ir.config_parameter'].sudo().get_param(
    'hr_birthday_reminders.cron_hour_utc')
```

Re-running the cron must produce **zero** new log rows / activities /
messages / emails for the same target dates and same Responsibles —
that is the idempotency contract.
