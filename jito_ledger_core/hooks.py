# -*- coding: utf-8 -*-

import logging

_logger = logging.getLogger(__name__)


# Per HLD §4.4 + Decisions #2 and #13: ship one minimal root account per
# semantic family per company in the **management-layer** chart of accounts
# (`jito.ledger.account`). Stock Odoo's `account.account` is intentionally
# untouched.
SEEDED_ROOTS = (
    ('FAAP.ROOT', 'FAAP — Default projection of statutory account meaning', 'equity'),
    ('MGT.ROOT', 'MGT — Final managerial / economic meaning', 'equity'),
    ('CLR.ROOT', 'CLR — Temporary clearing / transit / suspense', 'asset_current'),
    ('GRP.ROOT', 'GRP — Non-posting grouping nodes', 'off_balance'),
    # NL invoicing default buckets (17.0.1.5.0). The four functional MGT
    # accounts that every NL Customer Invoice / Credit Note / Vendor Bill /
    # Vendor Refund posts to by default. Users can override per line.
    # Display names tightened in 17.0.1.6.0 for clarity in the invoice UX.
    ('MGT.RECEIVABLE', 'Account Receivable', 'asset_receivable'),
    ('MGT.PAYABLE', 'Account Payable', 'liability_payable'),
    ('MGT.SALES', 'Product Sales', 'income'),
    ('MGT.EXPENSE', 'Operating Expenses', 'expense'),
)


def _ensure_leading_ledger_for_company(env, company):
    """Create the `jito.ledger(kind=leading)` record for `company` if missing.

    Per PRD §Vocabulary, every company has exactly one Leading Ledger
    (it is "the main accounting ledger… mandatory for all companies").
    The Leading Ledger record is a **label** for stock Odoo accounting
    in this company — it does not store entries. It exists so that
    Extension Ledgers can reference it via `base_ledger_id`.

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


def _ensure_extension_ledger_for_company(env, company):
    """Create the `jito.ledger(kind=extension)` record for `company` if missing,
    with `base_ledger_id` hard-locked to the company's Leading Ledger.

    Per the user's v1 design: every company has exactly one Extension
    Ledger that always sits on top of stock Odoo accounting (the Leading
    Ledger). Bringing up the Leading first via
    `_ensure_leading_ledger_for_company` is safe (also idempotent).
    """
    Ledger = env['jito.ledger']
    existing = Ledger.search([
        ('company_id', '=', company.id),
        ('kind', '=', 'extension'),
    ], limit=1)
    if existing:
        return existing
    leading = _ensure_leading_ledger_for_company(env, company)
    record = Ledger.create({
        'name': 'Extension Ledger',
        'code': 'EXT',
        'kind': 'extension',
        'company_id': company.id,
        'base_ledger_id': leading.id,
    })
    _logger.info(
        "jito_ledger_core: seeded Extension Ledger record (base=%s) for company %s",
        leading.code, company.display_name,
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
    if missing. ``default_account_id`` points at ``MGT.SALES`` so new
    Customer Invoice lines pre-fill it.
    """
    Journal = env['jito.ledger.journal']
    journal = Journal.search([
        ('code', '=', 'CINV'),
        ('company_id', '=', company.id),
    ], limit=1)
    if not journal:
        nl = _ensure_non_leading_ledger_for_company(env, company)
        sales_account = env['jito.ledger.account'].search([
            ('code', '=', 'MGT.SALES'),
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
    ``MGT.EXPENSE``. 17.0.2.1.0 also back-fills
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
            ('code', '=', 'MGT.EXPENSE'),
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


def _ensure_roots_for_company(env, company):
    """Create the four semantic root accounts for `company` if missing.

    Idempotent. Operates on `jito.ledger.account` only — never touches
    `account.account`.
    """
    Account = env['jito.ledger.account']
    created = []
    for code, name, account_type in SEEDED_ROOTS:
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
      * one `jito.ledger(kind=extension)` config record (base = Leading)
      * the four FAAP / MGT / CLR / GRP roots + four NL-invoicing
        default MGT buckets (Account Receivable, Payable, Product
        Sales, Expenses)
      * the Customer Invoices account.journal (linked to NL ledger
        with default_account_id=MGT.SALES) — 17.0.1.6.0

    Odoo 17 post-init hook signature: ``post_init_hook(env)`` — the env
    is already bound to SUPERUSER.
    """
    companies = env['res.company'].search([])
    for company in companies:
        _ensure_leading_ledger_for_company(env, company)
        _ensure_non_leading_ledger_for_company(env, company)
        _ensure_extension_ledger_for_company(env, company)
        _ensure_roots_for_company(env, company)
        _ensure_customer_invoices_journal_for_company(env, company)
        _ensure_vendor_bills_journal_for_company(env, company)
        _ensure_adjustments_journal_for_company(env, company)
