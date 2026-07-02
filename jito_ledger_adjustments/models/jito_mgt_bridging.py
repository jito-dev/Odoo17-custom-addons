# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from ..snapshot_schemas import snapshot_account_move_line, CURRENT_VERSION
from ..preview import render_preview_table


class JitoMgtBridging(models.Model):
    """FR-07 + Spec §Bridging Lifecycle — Management Bridging.

    Two-stage management adjustment that re-interprets a statutory
    posting as **value in transit**. Stage 1 ('bridge') routes value
    from its default FAAP projection into a temporary CLR.* clearing
    balance. Stage 2 ('clearance') resolves the CLR balance into a
    final MGT.* destination when the downstream event arrives.

    State machine:
      draft → open (bridge move posted; CLR balance is open)
            → cleared (clearance move posted; CLR balance net 0)

    Per HLD §5.2, the canonical use case: customer wires cash → LL
    records bank receipt. Internally management knows the cash is
    earmarked for a DeFi USDC deposit. Stage 1 bridges to
    CLR.PENDING_DEFI_DEPOSIT. Days later, the on-chain deposit happens;
    stage 2 clears CLR.PENDING_DEFI_DEPOSIT into MGT.DEFI_TREASURY.
    """

    _name = 'jito.mgt.bridging'
    _description = 'Management Bridging (FR-07)'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        default=lambda self: _('New'),
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('open', 'Open (CLR Pending)'),
            ('cleared', 'Cleared'),
        ],
        string='Status',
        default='draft',
        required=True,
        copy=False,
        tracking=True,
    )

    journal_id = fields.Many2one(
        comodel_name='jito.ledger.journal',
        string='Journal',
        required=True,
        tracking=True,
        help="Destination ML journal (17.0.6.0.0 — switched to "
             "jito.ledger.journal). The journal's ledger_id implicitly "
             "selects which management ledger the bridge posts to.",
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='journal_id.company_id',
        store=True,
        readonly=True,
    )

    # Source: the LL move + lines being bridged. Picking the move first
    # lets the form filter source_line_ids to that move's lines.
    source_move_id = fields.Many2one(
        comodel_name='account.move',
        string='Statutory Source Move',
        tracking=True,
        domain="[('state', '=', 'posted'), ('company_id', '=', company_id)]",
        help="The LL move whose value is being bridged (e.g., a vendor "
             "bill, a bank statement line, a customer payment).",
    )
    source_line_ids = fields.Many2many(
        comodel_name='account.move.line',
        relation='jito_mgt_bridging_source_line_rel',
        column1='bridging_id',
        column2='line_id',
        string='Statutory Source Lines',
        required=True,
        # `=?` is "filter by source_move_id when set, otherwise no-op"
        # — fixes the previous always-true `if False` typo.
        domain="[('parent_state', '=', 'posted'), ('move_id', '=?', source_move_id)]",
    )

    clr_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Clearing Account',
        required=True,
        domain="[('company_id', '=', company_id), "
               "('semantic_family', '=', 'clr')]",
        help="CLR.* account where value parks until clearance. Must be "
             "in the same company as the journal.",
    )
    target_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Final Destination Account',
        required=True,
        domain="[('company_id', '=', company_id), "
               "('semantic_family', '=', 'mgt')]",
        help="MGT.* account that receives the value when CLR is cleared.",
    )

    bridge_date = fields.Date(
        string='Bridge Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    clearance_date = fields.Date(
        string='Clearance Date',
        tracking=True,
        help="Set automatically when the bridge is cleared.",
    )
    reason = fields.Char(
        string='Reason',
        tracking=True,
    )
    clearance_note = fields.Char(
        string='Clearance Reference',
        tracking=True,
        help="Free-text reference to the downstream event that triggered "
             "the clearance (e.g., 'on-chain tx 0xABCD…' or 'invoice "
             "INV/2026/0042'). Captured on action_clear.",
    )

    bridge_move_id = fields.Many2one(
        comodel_name='jito.ledger.move',
        string='Bridge Move',
        readonly=True,
        copy=False,
        help="The stage-1 jito.ledger.move(entry_type=mgt_bridge) — moves "
             "value from FAAP into CLR.",
    )
    clearance_move_id = fields.Many2one(
        comodel_name='jito.ledger.move',
        string='Clearance Move',
        readonly=True,
        copy=False,
        help="The stage-2 jito.ledger.move(entry_type=mgt_bridge) — moves "
             "value from CLR into the final MGT destination.",
    )

    # ---- preview (17.0.2.2.0) -------------------------------------------

    preview_html = fields.Html(
        string='Preview',
        compute='_compute_preview_html',
        sanitize=False,
        readonly=True,
        help="Live render of the would-be bridge move's lines based on "
             "the current source / clearing / target choices.",
    )

    @api.depends(
        'source_line_ids', 'clr_account_id', 'target_account_id',
        'state',
    )
    def _compute_preview_html(self):
        for record in self:
            record.preview_html = render_preview_table(
                record._build_preview_lines()
            )

    def _build_preview_lines(self):
        """Return the dict-list the preview renderer expects.

        Stage 1 (draft → open): FAAP-mirror reversal + CLR park.
        Stage 2 (open → cleared): CLR debit + MGT destination credit
        based on the bridge_move_id's CLR lines.
        """
        self.ensure_one()
        lines = []
        if self.state == 'draft':
            if not self.clr_account_id or not self.source_line_ids:
                return lines
            for src in self.source_line_ids:
                src_signed = src.amount_currency or (src.debit - src.credit)
                currency = src.currency_id or src.company_id.currency_id
                faap_account = self._faap_mirror_for(src.account_id)
                lines.append({
                    'account_code': (faap_account and faap_account.code)
                                    or ('FAAP-mirror-of-' + src.account_id.code),
                    'name': _("Bridge from %s") % src.account_id.code,
                    'currency_symbol': currency.symbol,
                    'debit':  -src_signed if src_signed < 0 else 0.0,
                    'credit':  src_signed if src_signed > 0 else 0.0,
                })
                lines.append({
                    'account_code': self.clr_account_id.code,
                    'name': _("Bridge into %s") % self.clr_account_id.code,
                    'currency_symbol': currency.symbol,
                    'debit':  src_signed if src_signed > 0 else 0.0,
                    'credit': -src_signed if src_signed < 0 else 0.0,
                })
        elif self.state == 'open':
            if not self.target_account_id or not self.bridge_move_id:
                return lines
            clr_lines = self.bridge_move_id.line_ids.filtered(
                lambda l: l.account_id == self.clr_account_id
            )
            for cl in clr_lines:
                amt = cl.amount_currency or 0.0
                sym = cl.currency_id.symbol if cl.currency_id else ''
                # Clearance reverses the bridge's CLR sign:
                #   bridge had +amt on CLR  → clearance posts -amt on CLR
                #   the reversed amount lands on the MGT target with
                #   the original sign.
                lines.append({
                    'account_code': self.clr_account_id.code,
                    'name': _("Clear %s") % self.clr_account_id.code,
                    'currency_symbol': sym,
                    'debit':  -amt if amt < 0 else 0.0,
                    'credit':  amt if amt > 0 else 0.0,
                })
                lines.append({
                    'account_code': self.target_account_id.code,
                    'name': _("Settle into %s") % self.target_account_id.code,
                    'currency_symbol': sym,
                    'debit':  amt if amt > 0 else 0.0,
                    'credit': -amt if amt < 0 else 0.0,
                })
        return lines

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'journal_id' in fields_list and not res.get('journal_id'):
            res['journal_id'] = (
                self._resolve_default_adjustments_journal() or False
            )
        return res

    @api.model
    def _resolve_default_adjustments_journal(self):
        """Pick the journal an adjustment wizard should pre-fill with.

        Priority:
          1. ``company.jito_default_adjustments_journal_id`` (admin-set).
          2. The first ``jito.ledger.journal`` whose ``ledger_id`` is
             the company's Non-Leading ledger — covers the common
             single-journal install where the admin didn't bother to
             configure the explicit default. (17.0.6.0.0 — direct read
             on the new model; was via the retired rel.)
          3. None.

        Shared by Bridge / Restate / Regroup so the journal field can
        stay hidden in the wizard form: by the time the user clicks
        Post, journal_id is reliably populated.
        """
        company = self.env.company
        journal = company.jito_default_adjustments_journal_id
        if journal:
            return journal.id
        nl = self.env['jito.ledger'].search([
            ('company_id', '=', company.id),
            ('kind', '=', 'non_leading'),
        ], limit=1)
        if nl:
            journal = self.env['jito.ledger.journal'].search([
                ('ledger_id', '=', nl.id),
            ], limit=1, order='sequence, id')
            if journal:
                return journal.id
        return None

    # ---- workflow --------------------------------------------------------

    def action_post(self):
        """Stage 1: generate the bridge move; transition draft → open."""
        for record in self:
            if record.state != 'draft':
                raise UserError(_(
                    "Only draft bridgings can be posted (record '%s' "
                    "is %s).", record.name, record.state,
                ))
            if not record.source_line_ids:
                raise UserError(_(
                    "Pick at least one statutory source line."
                ))
            if record.name == _('New'):
                seq = self.env['ir.sequence'].with_company(
                    record.company_id
                ).next_by_code('jito.mgt.bridging') or _('New')
                record.name = seq
            move = record._generate_bridge_move()
            record.write({
                'state': 'open',
                'bridge_move_id': move.id,
            })
            record.message_post(body=_(
                "Bridge posted as %s — CLR balance pending clearance.",
                move.display_name,
            ))
        return True

    def action_clear(self):
        """Stage 2: generate the clearance move; transition open → cleared.

        For v1 simplicity, clearance lines trace back to the bridge
        lines (kind='clears'). The downstream event is captured in
        clearance_note + chatter — extending to a typed
        source_payload_kind link is a v1.x improvement.
        """
        for record in self:
            if record.state != 'open':
                raise UserError(_(
                    "Only open bridgings can be cleared (record '%s' "
                    "is %s). Post the bridge first.",
                    record.name, record.state,
                ))
            move = record._generate_clearance_move()
            record.write({
                'state': 'cleared',
                'clearance_move_id': move.id,
                'clearance_date': fields.Date.context_today(self),
            })
            record.message_post(body=_(
                "Clearance posted as %s. CLR balance resolved into %s.",
                move.display_name, record.target_account_id.code,
            ))
        return True

    # ---- helpers ---------------------------------------------------------

    def _generate_bridge_move(self):
        """Create the stage-1 jito.ledger.move (FAAP → CLR)."""
        self.ensure_one()
        Move = self.env['jito.ledger.move']
        Line = self.env['jito.ledger.move.line']
        Trace = self.env['jito.ledger.trace']

        move = Move.create({
            'journal_id': self.journal_id.id,
            'date': self.bridge_date,
            'entry_type': 'mgt_bridge',
            'ref': _("Bridge %s") % self.name,
            'state': 'draft',
            'name': _('New'),
            'reason': self.reason,
            'source_move_id': self.source_move_id.id if self.source_move_id else False,
            'adjustment_origin': '%s,%s' % (self._name, self.id),
        })

        for src in self.source_line_ids:
            faap_account = self._faap_mirror_for(src.account_id)
            if not faap_account:
                raise UserError(_(
                    "No FAAP mirror found for stock account '%s'. Run "
                    "Configuration → FAAP Mirrors → Sync from Stock CoA "
                    "first.", src.account_id.code,
                ))
            src_signed = src.amount_currency or (src.debit - src.credit)
            currency = src.currency_id or src.company_id.currency_id

            # FAAP reversal (mirror of the LL effect)
            faap_line = Line.create({
                'move_id': move.id,
                'account_id': faap_account.id,
                'name': _("Bridge from %s") % src.account_id.code,
                'currency_id': currency.id,
                'amount_currency': -src_signed,
            })
            # Park value in CLR
            clr_line = Line.create({
                'move_id': move.id,
                'account_id': self.clr_account_id.id,
                'name': _("Bridge into %s") % self.clr_account_id.code,
                'currency_id': currency.id,
                'amount_currency': src_signed,
            })
            # Trace: bridge lines link back to source LL line
            for line in (faap_line, clr_line):
                Trace.create({
                    'parallel_line_id': line.id,
                    'source_line_id': src.id,
                    'source_snapshot': snapshot_account_move_line(src),
                    'snapshot_version': CURRENT_VERSION,
                    'kind': 'bridges',
                    'weight': 1.0,
                })

        move.action_post()
        return move

    def _generate_clearance_move(self):
        """Create the stage-2 jito.ledger.move (CLR → MGT).

        Mirrors the bridge lines: each CLR line on the bridge becomes a
        debit-of-CLR / credit-of-MGT pair on the clearance, balanced
        per currency.
        """
        self.ensure_one()
        Move = self.env['jito.ledger.move']
        Line = self.env['jito.ledger.move.line']
        Trace = self.env['jito.ledger.trace']

        bridge_clr_lines = self.bridge_move_id.line_ids.filtered(
            lambda l: l.account_id == self.clr_account_id
        )
        if not bridge_clr_lines:
            raise UserError(_(
                "Bridge move %s has no CLR lines to clear.",
                self.bridge_move_id.display_name,
            ))

        move = Move.create({
            'journal_id': self.journal_id.id,
            'date': fields.Date.context_today(self),
            'entry_type': 'mgt_bridge',
            'ref': _("Clearance %s") % self.name,
            'state': 'draft',
            'name': _('New'),
            'reason': _("Clearance: %s") % (self.clearance_note or self.reason or ''),
            'source_move_id': self.source_move_id.id if self.source_move_id else False,
            'adjustment_origin': '%s,%s' % (self._name, self.id),
        })

        for bridge_line in bridge_clr_lines:
            # Debit CLR (clears it), credit MGT target
            clr_clear = Line.create({
                'move_id': move.id,
                'account_id': self.clr_account_id.id,
                'name': _("Clear %s") % self.clr_account_id.code,
                'currency_id': bridge_line.currency_id.id,
                'amount_currency': -bridge_line.amount_currency,
            })
            mgt_line = Line.create({
                'move_id': move.id,
                'account_id': self.target_account_id.id,
                'name': _("Settle into %s") % self.target_account_id.code,
                'currency_id': bridge_line.currency_id.id,
                'amount_currency': bridge_line.amount_currency,
            })
            # Trace: clearance lines point at the bridge lines (kind='clears')
            for line in (clr_clear, mgt_line):
                Trace.create({
                    'parallel_line_id': line.id,
                    'source_line_id': False,
                    'source_payload_kind': 'manual_entry',
                    'source_payload': {
                        'memo': self.clearance_note or '',
                        'author': self.env.user.display_name,
                        'bridge_line_id': bridge_line.id,
                        'bridging_record_id': self.id,
                    },
                    'kind': 'clears',
                    'weight': 1.0,
                })

        move.action_post()
        return move

    def _faap_mirror_for(self, stock_account):
        return self.env['jito.ledger.account'].search([
            ('statutory_account_id', '=', stock_account.id),
            ('company_id', '=', self.company_id.id),
            ('semantic_family', '=', 'faap'),
        ], limit=1)
