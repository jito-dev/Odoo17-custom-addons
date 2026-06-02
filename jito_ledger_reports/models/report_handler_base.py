# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import fields, models


class JitoLedgerReportHandlerBase(models.AbstractModel):
    """Shared helpers for all management-ledger account.report handlers.

    Lifted from ``jito.ledger.trial.balance.report.handler`` in 17.0.2.0.0
    so the new Partner Ledger handler (and any future handlers) can
    reuse the same domain shape, date-range parsing, and FX-translation
    math. Trial Balance keeps its behavior unchanged — it just calls
    these from the base now instead of owning them.

    Methods are deliberately ``self``-bound (not @staticmethod) so a
    subclass can override per-report. The base assumes:

      * Source model: ``jito.ledger.move.line``.
      * "Posted, non-voided, in-company date range" is the default
        line filter (callers can extend the domain).
      * FX presentation: translate transaction-currency amounts to
        company currency at report-render time via a rate map (HLD
        Decision #8 — we never store a company-currency snapshot).
    """

    _name = 'jito.ledger.report.handler.base'
    _description = 'Management Ledger Report Handler — Shared Base'

    def _build_domain(self, options, date_from, date_to, *,
                      model_name='jito.ledger.move.line',
                      include_drafts=False):
        """Standard line-level domain for one of three source models
        (17.0.3.0.0):

        - ``jito.ledger.move.line`` (default) — the management ledger.
          Adds ``move_state='posted'`` and ``move_id.is_voided=False``.
        - ``jito.ledger.statutory.view`` — FAAP projection of LL lines.
          The SQL view already restricts to ``parent_state='posted'``;
          we additionally filter ``state='posted'`` so drafts toggle has
          a consistent shape across sources (no-op for the view today,
          but explicit).
        - ``account.move.line`` — raw Leading Ledger, in case a future
          caller wants to bypass the FAAP projection.

        ``include_drafts``: when True, drops the posted-only clause.
        For ``jito.ledger.statutory.view`` it is a no-op (the view's
        own WHERE clause filters drafts out).
        """
        date_from_str = fields.Date.to_string(date_from)
        date_to_str = fields.Date.to_string(date_to)
        company_clause = ('company_id', 'in', self.env.companies.ids)
        date_clauses = [
            ('date', '>=', date_from_str),
            ('date', '<=', date_to_str),
        ]
        if model_name == 'jito.ledger.move.line':
            domain = [
                ('move_id.is_voided', '=', False),
                *date_clauses,
                company_clause,
            ]
            if not include_drafts:
                domain.insert(0, ('move_state', '=', 'posted'))
            return domain
        if model_name == 'jito.ledger.statutory.view':
            domain = [
                *date_clauses,
                company_clause,
            ]
            # The view is posted-only by construction (WHERE
            # parent_state='posted' inside _table_query). Keep a state
            # clause as a safety net so future view edits don't silently
            # leak drafts.
            domain.insert(0, ('state', '=', 'posted'))
            return domain
        if model_name == 'account.move.line':
            domain = [
                *date_clauses,
                company_clause,
            ]
            if not include_drafts:
                domain.insert(0, ('parent_state', '=', 'posted'))
            return domain
        raise ValueError(
            "Unsupported report source model: %r" % (model_name,)
        )

    def _resolve_date_range(self, options):
        """Pull date_from / date_to from the standard report options.

        Falls back to (jan 1 this year, today) if either is missing —
        matches what the stock account.report engine emits on first
        open with no filter selected.
        """
        date_opts = options.get('date') or {}
        date_from = fields.Date.from_string(date_opts.get('date_from')) \
            if date_opts.get('date_from') else fields.Date.today().replace(month=1, day=1)
        date_to = fields.Date.from_string(date_opts.get('date_to')) \
            if date_opts.get('date_to') else fields.Date.today()
        return date_from, date_to

    def _resolve_rate_date(self, options, date_to):
        """FX-translation reference date.

        Per FR-23:
          * period_end (default): rate at the last day of the report period.
          * spot_today: rate at report-run time.
        """
        policy = options.get('jito_rate_policy') or 'period_end'
        if policy == 'spot_today':
            return fields.Date.context_today(self)
        return date_to

    def _build_rate_map(self, rate_date, company):
        """Return ``{currency_id: rate-from-tx-to-company}``.

        Mirrors ``res.currency._get_query_currency_table``'s inverted
        convention: ``company_amount = source_amount × rate``. For
        currencies with no rate at ``rate_date``, Odoo's standard
        nearest-prior fallback applies (handled inside ``_get_rates``).
        """
        Currency = self.env['res.currency']
        all_currencies = Currency.search([])
        rates = all_currencies._get_rates(company, rate_date)
        company_rate = rates.get(company.currency_id.id, 1.0)
        rate_map = {}
        for cur in all_currencies:
            cur_rate = rates.get(cur.id, 1.0)
            rate_map[cur.id] = (company_rate / cur_rate) if cur_rate else 1.0
        return rate_map

    def _bucket_accounts_by_category(self, accounts):
        """Group accounts by ``category_id`` for report roll-up
        (17.0.7.0.0, depends on jito_ledger_core 17.0.3.0.0).

        Returns an ordered list of dicts, each with keys:
          * ``category`` — a single ``jito.ledger.account.category``
            recordset (empty recordset for the "(Uncategorized)"
            bucket).
          * ``accounts`` — a ``jito.ledger.account`` recordset sorted
            by ``code``.

        Outer ordering: categorized buckets first, sorted by
        ``(category.sequence, category.name)``; uncategorized bucket
        last. Empty buckets (no accounts) are omitted entirely.

        Used by Trial Balance and General Ledger handlers to emit
        per-category header / subtotal rows. Partner Ledger doesn't
        use this — it groups by partner, not account.
        """
        Account = self.env['jito.ledger.account']
        by_cat = defaultdict(lambda: Account.browse())
        for acc in accounts:
            by_cat[acc.category_id] += acc
        categorized = []
        uncategorized = Account.browse()
        for cat_rec, accs in by_cat.items():
            if not accs:
                continue
            if cat_rec:
                categorized.append((cat_rec, accs.sorted('code')))
            else:
                uncategorized = accs.sorted('code')
        categorized.sort(key=lambda kv: (kv[0].sequence, kv[0].name or ''))
        buckets = [
            {'category': cat, 'accounts': accs}
            for cat, accs in categorized
        ]
        if uncategorized:
            buckets.append({
                'category': self.env['jito.ledger.account.category'],
                'accounts': uncategorized,
            })
        return buckets

    @staticmethod
    def _make_money_column(currency, value):
        """Column dict for a Monetary cell in a report line.

        Two layers of defense for the "red on negative" rendering:
        (1) ``figure_type='monetary'`` + ``currency`` so the frontend
            ``AccountReportLineCell`` (line_cell.js) treats the cell as
            numeric and emits its own ``numeric text-end`` chain plus
            ``text-danger`` for negatives — the path stock partner_ledger
            uses.
        (2) We *also* append ``text-danger`` to the cell's ``class``
            ourselves so the class is on the rendered td even when the
            framework's path doesn't fire (e.g. an old client that
            doesn't read ``figure_type``, or any future refactor).
        The companion SCSS file ``jito_partner_ledger.scss`` adds a
        higher-specificity ``!important`` rule so ``.text-danger`` can't
        lose the cascade to ``.line_level_N > td { color: gray }`` from
        ``account_reports/.../account_report.scss``.
        """
        classes = 'number'
        if value and value < 0:
            classes += ' text-danger'
        return {
            'name': currency.format(value) if value else currency.format(0.0),
            'no_format': value,
            'figure_type': 'monetary',
            'currency': currency.id,
            'class': classes,
        }
