# -*- coding: utf-8 -*-

from odoo import fields, models


class JitoLedgerStatutoryEntryView(models.Model):
    """Phase 4 extends the FAAP-projection entry view with adjustment-
    count fields + click-through actions, so the user can navigate
    from a stock entry to the Bridgings / Restatements / Regroupings
    that were generated from its lines.

    Lives in jito_ledger_adjustments because it references the three
    Phase 4 wizard models. The base SQL-view model is in jito_ledger_nl.
    """

    _inherit = 'jito.ledger.statutory.entry.view'

    bridging_count = fields.Integer(
        string='Bridgings',
        compute='_compute_adjustment_counts',
        help="Number of jito.mgt.bridging records whose source lines "
             "include any line of this statutory entry.",
    )
    restatement_count = fields.Integer(
        string='Restatements',
        compute='_compute_adjustment_counts',
    )
    regrouping_count = fields.Integer(
        string='Regroupings',
        compute='_compute_adjustment_counts',
    )

    def _compute_adjustment_counts(self):
        Bridging = self.env['jito.mgt.bridging']
        Restate = self.env['jito.mgt.restatement']
        Regroup = self.env['jito.mgt.regrouping']
        for entry in self:
            line_ids = entry.move_id.line_ids.ids if entry.move_id else []
            if not line_ids:
                entry.bridging_count = 0
                entry.restatement_count = 0
                entry.regrouping_count = 0
                continue
            entry.bridging_count = Bridging.search_count([
                ('source_line_ids', 'in', line_ids),
            ])
            entry.restatement_count = Restate.search_count([
                ('source_line_ids', 'in', line_ids),
            ])
            entry.regrouping_count = Regroup.search_count([
                ('source_line_ids', 'in', line_ids),
            ])

    def _action_view_adjustments(self, model, name):
        self.ensure_one()
        line_ids = self.move_id.line_ids.ids if self.move_id else []
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'tree,form',
            'domain': [('source_line_ids', 'in', line_ids)],
            'context': {'create': False},
        }

    def action_view_bridgings(self):
        return self._action_view_adjustments('jito.mgt.bridging', 'Bridgings')

    def action_view_restatements(self):
        return self._action_view_adjustments('jito.mgt.restatement', 'Restatements')

    def action_view_regroupings(self):
        return self._action_view_adjustments('jito.mgt.regrouping', 'Regroupings')
