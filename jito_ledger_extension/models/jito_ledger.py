# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class JitoLedger(models.Model):
    """Extension Ledger UX additions.

    Per HLD Decision #4 + Decision #7, extension entries live in
    jito.ledger.move with entry_type='ext_adjustment' (no new tables);
    combined-view reporting is on-the-fly (no materialised view). This
    inheritance just adds:

      * Two stat buttons on the kind=extension form (Adjustments count,
        Base Entries count).
      * A header action to create a new ext_adjustment move with the
        ledger and entry_type pre-filled.

    All controls return zero / no-op for non-extension ledgers.
    """

    _inherit = 'jito.ledger'

    extension_adjustment_count = fields.Integer(
        compute='_compute_extension_adjustment_count',
        string='Adjustments',
        help="Count of ext_adjustment moves on this extension ledger.",
    )
    base_ledger_entry_count = fields.Integer(
        compute='_compute_base_ledger_entry_count',
        string='Base Entries',
        help="Count of journal entries on the base ledger this extension "
             "sits on top of. Reads account.move when the base is the "
             "Leading Ledger; reads jito.ledger.move when the base is a "
             "Non-Leading Ledger.",
    )

    @api.depends('kind')
    def _compute_extension_adjustment_count(self):
        Move = self.env['jito.ledger.move']
        for ledger in self:
            if ledger.kind != 'extension':
                ledger.extension_adjustment_count = 0
                continue
            ledger.extension_adjustment_count = Move.search_count([
                ('ledger_id', '=', ledger.id),
                ('entry_type', '=', 'ext_adjustment'),
            ])

    @api.depends('kind', 'base_ledger_id')
    def _compute_base_ledger_entry_count(self):
        AccountMove = self.env['account.move']
        JitoMove = self.env['jito.ledger.move']
        for ledger in self:
            if ledger.kind != 'extension' or not ledger.base_ledger_id:
                ledger.base_ledger_entry_count = 0
                continue
            base = ledger.base_ledger_id
            if base.kind == 'leading':
                ledger.base_ledger_entry_count = AccountMove.search_count([
                    ('company_id', '=', ledger.company_id.id),
                ])
            else:
                ledger.base_ledger_entry_count = JitoMove.search_count([
                    ('ledger_id', '=', base.id),
                ])

    # ---- actions ---------------------------------------------------------

    def action_view_extension_adjustments(self):
        """Open a tree of ext_adjustment moves on this extension ledger."""
        self.ensure_one()
        if self.kind != 'extension':
            raise UserError(_(
                "Extension adjustments view is only available for extension ledgers."
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Extension Adjustments — %s', self.display_name),
            'res_model': 'jito.ledger.move',
            'view_mode': 'tree,form',
            'domain': [
                ('ledger_id', '=', self.id),
                ('entry_type', '=', 'ext_adjustment'),
            ],
            'context': {
                'default_ledger_id': self.id,
                'default_entry_type': 'ext_adjustment',
            },
        }

    def action_view_base_ledger_entries(self):
        """Open the base ledger's entries.

        Routes to stock account.move when the base is Leading; to
        jito.ledger.move when the base is Non-Leading.
        """
        self.ensure_one()
        if self.kind != 'extension' or not self.base_ledger_id:
            raise UserError(_(
                "Base ledger view is only available for extension ledgers "
                "with a configured base ledger."
            ))
        base = self.base_ledger_id
        if base.kind == 'leading':
            return {
                'type': 'ir.actions.act_window',
                'name': _('Leading Ledger Entries — %s', self.company_id.display_name),
                'res_model': 'account.move',
                'view_mode': 'tree,form',
                'domain': [('company_id', '=', self.company_id.id)],
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Base Ledger Entries — %s', base.display_name),
            'res_model': 'jito.ledger.move',
            'view_mode': 'tree,form',
            'domain': [('ledger_id', '=', base.id)],
            'context': {
                'default_ledger_id': base.id,
            },
        }

    def action_create_extension_adjustment(self):
        """Open a new jito.ledger.move form pre-filled for this extension."""
        self.ensure_one()
        if self.kind != 'extension':
            raise UserError(_(
                "Only extension ledgers can create extension adjustments."
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Extension Adjustment'),
            'res_model': 'jito.ledger.move',
            'view_mode': 'form',
            'context': {
                'default_ledger_id': self.id,
                'default_entry_type': 'ext_adjustment',
            },
        }
