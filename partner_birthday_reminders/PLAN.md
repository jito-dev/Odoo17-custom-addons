# partner_birthday_reminders — Implementation Plan

Status: **awaiting approval** · Target version `17.0.1.0.0` · Author: dev session 2026-08-03

## 1. Goal

Birthday reminders for **contacts** (`res.partner`), mirroring the proven
`hr_birthday_reminders` flow, with one structural difference:

> the recipient is **not** a global roster — it is the contact's own
> **Account Manager** (`res.partner.user_id`).

Decisions confirmed with the user:

| Question | Decision |
|---|---|
| Packaging | **New module** `partner_birthday_reminders` — `hr_birthday_reminders` (v17.0.2.35.0, live in prod) stays untouched |
| Account Manager field | **Reuse `res.partner.user_id`** (standard "Salesperson" = *the internal user in charge of this contact*), relabelled "Account Manager" on the birthday UI |
| Greeting to the contact | **No** — reminders go to the Account Manager only. No automated mail to clients. |
| Intervals | **7 days before / 1 day before / on the day**, each AM can toggle their own |

## 2. Eligibility rule ("who shows up")

A contact is a birthday candidate when **all** hold:

1. `birthday` is set,
2. `is_company = False` (no company contacts),
3. the partner is **not** linked to any Odoo internal user — *current or past*
   (i.e. any `res.users` with `share = False`, **including archived users**),
4. `active = True`.

Rule 3 is the tricky one: archived users are invisible to a plain
`partner.user_ids` read (`active_test`). Implementation:

```python
has_internal_user = fields.Boolean(compute=..., store=True)

@api.depends('user_ids', 'user_ids.share', 'user_ids.active')
def _compute_has_internal_user(self):
    Users = self.env['res.users'].sudo().with_context(active_test=False)
    internal = Users._read_group([('partner_id','in', self.ids), ('share','=',False)], ...)
```

Belt-and-braces: the daily cron calls `_refresh_partner_birthday_helpers()`
first, which recomputes eligibility for all partners — so even if a
`@api.depends` edge case is missed (user archived through a path that does
not retrigger), the board self-heals within 24 h. This is the same
self-heal pattern the HR module uses for `next_birthday`.

## 3. Data model

New module, four pieces:

| Model | File | Purpose |
|---|---|---|
| `res.partner` (extension) | `models/res_partner.py` | `birthday` (Date, `groups='base.group_user'`), stored computes `next_birthday`, `birthday_proximity` (today/tomorrow/this_week/later), `has_internal_user`, `birthday_eligible`. Plus the cron entry point and the notify/email helpers. |
| `partner.birthday.reminder.pref` | `models/partner_birthday_reminder_pref.py` | Per-Account-Manager preferences: `user_id` (unique), `notify_7_days_before` / `notify_1_day_before` / `notify_on_day`, `last_run_date`, `active`, `user_tz` (related), `is_editable_by_current_user`. Auto-created by the cron for any user who is AM of ≥1 eligible contact; defaults taken from the Settings block. Pausing = `active=False`. |
| `partner.birthday.reminder.log` | `models/partner_birthday_reminder_log.py` | Idempotency + audit. `UNIQUE(partner_id, birthday_date, interval, user_id)`. |
| `res.config.settings` (extension) | `models/res_config_settings.py` | Master enable toggle (mirrors `ir.cron.active`), daily run hour UTC (ICP `partner_birthday_reminders.cron_hour_utc`, default 6 ≈ 09:00 Kyiv), default intervals for auto-created prefs. |

Deliberately **not** copied from the HR module (v1 scope): greeting flow,
Health dashboard, watchdog/alert model, banner. The log + Settings block
give enough observability for v1; the health dashboard can be lifted later
if operations ask for it.

## 4. Cron flow

```
ir.cron  "Contacts: Daily Birthday Reminders"  (daily @ cron_hour_utc, user_root)
 └ ResPartner._cron_partner_birthday_reminders()
     ├ _refresh_partner_birthday_helpers()      ← recompute next_birthday / proximity / eligibility
     ├ _ensure_prefs_for_account_managers()     ← auto-create a pref row per AM of an eligible contact
     └ for each active pref:
          skip if last_run_date == user-local today (res.users.tz, pytz, UTC fallback)
          for each enabled interval (7d / 1d / on_day):
             target = local_today + offset  (Feb-29 → Feb-28 fallback in non-leap years)
             partners = eligible contacts with birthday day/month == target AND user_id == pref.user_id
             for each partner:
                skip if log row (partner, target, interval, user) exists
                7d/1d → mail.activity (To Do, deadline = birthday) on the contact
                message_notify  → private inbox note (forced inbox routing)
                mail.template   → friendly email to the AM
                create log row
          stamp pref.last_run_date = user-local today
```

Idempotency, tz handling, `mail_activity_quick_update`, `message_notify`
(not `message_post`, so nothing lands on the client-visible chatter) and
forced-inbox routing are all carried over 1:1 from `hr_birthday_reminders` —
those decisions are documented in its GUIDANCE.md and have proven out in prod.

Day/month matching is done in Python over a pre-filtered set
(`birthday_eligible = True`), not with SQL `EXTRACT`, matching the HR module
and keeping the Feb-29 rule in one place.

## 5. Security

| Group | Rights |
|---|---|
| any internal user (`base.group_user`) | read/write **own** pref row (record rule `user_id = user.id`), read **own** log rows, see the Birthdays board (through their normal Contacts access) |
| `group_partner_birthday_manager` (new, category "Birthday Reminders") | full CRUD on prefs + logs, sees every row |
| `base.group_system` | same as Manager (explicit rules — lesson from HR v17.0.2.34.0, where admin was locked out of other people's rows) |

No "Responsible" group is needed here: the audience is derived from
`res.partner.user_id`, so there is no roster to gate. `birthday` and the
computed helpers carry `groups='base.group_user'`, so portal/public users
never read them.

## 6. UI

- **Contact form** (`base.view_partner_form` inherit): `Birthday` field next to
  Title/Job Position, `invisible="is_company"`; read-only `Next Birthday`
  next to it.
- **Contacts → Birthdays** menu → action on `res.partner` with domain
  `[('birthday_eligible','=',True)]`:
  - **tree** (`tree`, not `list`, per repo convention): name, Account Manager,
    email, phone, birthday, next birthday, proximity badge (decoration by proximity)
  - **kanban** grouped by proximity, **calendar** on `next_birthday`
  - search filters: Today / This week / This month / My contacts (`user_id = uid`),
    group-by Account Manager / month
- **Contacts → Birthday Reminder Settings** → own pref record (Manager sees all).
- **Settings → Contact Birthday Reminders** → enable, hour, default intervals.

## 7. Options considered

| Option | Verdict |
|---|---|
| Extend `hr_birthday_reminders` with `res.partner` | ✗ rejected — couples two audiences and risks a prod-critical module |
| Generic "birthday engine" abstract mixin refactored out of the HR module | ✗ rejected for v1 — would require touching/regression-testing the live HR module; revisit if a third audience appears |
| New dedicated `birthday_manager_id` on partner | ✗ rejected — `user_id` already means "internal user in charge"; one field to maintain, zero data entry |
| Auto-greeting email to the client | ✗ out of scope — customer-facing automated mail needs separate sign-off |
| No pref model (global intervals only) | ✗ rejected — loses per-user tz idempotency and the "pause me" affordance |

## 8. Files to create

```
partner_birthday_reminders/
  __init__.py, __manifest__.py, GUIDANCE.md
  models/{__init__,res_partner,partner_birthday_reminder_pref,
          partner_birthday_reminder_log,res_config_settings}.py
  data/{ir_cron_data,mail_template_data}.xml
  security/{partner_birthday_security.xml,ir.model.access.csv}
  views/{res_partner_views,partner_birthday_reminder_pref_views,
         partner_birthday_reminder_log_views,res_config_settings_views,menus}.xml
  tests/{__init__,test_partner_birthday_eligibility,test_partner_birthday_cron}.py
```

## 9. Test plan

Automated (`odoo-bin -u partner_birthday_reminders --test-enable`):
1. eligibility — company contact, contact with active internal user, contact
   with **archived** internal user, contact without birthday → all excluded;
   plain contact with birthday → included
2. archiving a user *after* the fact flips `birthday_eligible` to False
   (both via `@api.depends` and via the cron refresh)
3. Feb-29 birthday on a non-leap year fires on Feb-28
4. routing — AM A gets only their own contacts' reminders, AM B gets theirs
5. idempotency — running the cron twice creates no second activity/mail/log row
6. pref respects disabled intervals and `active=False` (paused)
7. contact with no `user_id` → no crash, no notification

Manual on `odoo_dev`: install, set a birthday on a test contact for tomorrow,
run the cron manually, screenshot the AM's Inbox + activity + Mailpit email,
screenshot the Birthdays board.

## 10. Estimate

~1 working session: models+security ~40%, views/menus ~25%,
templates+cron ~15%, tests ~20%.
