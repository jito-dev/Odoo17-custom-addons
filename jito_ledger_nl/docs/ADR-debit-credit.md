# ADR — Store company-currency `debit` / `credit` / `balance` on `jito.ledger.move.line`

- **Status**: Accepted (17.0.10.0.0)
- **Date**: 2026-06-02
- **Replaces**: HLD Decision #8 / FR-23 (tx-currency storage only, FX
  translation at report time)

## Context

The original architecture stored only transaction-currency amounts on
`jito.ledger.move.line` (`amount_currency` + `currency_id`) and
deferred FX translation to report time via
`res.currency._get_rates(company, rate_date)`. This held strictly to
FR-23's "FX is presentation, not posting" rule and avoided rate
snapshots on posted lines.

It worked correctly for single-currency moves but **broke for
multi-currency moves**: Restatement, Bridging, and Regrouping. When a
single move contains lines in two currencies that were calibrated
against each other at posting time (e.g. a Restatement's `CLR +1000
EUR` paired with `CLR -1200 USDT`, where the user picked the 1200
USDT as the destination), report-time translation uses Odoo's two
**independent** `res.currency.rate` values (EUR→USD and USDT→USD).
Those two rates imply a cross-currency ratio of `1.333 USD/EUR ÷ 1.0
USD/USDT = 1.333 EUR/USDT`, which generally differs from the rate
that was implicit in the calibration (`1200 / 1000 = 1.2`). The CLR
pair drifts apart in company currency, producing a residual that is
**a pure rate-mismatch artifact, not an economic event**, and which
fluctuates whenever the market rates move.

A user encountered this concretely: a `1000 EUR → 1200 USDT` matched
Restatement showed `+1000 EUR (1333 USD)` and `-1200 USDT (1200 USD)`
on the CLR account, with a residual `+133 USD` reported as an
imbalance even though both sides of the calibration had been
deliberately set at posting.

## Decision

Reverse FR-23 / Decision #8 for `jito.ledger.move.line`. The model
now mirrors stock Odoo's `account.move.line`:

- `company_currency_id` — Many2one related to `move_id.company_id.currency_id`
  (stored, readonly).
- `balance` — Monetary in company currency, computed by
  `_compute_balance` from `amount_currency × _convert(...)` at
  `line.date`. Stored, `readonly=False`, `precompute=True` — creators
  may pass an explicit value to override the default market-rate
  computation. Frozen at posting time.
- `debit` / `credit` — ±split of `balance` with `_compute_debit_credit`
  and matching inverses. Same currency field as `balance`.

`amount_currency` stays the tx-currency authority. The two
representations coexist; reports read whichever is appropriate.

### Posted-line immutability

A `write()` override on `jito.ledger.move.line` rejects edits to a
`_POSTED_PROTECTED_FIELDS` set (`amount_currency`, `balance`, `debit`,
`credit`, `currency_id`, `account_id`, `partner_id` and the
tx-currency debit/credit twins) when the line's parent move is in
state `posted`. The check is bypassed under sudo() so migrations and
admin tooling can still backfill. This catches the symmetric two-line
attack that the company-currency balance constraint alone would miss
(writing equal-and-opposite edits keeps the move sum at zero but
silently shifts account balances).

### Move-level balance constraint

A new `@api.constrains` method on `jito.ledger.move`,
`_check_balanced_in_company_currency`, requires
`sum(line.balance) == 0` per posted move in the company currency. It
runs alongside the existing `_check_balanced_per_currency` (HLD
Decision #10); both must hold for the move to post.

### Calibrated multi-currency creators

Restatement's FX path passes an explicit `balance` to `Line.create()`
for every line in a generated move. The magnitudes derive from a
per-source company-currency **anchor** computed once per source: for
matched mode the anchor is `abs(destination.amount_currency)
× market_rate(destination_currency → company_currency)`, for
unmatched it's the rate-derived target amount translated the same
way. Each line's `balance` is `±anchor` with the sign following its
`amount_currency`. The result: the CLR-src / CLR-tgt pair cancels in
company currency at posting, and the constraint passes.

Bridging and Regrouping generate single-currency-per-pair structures
(every FAAP-reversal + counterpart share one `currency_id`), so the
default `_compute_balance` translation naturally produces a balanced
move. They need no calibration.

Reversal moves (`jito.ledger.move.action_reverse`) copy
`-line.balance` from each source line so the counter cancels the
original in company currency at the original posting's rate, not the
reversal date's rate.

### Report consumption

The four `account.report` handlers (Trial Balance, General Ledger,
Partner Ledger, Categorized) now `read_group` on `debit:sum,
credit:sum` directly — no more `rate_map` multiplication at render
time. `_build_rate_map`, `_resolve_rate_date`, and the
`jito_rate_policy` chip remain on the base handler for transitional
back-compat but are unused by the read paths; they will be removed
in a future cleanup.

### Migration

`jito_ledger_nl/migrations/17.0.10.0.0/post-migrate.py` backfills
`balance` (and via compute also `debit`/`credit`) on existing posted
lines using `res.currency._convert(amount_currency,
company_currency, company, line.date)`. The module is young; backfill
volume is negligible.

## Consequences

### Positive

- Multi-currency moves balance cleanly in company currency at
  posting, eliminating the CLR-drift class of bugs.
- Reports read from stored columns — simpler code, faster queries (no
  per-currency rate lookup at render time).
- Posted-line immutability is enforced at the write layer in addition
  to the constraint layer.
- Aligned with stock Odoo's `account.move.line` shape, easing future
  feature parity (e.g. revaluation entries).

### Negative

- Rate snapshot is permanent: rate changes after posting don't
  retroactively re-translate existing lines. This is identical to
  stock Odoo's behavior and matches mainstream accounting practice,
  but it loses the "always reflect today's rate in historical
  reports" flexibility FR-23 offered.
- One-time migration cost (one query backfilling balances on existing
  lines).
- `jito_rate_policy` option chip on report filters is now vestigial.

### Out of scope (later)

- Currency revaluation entries (stock Odoo's period-end FX gain/loss
  recognition) — the balance is frozen forever once posted; a
  separate revaluation feature can be layered on if needed.
- Removing `_build_rate_map` / `_resolve_rate_date` / `jito_rate_policy`
  — deprecated this cycle, removed in a future cleanup.

## Versions

- `jito_ledger_nl` 17.0.9.0.6 → **17.0.10.0.0** (schema + constraint +
  migration + write override).
- `jito_ledger_adjustments` 17.0.7.3.2 → **17.0.8.0.0** (Restatement
  calibrated balance + reversal-line carry).
- `jito_ledger_reports` 17.0.8.0.0 → **17.0.9.0.0** (handlers consume
  frozen columns).
