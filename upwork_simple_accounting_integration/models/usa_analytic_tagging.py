import logging

from odoo import _, fields, models

from .usa_settings import UPWORK_ACCOUNT_SET

_logger = logging.getLogger(__name__)


class UsaSettingsAnalytic(models.Model):
    """Upwork reporting ring-fence via an analytic dimension.

    A dedicated analytic plan **"Data Source"** with an analytic account
    **"Upwork"** is stamped on every line of every Upwork move (see
    `account.move._post`). Filtering any Accounting report by Analytic =
    Upwork then shows the complete, exclusive Upwork ledger.
    """

    _inherit = 'usa.settings'

    upwork_analytic_plan_id = fields.Many2one(
        'account.analytic.plan', string='Upwork Analytic Plan', readonly=True,
        help='Analytic plan ("Data Source") grouping the Upwork analytic account.',
    )
    upwork_analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Upwork Analytic Account', readonly=True,
        help='Analytic account ("Upwork") stamped on every Upwork move line so '
             'Accounting reports filtered by it show the complete Upwork ledger.',
    )

    # ── Setup ──────────────────────────────────────────────────────────────────

    def _ensure_upwork_analytic(self):
        """Idempotently get-or-create the 'Data Source' plan + 'Upwork' analytic
        account, and store them on the settings."""
        self.ensure_one()
        company = self.journal_id.company_id or self.env.company
        Plan = self.env['account.analytic.plan'].sudo()
        Account = self.env['account.analytic.account'].sudo()

        plan = self.upwork_analytic_plan_id \
            or Plan.search([('name', '=', 'Data Source')], limit=1) \
            or Plan.create({'name': 'Data Source'})

        account = self.upwork_analytic_account_id
        if not account:
            account = Account.search([
                ('plan_id', '=', plan.id),
                ('name', '=', 'Upwork'),
                ('company_id', 'in', (False, company.id)),
            ], limit=1)
        if not account:
            account = Account.create({
                'name': 'Upwork',
                'plan_id': plan.id,
                'company_id': company.id,
            })

        self.write({
            'upwork_analytic_plan_id': plan.id,
            'upwork_analytic_account_id': account.id,
        })
        return account

    def _upwork_account_ids(self):
        """Set of account.account ids in the dedicated Upwork chart for this
        settings' company — used to recognise an 'Upwork move'."""
        self.ensure_one()
        company = self.journal_id.company_id or self.env.company
        codes = [code for code, _name, _atype in UPWORK_ACCOUNT_SET]
        accounts = self.env['account.account'].sudo().search([
            ('company_id', '=', company.id),
            ('code', 'in', codes),
        ])
        return set(accounts.ids)

    # ── Backfill ───────────────────────────────────────────────────────────────

    def action_backfill_upwork_analytic(self):
        """One-shot: stamp the Upwork analytic account on every line of every
        existing move that touches an Upwork account (idempotent — already-tagged
        lines are skipped). analytic_distribution is editable on posted entries,
        so the analytic lines are regenerated without resetting/reposting."""
        self.ensure_one()
        analytic = self.upwork_analytic_account_id or self._ensure_upwork_analytic()
        account_ids = self._upwork_account_ids()
        if not account_ids:
            return self._usa_notify_analytic(_(
                'No Upwork accounts found — run "Setup Upwork Accounting" first.'),
                'warning')

        Move = self.env['account.move'].sudo()
        moves = Move.search([('line_ids.account_id', 'in', list(account_ids))])

        tagged_moves = 0
        tagged_lines = 0
        for move in moves:
            n = move._usa_tag_upwork_analytic_lines(analytic, account_ids)
            if n:
                tagged_moves += 1
                tagged_lines += n

        _logger.info(
            'Upwork analytic backfill: %d move(s), %d line(s) tagged.',
            tagged_moves, tagged_lines,
        )
        return self._usa_notify_analytic(_(
            '%(m)d move(s) tagged with the Upwork analytic (%(l)d line(s)). '
            'Filter Accounting reports by Analytic = Upwork.',
            m=tagged_moves, l=tagged_lines), 'success')

    def _usa_notify_analytic(self, message, ntype):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Upwork Analytic Tagging'),
                'message': message,
                'type': ntype,
                'sticky': ntype != 'success',
            },
        }
