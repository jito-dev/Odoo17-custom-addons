# bank_account_internal_name

## What this module does
Adds a human-friendly **Internal Name** to bank accounts and makes every bank-account
selector searchable by it. Bank accounts are otherwise shown only by IBAN/account
number, which is hard to recognise and easy to mis-pick (e.g. the wrong account ending
up as the *Recipient Bank* on invoices).

## How it works (Option A — no helper field, no display pollution)
- **`res.partner.bank.internal_name`** (`models/res_partner_bank.py`) — a `Char` (indexed),
  e.g. `jito.eur.internal`. Internal only: it is **not** used on payment files or printed
  documents.
- **`_rec_names_search = ['acc_number', 'internal_name']`** — the base `_name_search` only
  searches `_rec_name` (`acc_number`) by default; adding `internal_name` to
  `_rec_names_search` makes name-search match it too (OR logic, handled by core). So typing
  e.g. `jito.eur` in **any** bank selector — the customer invoice **Recipient Bank**
  (`account.move.partner_bank_id`), vendor bills, payments, statements — finds the account.
  No method override, no extra/helper field, no `onchange` mirror to drift.
- The **display** is left as the IBAN (`_rec_name` unchanged), so nothing new leaks onto
  printed invoices; you *search* by the internal name, the field still *shows* the IBAN.

## Invoice helper field — "Recipient Bank Internal Name"
On the customer invoice (**Other Info**), right after **Recipient Bank**, a field
**Recipient Bank Internal Name** (`account.move.recipient_bank_internal_id`,
`models/account_move.py`) lets you pick the bank by its internal name:
- It's a **two-way live mirror** of `partner_bank_id` via **compute (`@api.depends('partner_bank_id')`,
  loads/reflects) + onchange (live push to Recipient Bank in the form) + inverse (write-through for
  ORM/imports)**, and crucially **`store=True`**. A plain writable `related` only writes on save (never
  updates the on-screen field), and a *non-stored* computed mirror gets **recomputed back from
  `partner_bank_id` during the onchange round**, reverting the live edit — so it appeared to change only
  after save. Making the field **stored** protects the user-assigned value (Odoo won't recompute over a
  manual edit on an editable *stored* field), so the onchange's live push to *Recipient Bank* sticks.
  (`account.move.partner_bank_id` is itself a computed-but-editable field, which is what made this subtle.)
- The view passes **`context={'bank_by_internal_name': 1}`** so its dropdown **displays the
  Internal Name** (via the context-scoped `_compute_display_name` override). The regular
  *Recipient Bank* field still shows the IBAN, so nothing changes on documents.
- It mirrors the customer *Recipient Bank* domain (`[('partner_id.ref_company_ids', 'parent_of',
  company_id)]`) and is anchored **before `qr_code_method`** (the unique field that follows the
  customer-side Recipient Bank).

## Recipient Bank follows the currency (v17.0.1.7.0)

`account.move._compute_partner_bank_id` is overridden so the default *Recipient
Bank* is an account **in the currency of the document**.

Stock Odoo never looks at the currency (`account/models/account_move.py:892`): it
takes the partner's bank accounts, sorts trusted (`allow_out_payment`) first and
keeps the first one. With several company accounts that silently prints the wrong
IBAN — every customer invoice up to `INV/2026/00332` went out with an account
literally named `test-to-delete`, because it had the lowest id.

The rule now:

1. an account whose `currency_id` equals the document currency wins;
2. among those, trusted first, then **`sequence`**, then id;
3. no account in that currency → the stock result is left untouched, so a
   currency without an account of its own still gets a bank rather than a blank.

`sequence` is what decides between two accounts of the same currency, and it is
exposed with a handle in the bank accounts list — the default is dragged, not
inherited from creation order. **This is configuration, not code**: a fresh
database with all sequences at the default `10` falls back to id order.

`currency_id` is in `@api.depends`, so changing the currency of a draft invoice
re-picks the account and **overwrites a manual choice**. That is deliberate: the
alternative needs a "a human picked this" flag, and a bank account left over from
the previous currency is a worse default than one the accountant picks again. The
field remains `readonly=False` — any account, including one in another currency,
can still be selected by hand, and `recipient_bank_internal_id` mirrors it as
before.

Accounts with **no** currency (like `test-to-delete`) never match, so they can
only ever be reached through the stock fallback.

## Linked journal (read-only) on the bank account form
`res.partner.bank.linked_journal_id` (`models/res_partner_bank.py`) — a computed read-only
**Many2one** showing the bank journal this account is bound to, if any. It just surfaces the
account module's existing reverse `journal_id` One2many (`account.journal.bank_account_id`,
constrained to ≤1) as a single clickable field. Useful because a bank account **bound to a
journal cannot be deleted on its own** — this makes that link visible at a glance.

## Views
- `views/res_partner_bank_views.xml` — inherits `base.view_partner_bank_form` (the
  `bank_account_form`) → adds **Internal Name** and the read-only **Bank Journal** after the
  account number; and `base.view_partner_bank_tree` → shows Internal Name in the list.
- `views/account_move_views.xml` — inherits `account.view_move_form` → the helper field above.

## Multi-currency banks (same IBAN, different currency)
The base `res.partner.bank` uniqueness is `unique(sanitized_acc_number, partner_id)` — so one IBAN
+ one owner can't repeat, which blocks multi-currency banks (Revolut/Wise: one IBAN, several
currency pockets). This module **replaces** that constraint (same name `unique_number`, so it
overrides via Odoo's by-name `_sql_constraints` merge) with
**`unique(sanitized_acc_number, partner_id, currency_id)`** — so you can create one bank account per
currency with the **same real IBAN** (each → its own bank journal). The relaxed key is *looser*, so
existing data always satisfies it; `-u` just drops the old constraint and adds the new one.
- **You must set the `Currency` field** on each such account, otherwise (NULL currency) Postgres
  treats the rows as distinct anyway, but you lose the meaningful differentiator. The Currency field
  is on the standard bank form (under `group_multi_currency`).

## Tests

`tests/test_recipient_bank_currency.py` — one class, seven tests, covering the
currency rule and what the accountant does next.

The suite builds its own bank accounts in `setUpClass` rather than leaning on the
chart template, including one **with no currency and the lowest sequence** — the
exact shape of the leftover account that got printed on 302 invoices. Two USD
accounts exist so the `sequence` tie-break is actually exercised.

| Test | The rule it protects |
|---|---|
| `test_default_follows_the_invoice_currency` | USD invoice → USD account, EUR → EUR |
| `test_sequence_breaks_the_tie_between_two_accounts_of_one_currency` | reordering changes the default, so the handle is not decoration |
| `test_account_without_a_currency_is_never_the_default` | the leftover account cannot win |
| `test_currency_without_an_account_keeps_the_stock_default` | the field never ends up empty |
| `test_manual_choice_is_kept` | the rule is a default, not a constraint |
| `test_changing_the_currency_re_picks_the_account` | the agreed overwrite behaviour |
| `test_internal_name_field_mirrors_the_default` | the two fields never disagree |

Every assertion carries a sentence naming what breaks and what it costs, because
this failure is silent: nothing errors, the invoice simply goes out with the wrong
IBAN. `_assert_bank` renders the invoice currency and both accounts (internal name,
id, currency) on failure, so a red test says which account was picked instead.

Run them on a dedicated database — never `odoo_dev`, the live server holds it:

```bash
odoo-bin -d odoo_test_bankname \
  --addons-path=<community>,<enterprise>,<jito_modules> \
  --without-demo=all --http-port=8199 \
  -u bank_account_internal_name --test-enable \
  --test-tags /bank_account_internal_name --stop-after-init --log-level=test
```

First run needs `-i` instead of `-u` to create the database.

## Notes / constraints
- New field → install/upgrade required (`-i bank_account_internal_name`) to create the column.
- Pairs well with a config fix: set the company's correct **default** recipient bank and
  archive junk accounts, so the right account is picked automatically.
- Future option (B): fold the internal name into `display_name` to *show* it in dropdowns —
  deliberately not done here to avoid any chance of it appearing on documents.
