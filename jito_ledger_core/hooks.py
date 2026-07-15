# -*- coding: utf-8 -*-

import logging

_logger = logging.getLogger(__name__)


# Greenfield seed (17.0.4.0.0 CoA redesign). The management-layer chart of
# accounts (`jito.ledger.account`) now uses **statutory-aligned numeric
# codes** under two prefixes only — `FAAP.` (read-only statutory mirror) and
# `MGT.` (management posting). Stock Odoo's `account.account` is untouched.
#
# Each row is ``(code, name, account_type, is_clearing)``. We ship a minimal
# example management CoA — a handful of statutory-aligned coded accounts
# (incl. a mandatory example **bank** account, later wired to a DeFi wallet,
# and a **clearing** account). Users prune what they don't need and extend by
# example; nothing here is load-bearing beyond the four invoicing-default
# buckets resolved by code in ``jito_ledger_nl``. No structural "root" anchor
# accounts are seeded — the CoA is a flat list (grouping is by
# ``account_type``), so a bare ``*.ROOT`` served no purpose.
SEEDED_ROOTS = (
    # Example management accounts — statutory-aligned numeric codes.
    ('MGT.101401', 'Bank (example — connect a DeFi wallet)', 'asset_cash', False),
    ('MGT.101402', 'DeFi Wallet (example)', 'asset_cash', False),
    ('MGT.101900', 'Clearing / Suspense (example)', 'asset_current', True),
    # NL invoicing default buckets. Every NL Customer Invoice / Credit Note /
    # Vendor Bill / Vendor Refund posts to these by default (users override
    # per line or via company config). Resolved by code in jito_ledger_nl —
    # keep the codes in sync with ``jito_ledger_move._get_default_*``.
    ('MGT.132000', 'Account Receivable', 'asset_receivable', False),
    ('MGT.211000', 'Account Payable', 'liability_payable', False),
    ('MGT.400500', 'Product Sales', 'income', False),
    ('MGT.600500', 'Operating Expenses', 'expense', False),
)


def _ensure_leading_ledger_for_company(env, company):
    """Create the `jito.ledger(kind=leading)` record for `company` if missing.

    Per PRD §Vocabulary, every company has exactly one Leading Ledger
    (it is "the main accounting ledger… mandatory for all companies").
    The Leading Ledger record is a **label** for stock Odoo accounting
    in this company — it does not store entries.

    Idempotent: if a leading ledger already exists for the company,
    nothing happens.
    """
    Ledger = env['jito.ledger']
    existing = Ledger.search([
        ('company_id', '=', company.id),
        ('kind', '=', 'leading'),
    ], limit=1)
    if existing:
        return existing
    record = Ledger.create({
        'name': 'Leading Ledger',
        'code': 'LL',
        'kind': 'leading',
        'company_id': company.id,
    })
    _logger.info(
        "jito_ledger_core: seeded Leading Ledger record for company %s",
        company.display_name,
    )
    return record


def _ensure_non_leading_ledger_for_company(env, company):
    """Create the `jito.ledger(kind=non_leading)` record for `company` if missing.

    Per the user's v1 design (17.0.1.4.0 refactor), every company has
    exactly one Non-Leading Ledger — system-managed, no creation flow.
    Idempotent: if one already exists, returns it untouched.
    """
    Ledger = env['jito.ledger']
    existing = Ledger.search([
        ('company_id', '=', company.id),
        ('kind', '=', 'non_leading'),
    ], limit=1)
    if existing:
        return existing
    record = Ledger.create({
        'name': 'Non-Leading Ledger',
        'code': 'NL',
        'kind': 'non_leading',
        'company_id': company.id,
    })
    _logger.info(
        "jito_ledger_core: seeded Non-Leading Ledger record for company %s",
        company.display_name,
    )
    return record


def _set_company_default_journal(company, field_name, journal):
    """Write ``company[field_name] = journal`` *only if currently blank*.

    Idempotent and admin-friendly: a user who deliberately rebinds a
    default-journal field to a custom journal (e.g. a ``CADJ-LEGAL``)
    keeps their override across re-upgrades. Only blanks are filled.

    Defensive against ``jito_ledger_nl`` not being installed: the
    `jito_default_*_journal_id` fields live there. If the company
    model doesn't have ``field_name``, this is a no-op.
    """
    if not field_name or not journal:
        return
    if field_name not in company._fields:
        return
    if company[field_name]:
        return
    company.write({field_name: journal.id})
    _logger.info(
        "jito_ledger_core: set company %s.%s = %s (was blank).",
        company.display_name, field_name, journal.display_name,
    )


def _ensure_customer_invoices_journal_for_company(env, company):
    """Auto-seed the Customer Invoices ML journal per company
    (17.0.2.0.0 — direct ``jito.ledger.journal`` creation; replaces
    the 17.0.1.6.0 stock-``account.journal`` + ``rel`` pairing).
    17.0.2.1.0 also back-fills ``company.jito_default_invoice_journal_id``
    when blank.

    Idempotent: search by ``(company_id, code='CINV')``; create only
    if missing. ``default_account_id`` points at ``MGT.400500`` (Product
    Sales) so new Customer Invoice lines pre-fill it.
    """
    Journal = env['jito.ledger.journal']
    journal = Journal.search([
        ('code', '=', 'CINV'),
        ('company_id', '=', company.id),
    ], limit=1)
    if not journal:
        nl = _ensure_non_leading_ledger_for_company(env, company)
        sales_account = env['jito.ledger.account'].search([
            ('code', '=', 'MGT.400500'),
            ('company_id', '=', company.id),
        ], limit=1)
        journal = Journal.create({
            'name': 'Customer Invoices',
            'code': 'CINV',
            'type': 'sale',
            'ledger_id': nl.id,
            'default_account_id': sales_account.id if sales_account else False,
        })
        _logger.info(
            "jito_ledger_core: seeded Customer Invoices ML journal for company %s",
            company.display_name,
        )
    _set_company_default_journal(company, 'jito_default_invoice_journal_id', journal)
    return journal


def _ensure_vendor_bills_journal_for_company(env, company):
    """Auto-seed the Vendor Bills ML journal per company (17.0.2.0.0).

    Same pattern as ``_ensure_customer_invoices_journal_for_company``
    but for the purchase side; ``default_account_id`` points at
    ``MGT.600500`` (Operating Expenses). 17.0.2.1.0 also back-fills
    ``company.jito_default_bill_journal_id`` when blank.
    """
    Journal = env['jito.ledger.journal']
    journal = Journal.search([
        ('code', '=', 'CBILL'),
        ('company_id', '=', company.id),
    ], limit=1)
    if not journal:
        nl = _ensure_non_leading_ledger_for_company(env, company)
        expense_account = env['jito.ledger.account'].search([
            ('code', '=', 'MGT.600500'),
            ('company_id', '=', company.id),
        ], limit=1)
        journal = Journal.create({
            'name': 'Vendor Bills',
            'code': 'CBILL',
            'type': 'purchase',
            'ledger_id': nl.id,
            'default_account_id': expense_account.id if expense_account else False,
        })
        _logger.info(
            "jito_ledger_core: seeded Vendor Bills ML journal for company %s",
            company.display_name,
        )
    _set_company_default_journal(company, 'jito_default_bill_journal_id', journal)
    return journal


def _ensure_adjustments_journal_for_company(env, company):
    """Auto-seed the Management Adjustments ML journal per company
    (17.0.2.1.0). Pairs with the existing
    ``company.jito_default_adjustments_journal_id`` field used by the
    Bridge / Restate / Regroup wizards' ``default_get`` chain.

    No ``default_account_id`` is set — adjustments wizards always pick
    the per-line accounts explicitly (FAAP reversal + MGT target etc.),
    so a journal-level pre-fill would be misleading.
    """
    Journal = env['jito.ledger.journal']
    journal = Journal.search([
        ('code', '=', 'CADJ'),
        ('company_id', '=', company.id),
    ], limit=1)
    if not journal:
        nl = _ensure_non_leading_ledger_for_company(env, company)
        journal = Journal.create({
            'name': 'Management Adjustments',
            'code': 'CADJ',
            'type': 'general',
            'ledger_id': nl.id,
        })
        _logger.info(
            "jito_ledger_core: seeded Management Adjustments ML journal for company %s",
            company.display_name,
        )
    _set_company_default_journal(
        company, 'jito_default_adjustments_journal_id', journal,
    )
    return journal


def _ensure_bank_journal_for_company(env, company):
    """Auto-seed the example Bank ML journal per company (17.0.4.0.0).

    Wires the mandatory example bank account (``MGT.101401``) to a
    ``type='bank'`` management journal and points its clearing/suspense
    slot at the example clearing account (``MGT.101900``). This gives the
    fresh install a working bank-reconciliation surface out of the box —
    the account the user later connects to a DeFi wallet.

    Idempotent: search by ``(company_id, code='CBANK')``; create only if
    missing. No ``default_account_id`` — bank lines resolve via the rec
    widget, not a journal pre-fill.
    """
    Journal = env['jito.ledger.journal']
    journal = Journal.search([
        ('code', '=', 'CBANK'),
        ('company_id', '=', company.id),
    ], limit=1)
    if not journal:
        nl = _ensure_non_leading_ledger_for_company(env, company)
        Account = env['jito.ledger.account']
        bank_account = Account.search([
            ('code', '=', 'MGT.101401'),
            ('company_id', '=', company.id),
        ], limit=1)
        clearing_account = Account.search([
            ('code', '=', 'MGT.101900'),
            ('company_id', '=', company.id),
        ], limit=1)
        journal = Journal.create({
            'name': 'Bank (example)',
            'code': 'CBANK',
            'type': 'bank',
            'ledger_id': nl.id,
            'bank_account_id': bank_account.id if bank_account else False,
            'suspense_account_id': clearing_account.id if clearing_account else False,
        })
        _logger.info(
            "jito_ledger_core: seeded example Bank ML journal for company %s",
            company.display_name,
        )
    return journal


def _ensure_roots_for_company(env, company):
    """Create the seed management accounts for `company` if missing.

    Idempotent. Operates on `jito.ledger.account` only — never touches
    `account.account`.
    """
    Account = env['jito.ledger.account']
    created = []
    for code, name, account_type, is_clearing in SEEDED_ROOTS:
        existing = Account.search([
            ('code', '=', code),
            ('company_id', '=', company.id),
        ], limit=1)
        if existing:
            continue
        Account.create({
            'code': code,
            'name': name,
            'account_type': account_type,
            'is_clearing': is_clearing,
            'company_id': company.id,
        })
        created.append(code)
    if created:
        _logger.info(
            "jito_ledger_core: seeded %s into jito.ledger.account for company %s",
            ', '.join(created), company.display_name,
        )


def post_init_hook(env):
    """Seed per company:
      * one `jito.ledger(kind=leading)` config record
      * one `jito.ledger(kind=non_leading)` config record
      * a minimal example management CoA with statutory-aligned numeric
        codes (example bank MGT.101401, DeFi wallet MGT.101402, clearing
        MGT.101900, and the four NL-invoicing default buckets: Receivable
        132000, Payable 211000, Sales 400500, Expenses 600500) — no bare
        structural root accounts
      * the Customer Invoices / Vendor Bills / Management Adjustments
        ML journals, plus an example Bank journal (CBANK) wired to
        MGT.101401 with clearing/suspense = MGT.101900 (17.0.4.0.0)

    Odoo 17 post-init hook signature: ``post_init_hook(env)`` — the env
    is already bound to SUPERUSER.
    """
    companies = env['res.company'].search([])
    for company in companies:
        _ensure_leading_ledger_for_company(env, company)
        _ensure_non_leading_ledger_for_company(env, company)
        _ensure_roots_for_company(env, company)
        _ensure_customer_invoices_journal_for_company(env, company)
        _ensure_vendor_bills_journal_for_company(env, company)
        _ensure_adjustments_journal_for_company(env, company)
        _ensure_bank_journal_for_company(env, company)
