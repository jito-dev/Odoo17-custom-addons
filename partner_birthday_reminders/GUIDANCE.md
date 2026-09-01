# partner_birthday_reminders — Module Guidance

Birthday reminders for **contacts**, delivered privately to the colleague
responsible for greeting them. Companion to `hr_birthday_reminders`
(employee birthdays) — same idea, different audience, deliberately not a
copy of it.

> **Two traps to know before changing anything here.**
> 1. `birthday_greeter_id` is `ondelete='set null'`. It must never become
>    `cascade`: a cascade from `res.users` to `res.partner` would delete
>    customer records when a user account is removed.
> 2. A Default Greeter can pause their own preference row, which stops
>    reminders for every contact resolving to them, with no error
>    anywhere. Settings shows a red banner when that happens — keep it.

> **If the board looks empty**, that is expected on a fresh install:
> `birthday` is a field this module adds and nothing populates it. Go to
> **Contacts → Birthdays → Missing Birthdays** and fill dates in, or
> import them.
> Settings → Contact Birthdays shows the current coverage.

## What this module does

Adds a **Birthday** field to contacts and reminds the responsible
colleague — 7 days before, 1 day before, and on the day — through a To Do
activity, a private Odoo notification and an email.

**Nothing is ever sent to the contact themselves.** The reminder is a
private nudge; how, and whether, to greet the client stays a human
decision. Automated customer-facing mail would be a separate product
decision, not a setting.

## Who receives a reminder

There is **no roster**. The recipient is derived from the contact:

```
reminder recipients ==  res.partner.birthday_manager_ids
                     =  birthday_greeter_id       (per-contact override)
                     |  user_id                   (Salesperson)
                     |  <Default Greeters>        (Settings — may be several)
                     |  ∅
```

The first non-empty step wins. Every candidate is validated on read
(active, not a portal user), so archiving somebody makes the chain fall
through to the next step rather than going quietly silent.

**Set `birthday_greeter_id`, not `user_id`.** Salesperson is a live CRM
field driving sales reporting, lead assignment and salesperson-based
record rules; bulk-editing it to steer birthday emails corrupts sales
data. Odoo's own Contacts list makes that mistake easy — it ships
`multi_edit="1"` with a Salesperson column — which is exactly why this
module offers the same bulk ergonomics on a field of its own.

Only the last step can be plural. Several **Default Greeters** cover the
whole contact base at once, and crucially nothing is written onto the
contacts: covering the base does not mean stamping a name on thousands of
records. Several recipients for *one specific* contact is not supported —
both per-contact fields are single-valued.

`birthday_manager_ids` is a stored computed many2many rather than a
helper method because the engine has to `search()` on the resolved
recipient and the board groups by it.

**There is deliberately no "inherit from the parent company" setting.**
Odoo already does that in core: `res.partner.user_id` is a stored,
`precompute=True` field whose `_compute_user_id` copies the parent
company's salesperson onto any person contact that has none. A setting of
ours would duplicate core behaviour and — worse — could not switch it
off, so it would be a knob that lies. `test_company_inheritance_is_core_behaviour`
pins this, so a future Odoo change surfaces the decision instead of
silently breaking it.

## Who appears on the board (the eligibility rule)

`birthday_eligible` is the module's central concept. All four clauses
must hold:

1. `birthday` is set,
2. `is_company = False` — no company records,
3. **not** linked to an Odoo internal user, **current or past** — a
   `res.users` with `share = False`, *including archived ones*,
4. `active = True`.

Clause 3 is the subtle one. A plain read of `partner.user_ids` hides
archived users (`active_test`), so a former colleague would silently pass
the filter. `_compute_has_internal_user` therefore searches `res.users`
with `with_context(active_test=False)` under `sudo()`, and declares
`user_ids.active` among its dependencies. Belt and braces: the daily cron
re-runs the compute for every partner, so any dependency edge case the
ORM misses self-heals within 24 h instead of leaking a colleague onto the
client birthday board.

Portal users are **not** excluded — a portal account is a client, not a
colleague. There is a test for this.

## Getting data in

**Contacts → Birthdays → Missing Birthdays** is the counterpart of the board: the
same four eligibility clauses with the birthday one inverted, written
from the same clauses on purpose so the two screens cannot drift. It is
an `editable="bottom"` tree with `multi_edit="1"` — walk the list and
type down the Birthday column, or select many rows and set the Greeter in
one go. `create="0"`: the screen completes existing contacts, it is not a
place to invent new ones.

A mass-update wizard was considered and rejected — birthdays are all
different, so setting one value for many records saves nothing.

**Unknown birth year.** Tick *Birth year unknown* and the stored year is
normalised to `BIRTHDAY_UNKNOWN_YEAR = 1904`. Nothing else changes: the
engine matches on `(month, day)` only, and no template ever prints a
year. 1904 rather than 1900 because 1900 is not a leap year — a Feb 29
birthday could not be stored against it at all.

**CSV import** (Odoo native, Contacts → ⚙ → Import records) — the useful
column headers are:

| Column | Field |
|---|---|
| `Name` or `id` (external id) | matching key |
| `Birthday` | `birthday` |
| `Birth year unknown` | `birthday_year_unknown` |
| `Birthday Greeter` | `birthday_greeter_id` |

Importing onto existing contacts requires matching on `id` or `Name`; a
plain name match creates duplicates when the names are not exact.

## Main models

| Model | File | Purpose |
|---|---|---|
| `res.partner` (fields) | `models/res_partner.py` | `birthday`, `birthday_year_unknown`, `birthday_greeter_id`, plus stored computes `next_birthday`, `birthday_proximity`, `has_internal_user`, `birthday_eligible`, `birthday_manager_ids`. |
| `res.partner` (engine) | `models/res_partner_reminder.py` | Cron entry points and the notification channels. Same model, split file — the field layer and the dispatch layer are read for different reasons. |
| `partner.birthday.pref` | `models/partner_birthday_pref.py` | Per-recipient settings: **when** (intervals + weekend shift), **how** (three channel switches), **which contacts** (scope), digest opt-in, pause flag, plus the `last_run_date` / `last_digest_date` stamps. |
| `partner.birthday.log` | `models/partner_birthday_log.py` | Idempotency + audit. `UNIQUE(partner_id, birthday_date, interval, user_id)`. |
| `res.config.settings` | `models/res_config_settings.py` | Cron enable + UTC hour, digest master switch, Default Greeters, the defaults used when provisioning a new preference row, and a read-only coverage readout. |

Constants shared by the two `res.partner` files live in
`models/constants.py` so the field layer and the engine cannot drift.

## Preference rows are provisioned, not subscribed to

Every cron tick calls `_ensure_prefs_for_users()` for the internal users
who are the resolved recipient of at least one eligible contact. Missing
rows are created with the Settings defaults. Opening **My Reminders**
also creates the row on demand, so the screen is never empty.

Consequences worth knowing:

* **Deleting** a preference row is harmless *and pointless* — the next
  run recreates it. **Pausing** (`active = False`) is the supported way
  to opt out; the lookup uses `active_test=False`, so a paused row is
  recognised as existing and never resurrected. Without that flag the
  cron would silently re-subscribe anyone who opted out.
* Changing the Settings defaults never rewrites existing rows — people
  who tuned their own settings keep them.

## Recipient preferences

Two entry points, split by audience — a regular user's record rule shows
them exactly one row, and a list of one is a poor way to render "my
settings":

* **Contacts → Birthdays → Reminders → My Reminders** — a *form* on your own
  row. Everyone.
* **Contacts → Birthdays → Reminders → All Preferences** — the list,
  restricted to the manager role, which is the only one that can see more
  than one row anyway.

What a recipient can choose:

| Setting | Default | Notes |
|---|---|---|
| 7 days / 1 day / on the day | all on | the fixed interval keys; they are also the log's idempotency key, which is why they are not free-form numbers |
| **Channels**: To Do / Discuss / Email | all on | the To Do is the one people refuse first — activities are a work queue, and a client birthday is not work for everyone |
| **Shift weekend reminders to Friday** | off | 7-day and 1-day only. The on-day reminder never shifts: moving "today is their birthday" does not make it early, it makes it false |
| **Scope**: all / only contacts I own | all | `owned_only` excludes contacts reached solely via the Default Greeters list |
| Monthly digest | off | separate opt-in with its own switch — it still sends when the Email channel is off |

Two behaviours worth knowing:

* **All channels off emits nothing and logs nothing.** Writing a log row
  would permanently suppress that reminder, so re-enabling a channel
  later would never resend it. The form warns that the row is inert.
* **The weekend shift cannot double-send.** The log key is the *birthday
  occurrence*, not the delivery date, so Friday covering Saturday's and
  Sunday's deliveries still produces one row per contact and interval.

## Cron flow

```
ir.cron "Contacts: Daily Birthday Reminders"   (daily @ cron_hour_utc, user_root)
 └ ResPartner._cron_partner_birthday_reminders()
     ├ _cleanup_overdue_birthday_activities()   ← drop our own expired To Dos
     ├ _refresh_partner_birthday_helpers()      ← next_birthday / proximity / eligibility / recipients
     ├ _ensure_prefs_for_users(recipients)
     └ for each active preference row:
          skip if every channel is off
          skip if last_run_date == user-local today   (res.users.tz, pytz, UTC fallback)
          for each enabled interval (7d / 1d / on-day):
             targets = _birthday_delivery_targets()    (weekend shift applied here)
             partners = eligible contacts born on target AND resolving to this user
             filtered further when scope = owned_only
             for each:  skip if a log row exists
                        7d/1d → mail.activity (deadline = birthday)   if channel on
                        message_notify → private inbox note           if channel on
                        mail.template  → email to the recipient       if channel on
                        create log row
          stamp last_run_date = user-local today
```

Every stage is individually wrapped in `try/except`: one broken contact,
user or preference row can never stop the batch.

## Monthly digest

A second, **opt-in** channel: one email on the 1st of each month listing
that recipient's contacts with a birthday that month. Planning context —
it does not replace the per-birthday reminders.

```
ir.cron "Contacts: Monthly Birthday Digest"   (daily, INACTIVE on install)
 └ ResPartner._cron_partner_birthday_digest()
     └ for each active pref with notify_monthly_digest:
          skip if last_digest_date == first of the user's local month
          gather eligible contacts resolving to this user, birthday in this month
          render + send (or skip if empty)
          stamp last_digest_date
```

Three decisions worth knowing:

* **The cron runs daily, not monthly.** The guard is per-user and keyed
  on the user's *local* month, so the digest lands on day 1 in each
  recipient's own timezone. A true monthly cron fires once globally and
  is inevitably a day early or late for someone. On days 2–31 the job is
  a cheap no-op.
* **Idempotency is `last_digest_date`, not the log table.**
  `partner.birthday.log.partner_id` is `required` + `ondelete='cascade'`,
  so anchoring a digest to some arbitrary contact would drop the guard
  when that contact is deleted, and would corrupt the table's single
  clear meaning ("this contact was notified"). Making `partner_id`
  nullable is worse — Postgres treats NULLs as distinct in a UNIQUE
  index, so the constraint would stop guarding anything at all.
* **The stamp is written even when the month is empty.** Otherwise the
  digest would fire mid-month as soon as any contact gained a birthday.

The digest template renders against **`res.users`**, not `res.partner` —
a digest is about many contacts, so no single contact can be its record.
The list is injected at render time via `add_context` in
`_send_partner_birthday_digest`; `mail.template.body_html` declares
`render_engine='qweb'`, which is what makes its `t-foreach` work.
`send_mail()` cannot carry extra context, hence the explicit
`_render_field` + `mail.mail` create. The list is capped at
`DIGEST_MAX_ROWS`, because a Default Greeter can own the entire base.

Both the cron (`active=False`) and the per-user flag (`False`) ship off:
a second outbound channel must be opted into deliberately.

## Idempotency and timezones

`partner.birthday.log` is the single source of truth for "already
notified?" — its UNIQUE constraint is the hard guarantee, the
`search_count` pre-check only avoids pointless work. A manual *Run
Manually* on the cron is therefore always safe.

`last_run_date` is keyed on the user's **local** date (`res.users.tz`,
UTC fallback), so the once-per-day promise holds even when the fixed UTC
firing straddles local midnight for recipients in other timezones.

⚠️ One residual window: the email is sent with `force_send=True`, i.e.
handed to SMTP immediately, while the log row is written afterwards and
committed with the rest of the batch. If the process is killed mid-run,
mail already sent loses its log row and will be sent again on the next
tick. Committing per contact would close this at the cost of batch
atomicity — worth doing only at a volume where the trade pays off.

## Channel decisions

* **`message_notify`, not `message_post`.** A contact's chatter is
  customer-facing context shared with the whole team; internal birthday
  chatter does not belong there. `mail.thread.message_ids` excludes
  `user_notification` messages, so nothing appears on the record. It also
  skips follower fan-out — only the recipient is told.
* **Inbox routing is forced** (`_birthday_force_inbox_routing`): the
  `mail.notification` row is rewritten to `inbox` and the bare
  auto-queued `mail.mail` is unlinked, so the user sees the note in
  Discuss *and* receives exactly one (rich, templated) email.
* **No To Do on the day.** By the birthday itself there is nothing left
  to prepare; the on-day interval is notification + email only.
* Activity cleanup matches only summaries starting with
  `ACTIVITY_SUMMARY_PREFIX`, so other people's activities on the same
  contact are never deleted. The prefix is English — a multi-language
  deployment should switch to a dedicated `mail.activity.type`.

## Security

Receiving a reminder is **not** a permission. Any active internal user
receives one as soon as the chain resolves to them; there is nothing to
grant.

| Group | Rights |
|---|---|
| `base.group_user` | read/write **own** preference row, read **own** log rows, the boards via normal Contacts access |
| `group_partner_birthday_manager` ("Contact Birthday Manager") | read/write every preference row, read the whole log |
| `base.group_system` | listed explicitly on both manager rules |

`base.group_system` is on the manager rules from day one on purpose:
without it an admin who also matches the narrower "own rows only" rule is
blocked from editing other people's rows, with a confusing AccessError on
save.

Every field this module adds to `res.partner` carries
`groups='base.group_user'`. `res.partner` is readable by portal and
public users in several flows, and a birthday is personal data;
declaring the groups on the field also keeps them out of the ORM prefetch
batch for those users, which a view-only restriction would not.

## UI

* **Contact form** — Birthday, Birth year unknown and Birthday Greeter
  (hidden on companies), plus a read-only echo of the resolved
  recipients.
* **Contacts → Birthdays** — one navbar section holding everything this
  module adds (`views/menus.xml`), because three sibling top-level
  entries read as three unrelated features:

  ```
  Birthdays
    Upcoming Birthdays
    Missing Birthdays
    ── Reminders ──          ← group header, not clickable
       My Reminders
       All Preferences
       Reminder Log
  ```

  The section itself carries no action: a navbar menu with children is
  a dropdown toggler (`web.NavBar.SectionsMenu`) and its action would
  never fire. "Reminders" is a menu with children and no action, which
  is how Odoo renders a `dropdown-header` group inside the dropdown.
  Deliberately *not* under Contacts → Configuration, which is gated to
  `base.group_system`; every internal user must reach their own
  preferences.
* **Upcoming Birthdays** — kanban (grouped by proximity) / tree /
  calendar over `[('birthday_eligible','=',True)]`, with filters Today /
  Tomorrow / Within 7 days / My contacts / No account manager. The board
  views carry `priority=99` so Odoo never picks them as the default views
  of `res.partner`. The tree is editable and `multi_edit`, so the Greeter
  can be reassigned in bulk without opening a single form.
* **Missing Birthdays** — the data-entry counterpart.
* **Settings → Contact Birthdays** — coverage readout, Default Greeters
  (with the count of contacts they would capture), digest switch, cron
  enable, UTC hour, defaults for newly provisioned recipients.

The resolved-recipients column on the board is **optional and hidden by
default**: with no Default Greeters configured it always equals the
Greeter or Salesperson already shown, and a permanently visible duplicate
column makes the board look broken.

## Email templates

Three per-interval `mail.template` records on `res.partner`, plus the
digest on `res.users`, with `email_to` overridden per recipient so the
templates stay audience-agnostic. Two conventions:

1. **Never self-close a non-void HTML element.** `<strong t-out=""/>`
   survives `html_sanitize`, but the WYSIWYG editor later normalises it
   into an unclosed tag that swallows every following paragraph, silently
   emptying the body. Every `t-out` has an explicit closing tag and a
   placeholder.
2. The card markup is **repeated per template rather than factored into
   a `t-call`**: admins edit these bodies in the WYSIWYG editor, which
   does not evaluate QWeb — a body consisting of one `t-call` would open
   as an empty, uneditable page.

Subjects and bodies disclose day and month only, never the year: a
reminder must not leak the contact's age.

To check what a template produces without sending anything, use Odoo's
built-in preview: **Settings → Technical → Email → Email Templates →
Preview**, and pick a contact.

## Tests

`tests/` — one file per concern: eligibility, cron dispatch, the
recipient chain, the greeter field, per-user preferences, unknown year,
the digest, and the Missing Birthdays screen.

```bash
odoo-bin -d <db> -u partner_birthday_reminders \
         --test-enable --test-tags /partner_birthday_reminders \
         --stop-after-init
```

Three traps when adding more:

* **Every date fixture must be anchored on `_local_today()`**, the helper in
  `tests/common.py`, and never on `fields.Date.context_today(self.env.user)`.
  The module works in the *preference owner's* timezone
  (`_birthday_local_today(pref)`); the test admin has none, so it is UTC.
  Anchoring a fixture on the admin made 18 of these tests fail between 21:00
  and 24:00 UTC and pass again by morning — the fixtures were a day behind the
  Kyiv managers they were written for. One constant, `PartnerBirthdayCommon.
  TEST_TZ`, is the timezone of **every** user in the suite, the admin included,
  so the fixtures, the cron and the model code that reads `self.env.user`
  (`_cleanup_overdue_birthday_activities`, `_compute_birthday_helpers`) all land
  on the same calendar day whatever the clock says. Give a user their own
  timezone only in a test that is *about* timezones — a third user left in
  another zone is how two of these tests failed even after the fixtures were
  fixed. Overriding `TEST_TZ` with a zone that is on a different date from UTC
  is also the cheapest way to check that a new test is not clock-dependent.

* `ir.config_parameter.get_param` is ormcached and that cache is **not**
  rolled back with the test transaction, so a value set by an earlier
  test can leak into the next. Set the parameters you depend on
  explicitly in `setUp` rather than trusting defaults.
* The cron is **global** — it also processes real contacts that happen to
  have a birthday today. Filter `_new_mails` by recipient rather than
  asserting that it is empty.
