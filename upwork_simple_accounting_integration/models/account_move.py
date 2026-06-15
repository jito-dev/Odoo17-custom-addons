from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    usa_reclassified = fields.Boolean(
        string='Upwork Expense Reclassified',
        default=False,
        copy=False,
        help='Set when this Upwork vendor bill has been moved to the dedicated '
             'Upwork expense account (600500 / 600510), or already used it. '
             'Used to keep the one-shot reclassification action idempotent.',
    )
    # ── Upwork analytic tagging ────────────────────────────────────────────────
    # Every move the Upwork module produces (invoices, bills, credit notes, the
    # wallet bank lines, reconciliation write-offs, the reclassification JE) touches
    # the dedicated Upwork chart. We stamp the "Upwork" analytic account on ALL of
    # their lines so Accounting reports filtered by Analytic = Upwork reconstruct
    # the complete, exclusive Upwork ledger (P&L *and* Balance Sheet).

    def _post(self, soft=True):
        # Tag while still draft so super()._post() generates the analytic lines
        # exactly once (the analytic_distribution inverse only fires for posted
        # lines, so no duplicate analytic lines are created here).
        self._usa_apply_analytics()
        return super()._post(soft=soft)

    def _usa_apply_analytics(self):
        """Stamp analytic accounts on every line of each Upwork move:
          - the baseline **Data Source = Upwork** account, plus
          - any **rule-based** plan (e.g. Department) whose rule matches the move's
            source transaction (usa.analytic.rule).
        Idempotent and re-runnable (used by _post and by "Re-apply Analytic Tags");
        cheap early-out when the feature isn't configured."""
        if not self:
            return
        settings = self.env['usa.settings'].sudo().search([], limit=1)
        ds_account = settings.upwork_analytic_account_id if settings else False
        if not ds_account:
            return
        account_ids = settings._upwork_account_ids()
        if not account_ids:
            return

        # Only Upwork moves matter — skip the rest cheaply (this hook fires on every
        # posting in the system).
        relevant = self.filtered(
            lambda m: any(line.account_id.id in account_ids for line in m.line_ids))
        if not relevant:
            return

        rules = self.env['usa.analytic.rule'].sudo().search(
            [('active', '=', True)], order='sequence, id')

        # All analytic accounts of the plans this engine manages (Data Source +
        # every plan referenced by a rule) — used to clear stale tags on re-apply.
        managed_plans = ds_account.plan_id | rules.mapped('plan_id')
        managed_account_ids = set(self.env['account.analytic.account'].sudo().search(
            [('plan_id', 'in', managed_plans.ids)]).ids)

        # Bulk-resolve move → source transaction in ONE query (not per move) so this
        # scales to thousands of moves without a search-per-move.
        tx_by_move = relevant._usa_resolve_transactions() if rules else {}

        for move in relevant:
            move._usa_apply_analytics_to_move(
                account_ids, ds_account, rules, managed_account_ids,
                tx_by_move.get(move.id))

    def _usa_resolve_transactions(self):
        """Map each move.id in this recordset to its usa.transaction in one search."""
        if not self:
            return {}
        move_ids = set(self.ids)
        txs = self.env['usa.transaction'].sudo().search([
            '|', '|', '|', '|', '|',
            ('vendor_bill_id', 'in', self.ids),
            ('customer_invoice_id', 'in', self.ids),
            ('customer_refund_id', 'in', self.ids),
            ('vendor_refund_id', 'in', self.ids),
            ('statement_line_id.move_id', 'in', self.ids),
            ('move_id', 'in', self.ids),
        ])
        result = {}
        for tx in txs:
            for mid in (
                tx.vendor_bill_id.id, tx.customer_invoice_id.id,
                tx.customer_refund_id.id, tx.vendor_refund_id.id,
                tx.move_id.id, tx.statement_line_id.move_id.id,
            ):
                if mid in move_ids and mid not in result:
                    result[mid] = tx
        return result

    def _usa_apply_analytics_to_move(self, account_ids, ds_account, rules,
                                     managed_account_ids, tx=None):
        """Resolve the target analytic accounts for this move (Data Source baseline +
        first matching rule per plan) and write them onto every line, clearing any
        prior managed-plan tags so re-running after a rule change re-tags cleanly."""
        self.ensure_one()
        if not any(line.account_id.id in account_ids for line in self.line_ids):
            return

        # Resolve one analytic account per managed plan.
        resolved = {ds_account.plan_id.id: ds_account.id}
        if rules and tx:
            for rule in rules:
                pid = rule.plan_id.id
                if pid in resolved:
                    continue
                if rule._matches(tx):
                    resolved[pid] = rule.analytic_account_id.id
        targets = set(resolved.values())

        for line in self.line_ids:
            dist = dict(line.analytic_distribution or {})
            new_dist = {}
            for raw_key, val in dist.items():
                ids_in_key = [int(p) for p in str(raw_key).split(',') if p.isdigit()]
                # Drop entries from plans we manage; keep everything else (other
                # plans, manual analytic, etc.).
                if any(i in managed_account_ids for i in ids_in_key):
                    continue
                new_dist[raw_key] = val
            for acc_id in targets:
                new_dist[str(acc_id)] = 100.0
            if new_dist != dist:
                line.analytic_distribution = new_dist

    def _usa_linked_transaction(self):
        """The usa.transaction this move was created from (invoice / bill / credit
        note / wallet statement line), or an empty recordset."""
        self.ensure_one()
        return self.env['usa.transaction'].sudo().search([
            '|', '|', '|', '|', '|',
            ('vendor_bill_id', '=', self.id),
            ('customer_invoice_id', '=', self.id),
            ('customer_refund_id', '=', self.id),
            ('vendor_refund_id', '=', self.id),
            ('statement_line_id.move_id', '=', self.id),
            ('move_id', '=', self.id),
        ], limit=1)
