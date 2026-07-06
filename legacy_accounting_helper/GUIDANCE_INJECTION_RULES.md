# Injection Rules — route Revolut transactions to GL accounts

Configurable rules that set each injected line's GL counterpart (`counterpart_account_id`) by matching the
**merchant** or **description**, so card SaaS → software sub-accounts, `To PE *` → Subcontractors, etc.

## Routing precedence (at injection, `revolut.transaction.action_inject_to_accounting`)
1. **Internal transfer** (`transfer_between_accounts`) → company transfer account.
2. **FCF** line → `_fcf_counterpart_account` (per-account FCF config).
3. **Injection Rules** → first active rule by `sequence` whose pattern matches (`_route_to_gl_account`).
4. **Fallback** → `legacy.accounting.config.revolut_suspense_account_id`, else the journal suspense (unchanged).

The routed account + matched rule are stored on the transaction (`routed_account_id`, `matched_rule_id`) so you can
see/verify what posted (columns in *Expenses Matching*, fields on the form). They're cleared on *Remove from Accounting*.

## Analytic tag: "Data Source → Revolut Business API"
Every injected line's **GL counterpart** is tagged with the analytic account **Revolut Business API** under the
plan **Data Source** (`analytic_distribution = {<account>: 100}`), so all Revolut-originated activity is reportable
by data source. The plan/account are get-or-created idempotently (`revolut.transaction._ensure_data_source_analytic`)
— at injection and by *Set up routing accounts*. Tagging is non-blocking (never fails an injection) and applies to
every type (rule-routed, FCF, transfer, suspense). The liquidity/bank line is not tagged.

## The model (`revolut.injection.rule`, menu Configuration → Injection Rules)
- `sequence` (drag to reorder = priority), `name`, `active`.
- `match_field` (Merchant / Description / Either), `match_type` (contains / regex / equals), `pattern`,
  optional `transaction_type`, `account_id` (GL target).
- `match_type` semantics: `contains`/`equals` are case-insensitive and accept a **pipe list** (`openai|claude|cursor`
  = match any token); `regex` is a Python `re.search` (case-insensitive). A `@api.constrains` validates the regex.
- `match_count` ("Hits") + **Preview matches** button = a dry-run over existing transactions before you trust a rule.

## GL accounts
`legacy.accounting.config.action_setup_routing_accounts` ("Set up routing accounts" on the config form) idempotently
get-or-creates the default chart (reuses `_ensure_account`): `6000` Subcontractor services (COGS), `6101` AI Tools &
APIs, `6102` Collaboration & Productivity, `6103` Hosting & Infrastructure, `6104` Sales Tools, `6109` Other SaaS &
Tools, `6500` Bank & FX charges, `6999` Revolut Suspense (set as fallback), `7000/7001` Revenue Dev/Design — plus a
`Software & Subscriptions` account group (prefix 61) for roll-up. Codes are suggestions; existing codes are reused.

## AI rule suggestions (`revolut.rule.suggest.wizard`)
Select unmatched transactions → ⚙ Actions → **Suggest Injection Rules (AI)** → pick the target GL account →
**Propose Rules**. The AI proposes routing rules (it does *not* apply them); each shows a **Covers** count over your
selection. Review/edit, then **Create Rules** writes them into *Injection Rules*. Falls back to a deterministic
"merchant contains <distinct merchants>" rule if the AI is unavailable. Uses the same OpenAI key as the rest of the
module (company key → `openai.config`).

## Dev-phase loop (change routing)
Edit a rule → select the affected transactions → **Remove from Accounting** (unreconciles → drafts → deletes the
move → clears the link) → **Inject** again → the new rule re-applies. No separate "re-route" action.

## Key code
- `models/revolut_injection_rule.py` — the rule model + matcher + preview.
- `models/revolut_transaction.py` — `_route_to_gl_account` + the hook in `action_inject_to_accounting`;
  `routed_account_id` / `matched_rule_id` fields.
- `models/legacy_accounting_config.py` — `revolut_suspense_account_id`, `_ROUTING_ACCOUNT_SET`,
  `action_setup_routing_accounts`.
