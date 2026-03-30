from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ScaTransaction(models.Model):
    _name = 'sca.transaction'
    _description = 'Crypto Transaction'
    _order = 'tx_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    watched_address_id = fields.Many2one(
        'sca.watched_address',
        string='Watched Address',
        required=True,
        ondelete='cascade',
        index=True,
    )
    token_id = fields.Many2one(
        'sca.token',
        string='Token',
        ondelete='set null',
        index=True,
    )
    tx_hash = fields.Char(string='Transaction Hash', required=True, index=True, copy=False)
    log_index = fields.Integer(
        string='Log Index',
        default=-1,
        help='ERC-20 event log index within the transaction. -1 for native ETH transfers.',
    )
    block_number = fields.Integer(string='Block Number', readonly=True)
    tx_date = fields.Datetime(string='Date', readonly=True)
    from_address = fields.Char(string='From Address', readonly=True)
    to_address = fields.Char(string='To Address', readonly=True)
    raw_value = fields.Char(string='Raw Value', readonly=True, help='Value in smallest token unit (wei / base units)')
    token_symbol = fields.Char(string='Token', readonly=True)
    token_contract = fields.Char(string='Token Contract', readonly=True)
    gas_used = fields.Integer(string='Gas Used', readonly=True)

    etherscan_url = fields.Char(
        string='View on Etherscan',
        compute='_compute_etherscan_url',
        store=False,
    )
    description = fields.Text(string='Description', tracking=True)
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'sca_transaction_attachment_rel',
        'transaction_id',
        'attachment_id',
        string='File Attachments',
    )

    value_decimal = fields.Float(
        string='Amount',
        compute='_compute_value_decimal',
        digits=(30, 8),
        store=True,
    )
    direction = fields.Selection(
        [('in', 'Incoming'), ('out', 'Outgoing')],
        string='Direction',
        compute='_compute_direction',
        store=True,
    )
    from_display = fields.Char(
        string='From',
        compute='_compute_display_addresses',
        store=False,
    )
    to_display = fields.Char(
        string='To',
        compute='_compute_display_addresses',
        store=False,
    )

    # ── Accounting Injection ────────────────────────────────────────────────
    statement_line_id = fields.Many2one(
        'account.bank.statement.line',
        string='Statement Line',
        readonly=True, copy=False,
        ondelete='set null',
    )
    is_injected = fields.Boolean(
        string='Injected',
        compute='_compute_is_injected', store=True,
    )
    crypto_tx_ref = fields.Char(
        string='Crypto TX Ref',
        compute='_compute_crypto_tx_ref', store=True,
        index='trigram', readonly=True, copy=False,
    )

    _sql_constraints = [
        ('unique_tx_hash', 'UNIQUE(tx_hash)', 'Transaction hash must be unique.'),
    ]

    @api.depends('tx_hash')
    def _compute_etherscan_url(self):
        for rec in self:
            rec.etherscan_url = 'https://etherscan.io/tx/%s' % rec.tx_hash if rec.tx_hash else False

    @api.depends('raw_value', 'token_id')
    def _compute_value_decimal(self):
        for rec in self:
            try:
                decimals = rec.token_id.decimals if rec.token_id else 18
                rec.value_decimal = int(rec.raw_value or '0') / (10 ** decimals)
            except (ValueError, TypeError):
                rec.value_decimal = 0.0

    @api.depends('to_address', 'watched_address_id')
    def _compute_direction(self):
        for rec in self:
            watched = (rec.watched_address_id.address or '').lower()
            to_addr = (rec.to_address or '').lower()
            rec.direction = 'in' if to_addr == watched else 'out'

    @api.depends('from_address', 'to_address')
    def _compute_display_addresses(self):
        # Load all known addresses once for the batch
        known = {
            r.address.lower(): r.name
            for r in self.env['sca.known_address'].sudo().search([])
        }
        for rec in self:
            from_addr = (rec.from_address or '').lower()
            to_addr = (rec.to_address or '').lower()
            rec.from_display = known.get(from_addr, rec.from_address or '')
            rec.to_display = known.get(to_addr, rec.to_address or '')

    @api.depends('statement_line_id')
    def _compute_is_injected(self):
        for rec in self:
            rec.is_injected = bool(rec.statement_line_id)

    @api.depends('tx_hash', 'log_index')
    def _compute_crypto_tx_ref(self):
        for rec in self:
            if rec.tx_hash:
                rec.crypto_tx_ref = '%s_%s' % (rec.tx_hash, rec.log_index)
            else:
                rec.crypto_tx_ref = False

    # ── Accounting Injection Methods ─────────────────────────────────────

    def _find_journal_mapping(self):
        """Find the journal mapping for this transaction's (address, token)."""
        self.ensure_one()
        return self.env['sca.journal.map'].search([
            ('watched_address_id', '=', self.watched_address_id.id),
            ('token_symbol', '=', self.token_symbol),
        ], limit=1)

    def _find_partner_for_transaction(self):
        """Best-effort partner matching via known address alias."""
        self.ensure_one()
        Partner = self.env['res.partner']

        # Counterparty is the "other" address
        counterparty = self.from_address if self.direction == 'in' else self.to_address
        if not counterparty:
            return Partner

        # Look up in known addresses
        known = self.env['sca.known_address'].sudo().search([
            ('address', '=ilike', counterparty),
        ], limit=1)
        if known:
            partner = Partner.search([
                ('name', 'ilike', known.name),
                ('is_company', '=', True),
            ], limit=1)
            if partner:
                return partner

        return Partner

    def action_inject_to_accounting(self):
        """Create account.bank.statement.line records from selected crypto transactions."""
        StatementLine = self.env['account.bank.statement.line']

        injected = 0
        skipped = 0
        errors = []

        for rec in self:
            # Skip already injected
            if rec.statement_line_id:
                skipped += 1
                continue

            # Skip zero-value
            if not rec.value_decimal:
                skipped += 1
                continue

            # Find journal mapping
            mapping = rec._find_journal_mapping()
            if not mapping or not mapping.journal_id:
                errors.append(
                    '%s: No journal mapping for %s / %s' % (
                        rec.tx_hash[:10], rec.watched_address_id.name, rec.token_symbol)
                )
                continue

            # Dedup check
            dup = self.search([
                ('crypto_tx_ref', '=', rec.crypto_tx_ref),
                ('statement_line_id', '!=', False),
                ('id', '!=', rec.id),
            ], limit=1)
            if dup and dup.statement_line_id:
                rec.statement_line_id = dup.statement_line_id.id
                skipped += 1
                continue

            # Partner matching
            partner = rec._find_partner_for_transaction()

            # Payment reference
            direction_label = 'Received' if rec.direction == 'in' else 'Sent'
            payment_ref = '%s %s %s' % (direction_label, rec.value_decimal, rec.token_symbol)

            # Date
            tx_date = rec.tx_date.date() if rec.tx_date else fields.Date.context_today(rec)

            # Amount with sign based on direction
            amount = rec.value_decimal if rec.direction == 'in' else -rec.value_decimal

            # Multi-currency
            journal = mapping.journal_id
            journal_currency = journal.currency_id or journal.company_id.currency_id
            tx_currency = mapping.currency_id

            vals = {
                'date': tx_date,
                'journal_id': journal.id,
                'payment_ref': payment_ref,
                'amount': amount,
                'crypto_tx_ref': rec.crypto_tx_ref,
            }

            if partner:
                vals['partner_id'] = partner.id

            # Set foreign currency only when currencies differ and amount non-zero
            if tx_currency and tx_currency != journal_currency and amount:
                vals['foreign_currency_id'] = tx_currency.id
                vals['amount_currency'] = amount

            try:
                line = StatementLine.create(vals)
                rec.statement_line_id = line.id
                injected += 1
            except Exception as e:
                errors.append('%s: %s' % (rec.tx_hash[:10], str(e)[:100]))

        # Result notification
        total = len(self)
        msg_parts = ['%d/%d transactions injected to accounting.' % (injected, total)]
        if skipped:
            msg_parts.append('%d skipped (already injected or zero value).' % skipped)
        if errors:
            msg_parts.append('%d errors: %s' % (len(errors), '; '.join(errors[:3])))
            if len(errors) > 3:
                msg_parts.append('... and %d more.' % (len(errors) - 3))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Inject to Accounting'),
                'message': ' '.join(msg_parts),
                'type': 'success' if injected and not errors else ('warning' if errors else 'info'),
                'sticky': bool(errors),
            },
        }

    def action_remove_from_accounting(self):
        """Remove injected statement lines from accounting for selected transactions."""
        removed = 0
        warnings = []

        for rec in self:
            if not rec.statement_line_id:
                continue

            line = rec.sudo().statement_line_id
            move = line.move_id

            # Attempt to unreconcile if reconciled
            if line.is_reconciled:
                try:
                    for ml in move.line_ids:
                        (ml.matched_debit_ids + ml.matched_credit_ids).sudo().unlink()
                except Exception as e:
                    warnings.append(
                        '%s: Could not unreconcile — %s' % (rec.tx_hash[:10], str(e)[:80])
                    )
                    continue

            # Clear link first
            rec.sudo().write({'statement_line_id': False})
            try:
                if move.state == 'posted':
                    move.sudo().button_draft()
                move.sudo().unlink()
                removed += 1
            except Exception as e:
                warnings.append(
                    '%s: Could not delete — %s' % (rec.tx_hash[:10], str(e)[:80])
                )

        msg_parts = ['%d statement line(s) removed from accounting.' % removed]
        if warnings:
            msg_parts.append(' | '.join(warnings[:3]))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Remove from Accounting'),
                'message': ' '.join(msg_parts),
                'type': 'success' if removed and not warnings else 'warning',
                'sticky': bool(warnings),
            },
        }
