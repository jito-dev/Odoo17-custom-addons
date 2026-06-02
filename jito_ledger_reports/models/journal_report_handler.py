# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class JitoJournalReportCustomHandler(models.AbstractModel):
    """Custom handler for the Management Journal Report (17.0.9.3.0).

    Mirrors stock Odoo's ``account.journal.report.handler``
    (``odoo17_enterprise/.../account_journal_report.py``) but runs
    against ``jito.ledger.move`` / ``jito.ledger.move.line`` and the
    NL chart of accounts.

    Layout:
      * **Level 2** rows — one per ``jito.ledger.move``, sorted by
        ``(journal, date, name)``. Unfoldable. Columns show the
        move's date, ref, partner, and journal-side totals (sum of
        debit / sum of credit across the move's lines).
      * **Level 3** rows (on expand) — the move's own journal items
        with Account, Label, Partner, Debit, Credit.

    Both row levels expose caret options:
      * Move row → **View Entry** opens the ``jito.ledger.move`` form.
      * Line row → **View Entry** opens the parent move via
        ``action_param='move_id'``.
    """

    _name = 'jito.ledger.journal.report.handler'
    _inherit = ['account.report.custom.handler', 'jito.ledger.report.handler.base']
    _description = 'Management Journal Report Custom Handler'

    EXPAND_FUNC = '_report_expand_unfoldable_line_jito_journal_report'
    EXPAND_FUNC_JOURNAL = '_report_expand_unfoldable_line_jito_journal_section'

    def _caret_options_initializer(self):
        return {
            'jito.ledger.move': [
                {'name': _("View Entry"),
                 'action': 'caret_option_open_record_form'},
            ],
            'jito.ledger.move.line': [
                {'name': _("View Entry"),
                 'action': 'caret_option_open_record_form',
                 'action_param': 'move_id'},
            ],
        }

    def _custom_options_initializer(self, report, options, previous_options=None):
        super()._custom_options_initializer(report, options, previous_options=previous_options)
        prev = previous_options or {}
        options['jito_rate_policy'] = prev.get('jito_rate_policy') or 'period_end'

    # ---- main report generation -----------------------------------------

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        """17.0.9.3.2 — emit one **unfoldable journal section row**
        per journal that has activity in the period. Per-journal
        Debit/Credit totals are pre-computed via ``read_group`` for
        speed. The moves under each journal are emitted on demand by
        ``_report_expand_unfoldable_line_jito_journal_section``;
        each move row is itself unfoldable and reveals its lines via
        the existing per-move expand callback.
        """
        company = self.env.company
        company_currency = company.currency_id

        date_from, date_to = self._resolve_date_range(options)
        include_drafts = bool(options.get('show_draft') or options.get('all_entries'))

        # Per-journal totals via read_group on the line table — sum
        # debit/credit grouped by journal_id, filtered by period +
        # company + posted state + the standard journal-chip filter.
        date_from_str = fields.Date.to_string(date_from)
        date_to_str = fields.Date.to_string(date_to)
        line_domain = [
            ('date', '>=', date_from_str),
            ('date', '<=', date_to_str),
            ('company_id', 'in', self.env.companies.ids),
            ('move_id.is_voided', '=', False),
        ]
        if not include_drafts:
            line_domain.append(('move_state', '=', 'posted'))
        selected_journal_ids = [
            j['id'] for j in (options.get('journals') or [])
            if j.get('selected')
        ]
        if selected_journal_ids:
            line_domain.append(('journal_id', 'in', selected_journal_ids))

        Line = self.env['jito.ledger.move.line']
        groups = Line.read_group(
            domain=line_domain,
            fields=['journal_id', 'debit:sum', 'credit:sum'],
            groupby=['journal_id'],
            lazy=False,
        )
        per_journal = {}
        for grp in groups:
            jid = grp.get('journal_id') and grp['journal_id'][0]
            if not jid:
                continue
            per_journal[jid] = {
                'debit': grp.get('debit') or 0.0,
                'credit': grp.get('credit') or 0.0,
            }

        Journal = self.env['jito.ledger.journal']
        journals = Journal.browse(list(per_journal.keys())).sorted(
            lambda j: (j.code or '', j.name or '', j.id),
        )

        lines = []
        total_debit = total_credit = 0.0
        for journal in journals:
            tots = per_journal[journal.id]
            debit = company_currency.round(tots['debit'])
            credit = company_currency.round(tots['credit'])
            total_debit += debit
            total_credit += credit
            journal_label = (
                '%s %s' % (journal.code or '', journal.name or '')
            ).strip()
            lines.append((0, {
                'id': report._get_generic_line_id(
                    'jito.ledger.journal', journal.id,
                    markup='journal_section',
                ),
                'name': journal_label or _('Journal #%s', journal.id),
                'level': 1,
                'class': 'total',
                'unfoldable': True,
                'unfolded': bool(options.get('unfold_all')),
                'expand_function': self.EXPAND_FUNC_JOURNAL,
                'columns': [
                    {'name': '', 'class': 'date'},
                    {'name': '', 'class': 'text'},
                    {'name': '', 'class': 'text'},
                    {'name': '', 'class': 'text'},
                    self._make_money_column(company_currency, debit),
                    self._make_money_column(company_currency, credit),
                ],
            }))

        # Grand Total at the bottom.
        lines.append((0, {
            'id': report._get_generic_line_id(False, False, markup='total'),
            'name': _('Total'),
            'level': 1,
            'class': 'total',
            'columns': [
                {'name': '', 'class': 'date'},
                {'name': '', 'class': 'text'},
                {'name': '', 'class': 'text'},
                {'name': '', 'class': 'text'},
                self._make_money_column(company_currency, company_currency.round(total_debit)),
                self._make_money_column(company_currency, company_currency.round(total_credit)),
            ],
        }))
        return lines

    # ---- expand callbacks -----------------------------------------------

    def _report_expand_unfoldable_line_jito_journal_section(
            self, line_dict_id, groupby, options, progress, offset,
            unfold_all_batch_data=None):
        """Drill-down on a journal-section row (level 1 → level 2):
        emit one unfoldable row per ``jito.ledger.move`` on this
        journal, in the period, sorted by ``(date, name, id)``. Each
        move row's expand callback then emits its lines.
        """
        report = self.env['account.report'].browse(options.get('report_id'))
        if not report:
            report = self.env.ref(
                'jito_ledger_reports.management_journal_report',
                raise_if_not_found=False,
            )
        if not report:
            raise UserError(_(
                "Journal Report record not found. Re-upgrade the "
                "jito_ledger_reports module."
            ))

        markup, model, journal_id = report._parse_line_id(line_dict_id)[-1]
        if model != 'jito.ledger.journal':
            raise UserError(_(
                "Wrong ID for Journal Report section to expand: %s",
                line_dict_id,
            ))

        company = self.env.company
        company_currency = company.currency_id
        date_from, date_to = self._resolve_date_range(options)
        include_drafts = bool(options.get('show_draft') or options.get('all_entries'))

        domain = [
            ('journal_id', '=', journal_id),
            ('date', '>=', fields.Date.to_string(date_from)),
            ('date', '<=', fields.Date.to_string(date_to)),
            ('company_id', 'in', self.env.companies.ids),
            ('is_voided', '=', False),
        ]
        if not include_drafts:
            domain.append(('state', '=', 'posted'))

        Move = self.env['jito.ledger.move']
        moves = Move.search(domain, order='date, name, id')

        lines = []
        for move in moves:
            move_lines = move.line_ids
            sum_debit = company_currency.round(sum(move_lines.mapped('debit')))
            sum_credit = company_currency.round(sum(move_lines.mapped('credit')))
            lines.append({
                'id': report._get_generic_line_id(
                    'jito.ledger.move', move.id,
                    parent_line_id=line_dict_id,
                ),
                'name': move.name or _('Draft'),
                'level': 2,
                'parent_id': line_dict_id,
                'unfoldable': True,
                'unfolded': bool(options.get('unfold_all')),
                'expand_function': self.EXPAND_FUNC,
                'caret_options': 'jito.ledger.move',
                'columns': [
                    {
                        'name': fields.Date.to_string(move.date) if move.date else '',
                        'class': 'date',
                    },
                    {'name': '', 'class': 'text'},
                    {'name': move.ref or '', 'class': 'text'},
                    {
                        'name': move.partner_id.display_name if move.partner_id else '',
                        'class': 'text',
                    },
                    self._make_money_column(company_currency, sum_debit),
                    self._make_money_column(company_currency, sum_credit),
                ],
            })
        return {
            'lines': lines,
            'offset_increment': len(lines),
            'has_more': False,
            'progress': {},
        }

    def _report_expand_unfoldable_line_jito_journal_report(
            self, line_dict_id, groupby, options, progress, offset,
            unfold_all_batch_data=None):
        """Drill-down: emit the clicked move's journal items at
        level 3 with Account / Label / Partner / Debit / Credit.
        Date column is blank (already shown on the parent move row).
        """
        report = self.env['account.report'].browse(options.get('report_id'))
        if not report:
            report = self.env.ref(
                'jito_ledger_reports.management_journal_report',
                raise_if_not_found=False,
            )
        if not report:
            raise UserError(_(
                "Journal Report record not found. Re-upgrade the "
                "jito_ledger_reports module."
            ))

        markup, model, move_id = report._parse_line_id(line_dict_id)[-1]
        if model != 'jito.ledger.move':
            raise UserError(_(
                "Wrong ID for Journal Report line to expand: %s",
                line_dict_id,
            ))

        company = self.env.company
        company_currency = company.currency_id
        move = self.env['jito.ledger.move'].browse(move_id).exists()
        if not move:
            return {
                'lines': [], 'offset_increment': 0,
                'has_more': False, 'progress': {},
            }

        lines = []
        for line in move.line_ids.sorted('id'):
            account = line.account_id
            account_label = '%s %s' % (
                account.code or '', account.name or '',
            )
            debit = company_currency.round(line.debit or 0.0)
            credit = company_currency.round(line.credit or 0.0)
            lines.append({
                'id': report._get_generic_line_id(
                    'jito.ledger.move.line', line.id,
                    parent_line_id=line_dict_id,
                ),
                'name': line.name or '',
                'level': 3,
                'parent_id': line_dict_id,
                'caret_options': 'jito.ledger.move.line',
                'columns': [
                    {'name': '', 'class': 'date'},
                    {'name': account_label.strip(), 'class': 'text'},
                    {'name': line.name or '', 'class': 'text'},
                    {
                        'name': (
                            line.partner_id.display_name
                            if line.partner_id else ''
                        ),
                        'class': 'text',
                    },
                    self._make_money_column(company_currency, debit),
                    self._make_money_column(company_currency, credit),
                ],
            })

        return {
            'lines': lines,
            'offset_increment': len(lines),
            'has_more': False,
            'progress': {},
        }
