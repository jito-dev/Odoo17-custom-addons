# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from ..snapshot_schemas import snapshot_account_move_line, CURRENT_VERSION
from ..preview import render_preview_table


class JitoMgtRestatement(models.Model):
    """FR-06 — Management Restatement.

    Re-categorize the management meaning of a specific LL line (or set
    of LL lines) into a target MGT account. Generates a single balanced
    `jito.ledger.move(entry_type='mgt_restate')` plus
    `jito.ledger.trace` rows linking each generated line to its
    contributing LL source line(s).

    Difference from manual ext_adjustment: traceability is
    **mandatory** — restatement always emits trace rows that an auditor
    can query ("show me which statutory line drove this management
    line"). Manual ext_adjustment is freeform.

    Form flow:
      1. Pick a journal in the destination ledger (the journal carries
         the ledger via jito.ledger.journal.rel).
      2. Pick one or more LL `account.move.line` records as sources.
      3. Pick the target MGT account (must be MGT.* family).
      4. Optionally override the FAAP source representation (defaults to
         the FAAP mirror of the LL source's account, if available).
      5. Confirm — generates the balanced move + trace rows.
    """

    _name = 'jito.mgt.restatement'
    _description = 'Management Restatement (FR-06)'
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
            ('posted', 'Posted'),
        ],
        string='Status',
        default='draft',
        required=True,
        copy=False,
        tracking=True,
    )

    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Journal',
        required=True,
        tracking=True,
        help="Destination journal — must be associated with a Non-Leading "
             "or Extension ledger via jito.ledger.journal.rel.",
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='journal_id.company_id',
        store=True,
        readonly=True,
    )

    source_line_ids = fields.Many2many(
        comodel_name='account.move.line',
        relation='jito_mgt_restatement_source_line_rel',
        column1='restatement_id',
        column2='line_id',
        string='Statutory Source Lines',
        required=True,
        help="The LL lines whose management meaning is being restated.",
    )
    target_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Target Management Account',
        required=True,
        domain="[('company_id', '=', company_id), "
               "('semantic_family', '=', 'mgt')]",
        help="The MGT.* account that captures the restated management "
             "meaning. Must be in the same company as the journal.",
    )

    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    reason = fields.Char(
        string='Reason',
        tracking=True,
        help="Why this restatement is being made. Captured for audit.",
    )

    generated_move_id = fields.Many2one(
        comodel_name='jito.ledger.move',
        string='Generated Move',
        readonly=True,
        copy=False,
        help="The jito.ledger.move(entry_type=mgt_restate) produced by "
             "this restatement on confirmation.",
    )

    # ---- preview (17.0.2.2.0) -------------------------------------------

    preview_html = fields.Html(
        string='Preview',
        compute='_compute_preview_html',
        sanitize=False,
        readonly=True,
    )

    @api.depends('source_line_ids', 'target_account_id')
    def _compute_preview_html(self):
        for record in self:
            record.preview_html = render_preview_table(
                record._build_preview_lines()
            )

    def _build_preview_lines(self):
        """For each source: FAAP-mirror reversal + MGT target line."""
        self.ensure_one()
        lines = []
        if not self.target_account_id or not self.source_line_ids:
            return lines
        for src in self.source_line_ids:
            src_signed = src.amount_currency or (src.debit - src.credit)
            currency = src.currency_id or src.company_id.currency_id
            faap_account = self._faap_mirror_for(src.account_id)
            lines.append({
                'account_code': (faap_account and faap_account.code)
                                or ('FAAP-mirror-of-' + src.account_id.code),
                'name': _("Restate from %s") % src.account_id.code,
                'currency_symbol': currency.symbol,
                'debit':  -src_signed if src_signed < 0 else 0.0,
                'credit':  src_signed if src_signed > 0 else 0.0,
            })
            lines.append({
                'account_code': self.target_account_id.code,
                'name': _("Restate to %s") % self.target_account_id.code,
                'currency_symbol': currency.symbol,
                'debit':  src_signed if src_signed > 0 else 0.0,
                'credit': -src_signed if src_signed < 0 else 0.0,
            })
        return lines

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'journal_id' in fields_list and not res.get('journal_id'):
            jid = self.env['jito.mgt.bridging']._resolve_default_adjustments_journal()
            if jid:
                res['journal_id'] = jid
        return res

    # ---- workflow --------------------------------------------------------

    def action_post(self):
        """Generate the balanced move + trace rows; transition to posted."""
        for record in self:
            if record.state != 'draft':
                raise UserError(_(
                    "Only draft restatements can be posted (record '%s' "
                    "is %s).", record.name, record.state,
                ))
            if not record.source_line_ids:
                raise UserError(_(
                    "Pick at least one statutory source line."
                ))
            if record.name == _('New'):
                seq = self.env['ir.sequence'].with_company(
                    record.company_id
                ).next_by_code('jito.mgt.restatement') or _('New')
                record.name = seq
            move = record._generate_move()
            record.write({
                'state': 'posted',
                'generated_move_id': move.id,
            })
            record.message_post(body=_(
                "Restatement posted as %s.", move.display_name,
            ))
        return True

    def _generate_move(self):
        """Create the jito.ledger.move with balanced lines + trace rows."""
        self.ensure_one()
        Move = self.env['jito.ledger.move']
        Line = self.env['jito.ledger.move.line']
        Trace = self.env['jito.ledger.trace']

        # Group source lines by (currency, side, FAAP mirror) so we can
        # emit one consolidated line per source-bucket.
        # For each source LL line: a pair of parallel-ledger lines, one
        # reversing the FAAP projection (debit FAAP if source was credit,
        # vice versa), one posting to the MGT target.
        single_source_move = (
            self.source_line_ids[0].move_id
            if self.source_line_ids
            and len(self.source_line_ids.mapped('move_id')) == 1
            else self.env['account.move']
        )
        move = Move.create({
            'journal_id': self.journal_id.id,
            'date': self.date,
            'entry_type': 'mgt_restate',
            'ref': _("Restatement %s") % self.name,
            'state': 'draft',
            'name': _('New'),
            'reason': self.reason,
            'source_move_id': single_source_move.id if single_source_move else False,
            'adjustment_origin': '%s,%s' % (self._name, self.id),
        })

        for src in self.source_line_ids:
            faap_account = self._faap_mirror_for(src.account_id)
            if not faap_account:
                raise UserError(_(
                    "No FAAP mirror found for stock account '%s'. Run "
                    "Configuration → Sync FAAP Mirrors first.",
                    src.account_id.code,
                ))
            # Source amount in tx currency (signed):
            #   stock account.move.line.amount_currency is signed
            #   (positive=debit-side, negative=credit-side), same as
            #   our jito.ledger.move.line model.
            src_signed = src.amount_currency or (src.debit - src.credit)
            currency = src.currency_id or src.company_id.currency_id

            # Reverse the FAAP projection: opposite sign on FAAP mirror
            faap_line = Line.create({
                'move_id': move.id,
                'account_id': faap_account.id,
                'name': _("Restate from %s") % src.account_id.code,
                'currency_id': currency.id,
                'amount_currency': -src_signed,
            })
            # Post to MGT target with original sign
            mgt_line = Line.create({
                'move_id': move.id,
                'account_id': self.target_account_id.id,
                'name': _("Restate to %s") % self.target_account_id.code,
                'currency_id': currency.id,
                'amount_currency': src_signed,
            })
            # Trace: each generated line traces back to the source
            for line in (faap_line, mgt_line):
                Trace.create({
                    'parallel_line_id': line.id,
                    'source_line_id': src.id,
                    'source_snapshot': snapshot_account_move_line(src),
                    'snapshot_version': CURRENT_VERSION,
                    'kind': 'derives_from',
                    'weight': 1.0,
                })

        # Post the move (runs balance constraint + period-lock check)
        move.action_post()
        return move

    def _faap_mirror_for(self, stock_account):
        """Look up the jito.ledger.account FAAP mirror for a stock
        account.account, scoped to this restatement's company.
        """
        return self.env['jito.ledger.account'].search([
            ('statutory_account_id', '=', stock_account.id),
            ('company_id', '=', self.company_id.id),
            ('semantic_family', '=', 'faap'),
        ], limit=1)
