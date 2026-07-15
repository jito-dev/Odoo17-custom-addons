# -*- coding: utf-8 -*-

"""Sync ML analytic mirrors from stock analytic (17.0.13.0.0).

Twin of ``jito.ledger.faap.sync.wizard`` (which mirrors stock
``account.account`` into ``jito.ledger.account``), but for the analytic
dimension: it mirrors stock ``account.analytic.plan`` /
``account.analytic.account`` into ``jito.ledger.analytic.plan`` /
``jito.ledger.analytic.account`` with a soft pointer back to stock
(``statutory_plan_id`` / ``statutory_analytic_account_id``).

Design notes:
  * ONE set of ML analytic accounts. A mirror carries a stock pointer;
    a management-only account does not. ``scope`` derives from the pointer.
  * Mirrored accounts keep the SAME ``code`` as their stock source, so the
    reporting join key ``base_code`` (which defaults to ``code``) lines up.
  * Plans are mirrored 1:1 preserving hierarchy. Stock analytic *accounts*
    are flat (no ``parent_id``), so account mirroring needs no topo-sort.
  * Idempotent: get-or-create is keyed by the stock pointer, so re-running
    with ``update_existing=False`` is a safe no-op.
  * Stock analytic tables are never written to (soft pointers only).

Admin-only per the security matrix (see ir.model.access.csv).
"""

import logging

from odoo import fields, models, _

_logger = logging.getLogger(__name__)


class JitoLedgerAnalyticSyncWizard(models.TransientModel):
    _name = 'jito.ledger.analytic.sync.wizard'
    _description = 'Sync Analytic Mirrors from Stock Analytic'

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    update_existing = fields.Boolean(
        string='Update existing mirrors',
        default=False,
        help="When set, an existing mirror is refreshed (name, hierarchy, "
             "partner, pointer). A manually-tuned base_code is preserved. "
             "Otherwise existing mirrors are left untouched.",
    )
    skip_archived = fields.Boolean(
        string='Skip archived statutory accounts',
        default=True,
        help="Stock analytic accounts marked archived are skipped. "
             "(Stock analytic plans have no archive state.) Recommended.",
    )
    sync_accounts = fields.Boolean(
        string='Also mirror analytic accounts',
        default=True,
        help="Plans are always mirrored. Untick to mirror plan structure "
             "only, without the individual analytic accounts.",
    )

    # ------------------------------------------------------------------ #
    def action_sync(self):
        """Run the bulk sync. Returns a notification with the result."""
        self.ensure_one()
        company_id = self.company_id.id

        plan_stats, plan_map = self._sync_plans(company_id)
        acc_stats = (
            self._sync_accounts(company_id, plan_map)
            if self.sync_accounts else {}
        )

        return self._notify(plan_stats, acc_stats)

    # ---- Pass A: plans (hierarchy-safe) ------------------------------- #
    def _sync_plans(self, company_id):
        Plan = self.env['jito.ledger.analytic.plan']
        StockPlan = self.env['account.analytic.plan']

        # Stock analytic plans are GLOBAL in Odoo 17 — no company_id and no
        # active field — so we mirror every plan into the wizard's company.
        # parent_path sort => parents before children (stock _parent_store
        # forbids cycles, so this ordering is total and safe).
        stock_plans = StockPlan.search([], order='parent_path')

        created = updated = skipped = 0
        plan_map = {}  # stock_plan.id -> ML plan record
        for sp in stock_plans:
            ml_plan = Plan.with_context(active_test=False).search([
                ('statutory_plan_id', '=', sp.id),
                ('company_id', '=', company_id),
            ], limit=1)
            parent_ml = plan_map.get(sp.parent_id.id) if sp.parent_id else False
            if ml_plan:
                if self.update_existing:
                    ml_plan.write({
                        'name': sp.name,
                        'description': sp.description,
                        'sequence': sp.sequence,
                        'default_applicability': sp.default_applicability,
                        'parent_id': parent_ml.id if parent_ml else False,
                    })
                    updated += 1
                else:
                    skipped += 1
            else:
                ml_plan = Plan.create({
                    'name': sp.name,
                    'description': sp.description,
                    'sequence': sp.sequence,
                    'default_applicability': sp.default_applicability,
                    'parent_id': parent_ml.id if parent_ml else False,
                    'company_id': company_id,
                    'statutory_plan_id': sp.id,
                })
                created += 1
            plan_map[sp.id] = ml_plan

        return {
            'considered': len(stock_plans),
            'created': created, 'updated': updated, 'skipped': skipped,
        }, plan_map

    # ---- Pass B: accounts (flat) -------------------------------------- #
    def _sync_accounts(self, company_id, plan_map):
        Account = self.env['jito.ledger.analytic.account']
        Plan = self.env['jito.ledger.analytic.plan']
        StockAccount = self.env['account.analytic.account']
        if not self.skip_archived:
            StockAccount = StockAccount.with_context(active_test=False)

        stock_accounts = StockAccount.search(
            [('company_id', 'in', [company_id, False])]
        )

        created = updated = skipped = 0
        skipped_no_plan = skipped_collision = 0
        for sa in stock_accounts:
            ml_plan = plan_map.get(sa.plan_id.id)
            if not ml_plan:
                ml_plan = Plan.with_context(active_test=False).search([
                    ('statutory_plan_id', '=', sa.plan_id.id),
                    ('company_id', '=', company_id),
                ], limit=1)
            if not ml_plan:
                skipped_no_plan += 1
                continue

            ml_acc = Account.with_context(active_test=False).search([
                ('statutory_analytic_account_id', '=', sa.id),
                ('company_id', '=', company_id),
            ], limit=1)
            if ml_acc:
                if self.update_existing:
                    ml_acc.write({
                        'name': sa.name,
                        'partner_id': sa.partner_id.id or False,
                        'plan_id': ml_plan.id,
                        'statutory_analytic_account_id': sa.id,
                    })
                    updated += 1
                else:
                    skipped += 1
                continue

            # A non-mirror account already occupying this (code, plan): the
            # unique(code, plan, company) constraint would abort the txn, so
            # skip-and-report instead. (Empty codes never collide — NULL is
            # distinct in Postgres.)
            if sa.code:
                clash = Account.with_context(active_test=False).search([
                    ('code', '=', sa.code),
                    ('plan_id', '=', ml_plan.id),
                    ('company_id', '=', company_id),
                ], limit=1)
                if clash:
                    skipped_collision += 1
                    _logger.warning(
                        "Analytic sync: stock account %s (code=%r) collides "
                        "with existing management account %s in plan %s — "
                        "skipped.",
                        sa.display_name, sa.code, clash.display_name,
                        ml_plan.display_name,
                    )
                    continue

            Account.create({
                'name': sa.name,
                'code': sa.code or False,
                'plan_id': ml_plan.id,
                'partner_id': sa.partner_id.id or False,
                'company_id': company_id,
                'statutory_analytic_account_id': sa.id,
            })
            created += 1

        return {
            'considered': len(stock_accounts),
            'created': created, 'updated': updated, 'skipped': skipped,
            'skipped_no_plan': skipped_no_plan,
            'skipped_collision': skipped_collision,
        }

    # ---- notification ------------------------------------------------- #
    def _notify(self, plan_stats, acc_stats):
        parts = [
            _("Plans — considered %d, created %d, updated %d, skipped %d.",
              plan_stats['considered'], plan_stats['created'],
              plan_stats['updated'], plan_stats['skipped']),
        ]
        if acc_stats:
            parts.append(_(
                "Accounts — considered %d, created %d, updated %d, skipped %d.",
                acc_stats['considered'], acc_stats['created'],
                acc_stats['updated'], acc_stats['skipped'],
            ))
            if acc_stats['skipped_no_plan']:
                parts.append(_("Accounts skipped (plan not mirrored): %d")
                             % acc_stats['skipped_no_plan'])
            if acc_stats['skipped_collision']:
                parts.append(_("Accounts skipped (code collision): %d")
                             % acc_stats['skipped_collision'])
        message = "\n".join(parts)
        _logger.info("Analytic sync complete: %s", message.replace("\n", " | "))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Analytic Sync'),
                'message': message,
                'type': 'success',
                'sticky': True,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
