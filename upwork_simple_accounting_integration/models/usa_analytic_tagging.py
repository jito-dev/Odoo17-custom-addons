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

        # Seed the rule-engine dimension: a "Department" plan + starter accounts,
        # so the user can pick them when configuring Analytic Rules. (No rules are
        # seeded — those are configured by the user.)
        dept_plan = Plan.search([('name', '=', 'Department')], limit=1) \
            or Plan.create({'name': 'Department'})
        for dept_name in ('Software Development', 'UX/UI Design'):
            exists = Account.search([
                ('plan_id', '=', dept_plan.id),
                ('name', '=', dept_name),
                ('company_id', 'in', (False, company.id)),
            ], limit=1)
            if not exists:
                Account.create({
                    'name': dept_name,
                    'plan_id': dept_plan.id,
                    'company_id': company.id,
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
        """One-shot "Re-apply Analytic Tags": re-run the full analytic processor on
        every existing move that touches an Upwork account — applying the Data Source
        baseline AND all configured rule-based plans (e.g. Department). Idempotent;
        re-running after editing rules re-tags cleanly (stale managed-plan tags are
        cleared). analytic_distribution is editable on posted entries, so analytic
        lines are regenerated without resetting/reposting."""
        self.ensure_one()
        if not (self.upwork_analytic_account_id or self._ensure_upwork_analytic()):
            return self._usa_notify_analytic(_(
                'Analytic not configured — run "Setup Upwork Accounting" first.'),
                'warning')
        account_ids = self._upwork_account_ids()
        if not account_ids:
            return self._usa_notify_analytic(_(
                'No Upwork accounts found — run "Setup Upwork Accounting" first.'),
                'warning')

        move_ids = self.env['account.move'].sudo().search(
            [('line_ids.account_id', 'in', list(account_ids))]).ids
        if not move_ids:
            return self._usa_notify_analytic(_('No Upwork moves found to tag.'), 'warning')

        # Re-tagging thousands of moves is too heavy for one HTTP request (worker
        # timeout), so run it in the background via queue_job, in batches. Each batch
        # runs in its own job/transaction. (Requires the queue_job runner — production.)
        batch_size = 200
        batches = [move_ids[i:i + batch_size] for i in range(0, len(move_ids), batch_size)]
        for batch in batches:
            self.sudo().with_delay(
                description=_('Re-apply Upwork analytic tags (%d moves)') % len(batch),
            )._usa_reapply_analytics_batch(batch)

        _logger.info(
            'Upwork analytic re-apply: queued %d job(s) for %d move(s).',
            len(batches), len(move_ids))
        return self._usa_notify_analytic(_(
            'Queued %(b)d background job(s) to re-apply analytic tags to %(m)d move(s) '
            '(Data Source + rules). Track progress under Settings → Technical → Queue Jobs, '
            'then filter Accounting reports by Analytic.',
            b=len(batches), m=len(move_ids)), 'success')

    def _usa_reapply_analytics_batch(self, move_ids):
        """queue_job worker: re-apply analytic tags to one batch of moves."""
        moves = self.env['account.move'].sudo().browse(move_ids).exists()
        moves._usa_apply_analytics()

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
