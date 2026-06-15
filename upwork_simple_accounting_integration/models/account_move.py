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
        self._usa_tag_upwork_analytic_on_post()
        return super()._post(soft=soft)

    def _usa_tag_upwork_analytic_on_post(self):
        """Stamp the Upwork analytic on every line of each move that touches an
        Upwork account. Cheap early-out when the feature isn't configured."""
        if not self:
            return
        settings = self.env['usa.settings'].sudo().search([], limit=1)
        analytic = settings.upwork_analytic_account_id if settings else False
        if not analytic:
            return
        account_ids = settings._upwork_account_ids()
        if not account_ids:
            return
        for move in self:
            move._usa_tag_upwork_analytic_lines(analytic, account_ids)

    def _usa_tag_upwork_analytic_lines(self, analytic, account_ids):
        """If this move touches an Upwork account, merge `analytic` into every
        line's analytic_distribution that doesn't already carry an account from the
        same plan. Idempotent. Returns the number of lines updated."""
        self.ensure_one()
        if not any(line.account_id.id in account_ids for line in self.line_ids):
            return 0
        plan_account_ids = set(analytic.plan_id.account_ids.ids)
        key = str(analytic.id)
        updated = 0
        for line in self.line_ids:
            dist = dict(line.analytic_distribution or {})
            present = set()
            for raw_key in dist:
                for part in str(raw_key).split(','):
                    if part.isdigit():
                        present.add(int(part))
            # Skip if this line already carries an account from the Data Source plan.
            if present & plan_account_ids:
                continue
            dist[key] = 100.0
            line.analytic_distribution = dist
            updated += 1
        return updated
