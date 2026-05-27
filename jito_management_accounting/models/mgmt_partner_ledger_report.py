from odoo import api, models, _, fields
from collections import defaultdict
from datetime import timedelta


class MgmtPartnerLedgerReportHandler(models.AbstractModel):
    _name = 'mgmt.partner.ledger.report.handler'
    _inherit = 'account.report.custom.handler'
    _description = 'Management Partner Ledger Report Handler'

    def _get_custom_display_config(self):
        return {
            'css_custom_class': 'mgmt_partner_ledger',
        }

    def _custom_options_initializer(self, report, options, previous_options=None):
        super()._custom_options_initializer(report, options, previous_options=previous_options)
        # Remove the 'all_entries' key so the engine won't check for unposted
        # account.move records — that warning is irrelevant for management data.
        options.pop('all_entries', None)

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        partner_lines, totals_by_column_group = self._build_partner_lines(report, options)
        lines = [(0, line) for line in partner_lines]
        lines.append((0, self._get_report_line_total(report, options, totals_by_column_group)))
        return lines

    def _build_partner_lines(self, report, options):
        lines = []
        totals_by_column_group = {
            column_group_key: {'debit': 0.0, 'credit': 0.0, 'balance': 0.0}
            for column_group_key in options['column_groups']
        }

        partners_results = self._query_partners(report, options)
        for partner, results in partners_results:
            partner_values = defaultdict(dict)
            for column_group_key in options['column_groups']:
                partner_sum = results.get(column_group_key, {})
                partner_values[column_group_key]['debit'] = partner_sum.get('debit', 0.0)
                partner_values[column_group_key]['credit'] = partner_sum.get('credit', 0.0)
                partner_values[column_group_key]['balance'] = partner_sum.get('balance', 0.0)

                totals_by_column_group[column_group_key]['debit'] += partner_values[column_group_key]['debit']
                totals_by_column_group[column_group_key]['credit'] += partner_values[column_group_key]['credit']
                totals_by_column_group[column_group_key]['balance'] += partner_values[column_group_key]['balance']

            lines.append(self._get_report_line_partners(report, options, partner, partner_values))

        return lines, totals_by_column_group

    def _query_partners(self, report, options):
        """Query mgmt_ledger_line grouped by partner, return list of (partner, {col_group: sums})."""
        company_currency = self.env.company.currency_id
        company_ids = tuple(report.get_report_company_ids(options))
        groupby_partners = {}

        for column_group_key, column_group_options in report._split_options_per_column_group(options).items():
            date_from = column_group_options['date']['date_from']
            date_to = column_group_options['date']['date_to']

            query = """
                SELECT
                    mll.partner_id AS groupby,
                    %(column_group_key)s AS column_group_key,
                    SUM(mll.debit) AS debit,
                    SUM(mll.credit) AS credit,
                    SUM(mll.balance) AS balance
                FROM mgmt_ledger_line mll
                WHERE mll.company_id IN %(company_ids)s
                  AND mll.date >= %(date_from)s
                  AND mll.date <= %(date_to)s
                GROUP BY mll.partner_id
            """
            params = {
                'column_group_key': column_group_key,
                'company_ids': company_ids,
                'date_from': date_from,
                'date_to': date_to,
            }

            # Apply partner filter if active
            partner_ids = options.get('partner_ids', [])
            if partner_ids:
                query = query.replace(
                    'GROUP BY mll.partner_id',
                    'AND mll.partner_id IN %(partner_ids)s\n                GROUP BY mll.partner_id'
                )
                params['partner_ids'] = tuple(partner_ids)

            self._cr.execute(query, params)
            for res in self._cr.dictfetchall():
                fields_to_check = ['balance', 'debit', 'credit']
                if any(not company_currency.is_zero(res[field]) for field in fields_to_check):
                    groupby_partners.setdefault(res['groupby'], defaultdict(lambda: defaultdict(float)))
                    for field in fields_to_check:
                        groupby_partners[res['groupby']][column_group_key][field] += res[field]

        # Retrieve the partners
        if groupby_partners:
            partner_ids_list = [pid for pid in groupby_partners.keys() if pid is not None]
            if partner_ids_list:
                partners = self.env['res.partner'].with_context(active_test=False).search(
                    [('id', 'in', partner_ids_list)]
                )
            else:
                partners = self.env['res.partner']
        else:
            partners = self.env['res.partner']

        # Add Unknown Partner if needed
        result = [(partner, groupby_partners[partner.id]) for partner in partners]
        if None in groupby_partners:
            result.append((None, groupby_partners[None]))

        return result

    def _get_initial_balance_values(self, report, partner_ids, options):
        """Get initial balances (before date_from) for the given partners."""
        company_ids = tuple(report.get_report_company_ids(options))
        init_balance_by_col_group = {
            partner_id: {column_group_key: {} for column_group_key in options['column_groups']}
            for partner_id in partner_ids
        }

        for column_group_key, column_group_options in report._split_options_per_column_group(options).items():
            date_from = fields.Date.from_string(column_group_options['date']['date_from'])
            date_before = date_from - timedelta(days=1)

            # Build partner clause
            partner_ids_wo_none = [pid for pid in partner_ids if pid is not None]
            clauses = []
            params = {
                'column_group_key': column_group_key,
                'company_ids': company_ids,
                'date_to': fields.Date.to_string(date_before),
            }

            if partner_ids_wo_none:
                clauses.append('mll.partner_id IN %(partner_ids_list)s')
                params['partner_ids_list'] = tuple(partner_ids_wo_none)
            if None in partner_ids:
                clauses.append('mll.partner_id IS NULL')

            if not clauses:
                continue

            partner_clause = '(' + ' OR '.join(clauses) + ')'

            query = f"""
                SELECT
                    mll.partner_id,
                    %(column_group_key)s AS column_group_key,
                    SUM(mll.debit) AS debit,
                    SUM(mll.credit) AS credit,
                    SUM(mll.balance) AS balance
                FROM mgmt_ledger_line mll
                WHERE mll.company_id IN %(company_ids)s
                  AND mll.date <= %(date_to)s
                  AND {partner_clause}
                GROUP BY mll.partner_id
            """

            self._cr.execute(query, params)
            for result in self._cr.dictfetchall():
                pid = result['partner_id']
                if pid in init_balance_by_col_group:
                    init_balance_by_col_group[pid][column_group_key] = result

        return init_balance_by_col_group

    def _get_aml_values(self, report, options, partner_ids, offset=0, limit=None):
        """Get individual mgmt.ledger.line records for given partners."""
        rslt = {partner_id: [] for partner_id in partner_ids}
        company_ids = tuple(report.get_report_company_ids(options))

        for column_group_key, column_group_options in report._split_options_per_column_group(options).items():
            date_from = column_group_options['date']['date_from']
            date_to = column_group_options['date']['date_to']

            # Build partner clause
            partner_ids_wo_none = [pid for pid in partner_ids if pid is not None]
            clauses = []
            params = {
                'column_group_key': column_group_key,
                'company_ids': company_ids,
                'date_from': date_from,
                'date_to': date_to,
            }

            if partner_ids_wo_none:
                clauses.append('mll.partner_id IN %(partner_ids_list)s')
                params['partner_ids_list'] = tuple(partner_ids_wo_none)
            if None in partner_ids:
                clauses.append('mll.partner_id IS NULL')

            if not clauses:
                continue

            partner_clause = '(' + ' OR '.join(clauses) + ')'

            query = f"""
                SELECT
                    mll.id,
                    mll.date,
                    mll.label,
                    mll.partner_id,
                    mll.debit,
                    mll.credit,
                    mll.balance,
                    mll.origin_type,
                    mll.ref_amount,
                    ma.code AS mgmt_account_code,
                    %(column_group_key)s AS column_group_key
                FROM mgmt_ledger_line mll
                JOIN mgmt_account ma ON ma.id = mll.mgmt_account_id
                WHERE mll.company_id IN %(company_ids)s
                  AND mll.date >= %(date_from)s
                  AND mll.date <= %(date_to)s
                  AND {partner_clause}
                ORDER BY mll.date, mll.id
            """

            if offset:
                query += ' OFFSET %(offset)s'
                params['offset'] = offset
            if limit:
                query += ' LIMIT %(limit)s'
                params['limit'] = limit

            self._cr.execute(query, params)
            for row in self._cr.dictfetchall():
                pid = row['partner_id']
                if pid in rslt:
                    rslt[pid].append(row)

        return rslt

    # ---- Line builders ----

    def _get_report_line_partners(self, report, options, partner, partner_values):
        company_currency = self.env.company.currency_id

        unfoldable = False
        column_values = []
        for column in options['columns']:
            col_expr_label = column['expression_label']
            value = partner_values[column['column_group_key']].get(col_expr_label)
            unfoldable = unfoldable or (col_expr_label in ('debit', 'credit') and value and not company_currency.is_zero(value))
            column_values.append(report._build_column_dict(value, column, options=options))

        if partner:
            line_id = report._get_generic_line_id('res.partner', partner.id)
        else:
            line_id = report._get_generic_line_id('res.partner', None, markup='no_partner')

        return {
            'id': line_id,
            'name': partner.name[:128] if partner else self._get_no_partner_line_label(),
            'columns': column_values,
            'level': 1,
            'unfoldable': unfoldable,
            'unfolded': line_id in options.get('unfolded_lines', []) or options.get('unfold_all'),
            'expand_function': '_report_expand_unfoldable_line_mgmt_partner_ledger',
        }

    def _get_no_partner_line_label(self):
        return _('Unknown Partner')

    def _get_report_line_total(self, report, options, totals_by_column_group):
        column_values = []
        for column in options['columns']:
            col_value = totals_by_column_group[column['column_group_key']].get(column['expression_label'])
            column_values.append(report._build_column_dict(col_value, column, options=options))

        return {
            'id': report._get_generic_line_id(None, None, markup='total'),
            'name': _('Total'),
            'level': 1,
            'columns': column_values,
        }

    def _get_report_line_move_line(self, report, options, result, partner_line_id, init_bal_by_col_group):
        """Build a detail line dict for a single mgmt.ledger.line record."""
        # Map origin_type codes to display labels
        origin_labels = {
            'source': _('Source'),
            'mapping': _('Classification'),
            'allocation': _('Allocation'),
            'timing': _('Timing'),
            'manual': _('Journal Entry'),
        }

        columns = []
        for column in options['columns']:
            col_expr_label = column['expression_label']

            if column['column_group_key'] != result['column_group_key']:
                columns.append(report._build_column_dict(None, None))
                continue

            if col_expr_label == 'date':
                col_value = result.get('date')
            elif col_expr_label == 'mgmt_account_code':
                col_value = result.get('mgmt_account_code', '')
            elif col_expr_label == 'label':
                col_value = result.get('label', '')
            elif col_expr_label == 'origin_type':
                col_value = origin_labels.get(result.get('origin_type', ''), '')
            elif col_expr_label == 'ref_amount':
                col_value = result.get('ref_amount') or 0.0
            elif col_expr_label == 'balance':
                col_value = result['balance'] + init_bal_by_col_group.get(column['column_group_key'], 0.0)
            else:
                col_value = result.get(col_expr_label)

            if col_value is None:
                columns.append(report._build_column_dict(None, None))
            else:
                columns.append(report._build_column_dict(col_value, column, options=options))

        return {
            'id': report._get_generic_line_id('mgmt.ledger.line', result['id'], parent_line_id=partner_line_id),
            'parent_id': partner_line_id,
            'name': result.get('label', '') or '',
            'columns': columns,
            'level': 3,
        }

    # ---- Unfold callback ----

    def _report_expand_unfoldable_line_mgmt_partner_ledger(self, line_dict_id, groupby, options, progress, offset, unfold_all_batch_data=None):
        report = self.env['account.report'].browse(options['report_id'])
        markup, model, record_id = report._parse_line_id(line_dict_id)[-1]

        lines = []

        # Initial balance
        if offset == 0:
            init_balance_by_col_group = self._get_initial_balance_values(report, [record_id], options)[record_id]
            initial_balance_line = report._get_partner_and_general_ledger_initial_balance_line(
                options, line_dict_id, init_balance_by_col_group
            )
            if initial_balance_line:
                lines.append(initial_balance_line)
                progress = {
                    column['column_group_key']: line_col.get('no_format', 0)
                    for column, line_col in zip(options['columns'], initial_balance_line['columns'])
                    if column['expression_label'] == 'balance'
                }

        # Load detail lines
        limit_to_load = report.load_more_limit + 1 if report.load_more_limit and options['export_mode'] != 'print' else None
        aml_results = self._get_aml_values(report, options, [record_id], offset=offset, limit=limit_to_load)[record_id]

        has_more = False
        treated_results_count = 0
        next_progress = progress or {}
        for result in aml_results:
            if options['export_mode'] != 'print' and report.load_more_limit and treated_results_count == report.load_more_limit:
                has_more = True
                break

            # Build running balance from progress
            init_bal = {
                col_group_key: next_progress.get(col_group_key, 0.0)
                for col_group_key in options['column_groups']
            }
            new_line = self._get_report_line_move_line(report, options, result, line_dict_id, init_bal)
            lines.append(new_line)

            # Update progress with running balance
            next_progress = {
                column['column_group_key']: line_col.get('no_format', 0)
                for column, line_col in zip(options['columns'], new_line['columns'])
                if column['expression_label'] == 'balance'
            }
            treated_results_count += 1

        return {
            'lines': lines,
            'offset_increment': treated_results_count,
            'has_more': has_more,
            'progress': next_progress,
        }
