# -*- coding: utf-8 -*-

"""Bank Reconciliation Widget — transient model (17.0.8.2.0).

Mirrors stock Enterprise ``bank.rec.widget`` for the parallel
Management Ledger. One row per *bank-side line being processed*; its
``widget_line_ids`` are the candidate counterpart lines the user is
about to reconcile against.

The widget is **transient** — a fresh row is created each time the
user clicks a card in the bank-rec kanban (via
``_action_open_for_st_line``). State is not persisted between
clicks; only the underlying ``jito.ledger.partial.reconcile`` rows
created by ``_action_validate`` survive.

17.0.8.2.0 — stock-style unified reconciliation table. ``display_lines_data``
is a JSON payload consumed by the ``jito_bank_rec_lines_table`` OWL
widget; it synthesises the liquidity row, every picked counterpart, and
the auto-balance/suspense row in a single shape so the front-end can
render them like stock's ``o_bank_rec_lines_widget_table``.

See the OWL components in
``static/src/components/bank_reconciliation/`` for the chrome.
"""

import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class JitoBankRecWidget(models.TransientModel):
    _name = 'jito.bank.rec.widget'
    _description = 'ML Bank Reconciliation Widget'

    # ---- the "liquidity" line (the bank-side line we're reconciling) ----
    st_line_id = fields.Many2one(
        comodel_name='jito.ledger.move.line',
        string='Bank Line',
        required=True,
        ondelete='cascade',
        help='The bank-side jito.ledger.move.line currently being '
             'reconciled. Must be on a posted move and on an account '
             'with reconcile=True.',
    )
    journal_id = fields.Many2one(
        comodel_name='jito.ledger.journal',
        compute='_compute_from_st_line',
        store=False,
    )
    bank_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        compute='_compute_from_st_line',
        store=False,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        compute='_compute_from_st_line',
        store=False,
        readonly=False,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        compute='_compute_from_st_line',
        store=False,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        compute='_compute_from_st_line',
        store=False,
    )
    amount_currency = fields.Monetary(
        compute='_compute_from_st_line',
        store=False,
        currency_field='currency_id',
    )
    date = fields.Date(
        compute='_compute_from_st_line',
        store=False,
    )
    label = fields.Char(
        string='Memo',
        compute='_compute_from_st_line',
        store=False,
    )

    # ---- candidate counterpart lines ------------------------------------
    widget_line_ids = fields.One2many(
        comodel_name='jito.bank.rec.widget.line',
        inverse_name='widget_id',
        string='Reconciliation Lines',
    )
    available_candidate_ids = fields.Many2many(
        comodel_name='jito.ledger.move.line',
        compute='_compute_available_candidate_ids',
        store=False,
        help='Open posted lines (same currency, reconcilable account, '
             'optionally same partner) that the user can match against.',
    )
    selected_aml_ids = fields.Many2many(
        comodel_name='jito.ledger.move.line',
        compute='_compute_selected_aml_ids',
        store=False,
        string='Selected AMLs',
        help='Convenience M2M of the aml_id values currently held in '
             'widget_line_ids — used by the custom amls list view to '
             'visually highlight rows the user already picked.',
    )

    # ---- "Match Existing Entries" filters (17.0.8.1.0) -----------------
    search_query = fields.Char(
        string='Search',
        help='Free-text filter applied to candidates: ilike on memo, '
             'partner name, and source move name.',
    )
    candidate_filter = fields.Selection(
        selection=[
            ('same_partner', 'Same partner'),
            ('all', 'All partners'),
        ],
        string='Candidate Filter',
        default='same_partner',
        help='Narrow the candidate list by partner scope.',
    )

    # ---- Already-reconciled re-open (17.0.8.6.0) -----------------------
    # Populated when the widget is opened on a bank line that has
    # already been reconciled (either directly with an opposite-side
    # counterpart, or via a 17.0.8.5.0 auto-bridging move). The OWL
    # widget reads these to render the bank line + counterparts in the
    # unified top table with reconciled-row styling.
    reconciled_aml_ids = fields.Many2many(
        comodel_name='jito.ledger.move.line',
        relation='jito_bank_rec_widget_reconciled_aml_rel',
        column1='widget_id',
        column2='aml_id',
        string='Already-reconciled Counterparts',
        compute='_compute_reconciled_aml_ids',
        store=False,
        help='Original AR/AP / open-line counterparts that this bank '
             'line was reconciled with on a prior Validate. When '
             'non-empty, the widget renders in reconciled mode '
             '(state=reconciled, Validate hidden).',
    )

    # ---- Suspense + display payload (17.0.8.2.0) -----------------------
    suspense_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        compute='_compute_suspense_account_id',
        store=False,
        help='Clearing account used for the auto-balance row when the '
             'picked counterparts do not fully cover the bank-side '
             "amount. Defaults to the journal's suspense_account_id; "
             'falls back to the first CLR.* account on the same '
             'company if the journal has none.',
    )
    display_lines_data = fields.Text(
        compute='_compute_display_lines_data',
        store=False,
        help='JSON payload of the rows the OWL "lines table" widget '
             'renders: liquidity (bank), each picked counterpart, and '
             'the auto-balance suspense line. Same shape stock uses '
             'for ``o_bank_rec_lines_widget_table``.',
    )

    # ---- state ---------------------------------------------------------
    state = fields.Selection(
        selection=[
            ('invalid', 'Out of balance'),
            ('valid', 'Balanced'),
            ('reconciled', 'Reconciled'),
        ],
        compute='_compute_state',
        store=False,
    )
    balance_amount = fields.Monetary(
        string='Open Balance',
        compute='_compute_state',
        store=False,
        currency_field='currency_id',
        help='Bank-side amount minus the sum of matched widget-line '
             'amounts. Zero = balanced; nonzero = still open.',
    )

    # ---- computes -------------------------------------------------------

    @api.depends('st_line_id')
    def _compute_from_st_line(self):
        for wiz in self:
            line = wiz.st_line_id
            wiz.journal_id = line.journal_id
            wiz.bank_account_id = line.account_id
            wiz.partner_id = line.partner_id
            wiz.currency_id = line.currency_id
            wiz.company_id = line.company_id
            wiz.amount_currency = line.amount_currency
            wiz.date = line.date
            wiz.label = line.name

    @api.depends(
        'st_line_id', 'currency_id', 'partner_id',
        'widget_line_ids.aml_id',
        'search_query', 'candidate_filter',
    )
    def _compute_available_candidate_ids(self):
        """Surface open lines the user can match against.

        Base filter (always applied):
          * same currency as the bank line
          * account.reconcile = True
          * NOT on the same account as the bank line (different side)
          * NOT the bank line itself
          * already-picked widget lines are excluded
          * posted move only
          * reconciled = False

        User-controlled filters (17.0.8.1.0):
          * ``candidate_filter='same_partner'`` (default) — restrict to
            the bank line's partner OR no-partner lines. ``='all'`` —
            no partner restriction.
          * ``search_query`` — ilike on name (memo), partner.name,
            move_name (source).
        """
        Line = self.env['jito.ledger.move.line'].sudo()
        for wiz in self:
            if not wiz.st_line_id:
                wiz.available_candidate_ids = Line
                continue
            already_picked = wiz.widget_line_ids.aml_id.ids
            domain = [
                ('id', '!=', wiz.st_line_id.id),
                ('id', 'not in', already_picked),
                ('account_id', '!=', wiz.st_line_id.account_id.id),
                ('account_id.reconcile', '=', True),
                ('move_state', '=', 'posted'),
                ('reconciled', '=', False),
                ('currency_id', '=', wiz.currency_id.id),
                ('company_id', '=', wiz.company_id.id),
            ]
            if wiz.candidate_filter == 'same_partner' and wiz.partner_id:
                domain += [
                    '|',
                    ('partner_id', '=', wiz.partner_id.id),
                    ('partner_id', '=', False),
                ]
            q = (wiz.search_query or '').strip()
            if q:
                domain += [
                    '|', '|',
                    ('name', 'ilike', q),
                    ('partner_id.name', 'ilike', q),
                    ('move_name', 'ilike', q),
                ]
            wiz.available_candidate_ids = Line.search(
                domain, limit=50, order='date desc, id desc',
            )

    @api.depends('widget_line_ids.aml_id')
    def _compute_selected_aml_ids(self):
        for wiz in self:
            wiz.selected_aml_ids = wiz.widget_line_ids.aml_id

    @api.depends('st_line_id')
    def _compute_reconciled_aml_ids(self):
        """Surface what bank line was reconciled with on prior Validates.

        Two sources, unioned:
          * Direct partials on the bank line itself (opposite-side
            counterparts — the fast-path case).
          * Bridging moves whose ``bank_rec_source_line_id`` points to
            this bank line — for each AR-side mirror, walk its partial
            to the *original* AR/AP line. Bridge-internal lines and
            the bank move's own counter-line are filtered out so the
            user only sees user-meaningful counterparts.
        """
        Line = self.env['jito.ledger.move.line']
        Move = self.env['jito.ledger.move'].sudo()
        for wiz in self:
            bank_line = wiz.st_line_id
            if not bank_line:
                wiz.reconciled_aml_ids = Line
                continue
            found = Line
            # 1) Direct partials on the bank line
            for partial in (bank_line.matched_debit_ids
                            | bank_line.matched_credit_ids):
                other = (partial.debit_line_id
                         if partial.debit_line_id != bank_line
                         else partial.credit_line_id)
                # Skip bridge mirrors — those are surfaced via path (2).
                if other.move_id.bank_rec_source_line_id:
                    continue
                found |= other
            # 2) Bridging moves whose source is this bank line
            bridges = Move.search([
                ('bank_rec_source_line_id', '=', bank_line.id),
                ('state', '=', 'posted'),
            ])
            for bridge in bridges:
                for bm_line in bridge.line_ids:
                    for partial in (bm_line.matched_debit_ids
                                    | bm_line.matched_credit_ids):
                        other = (partial.debit_line_id
                                 if partial.debit_line_id != bm_line
                                 else partial.credit_line_id)
                        # Skip the bridge's own internal lines.
                        if other.move_id.bank_rec_source_line_id:
                            continue
                        # Skip the bank move's other side — that's the
                        # technical income/clearing line, not a
                        # user-meaningful counterpart.
                        if other.move_id == bank_line.move_id:
                            continue
                        found |= other
            wiz.reconciled_aml_ids = found

    @api.depends('st_line_id', 'journal_id', 'company_id')
    def _compute_suspense_account_id(self):
        Account = self.env['jito.ledger.account'].sudo()
        for wiz in self:
            journal_suspense = wiz.journal_id.suspense_account_id
            if journal_suspense:
                wiz.suspense_account_id = journal_suspense
                continue
            if wiz.company_id:
                wiz.suspense_account_id = Account.search([
                    ('company_id', '=', wiz.company_id.id),
                    ('semantic_family', '=', 'clr'),
                ], limit=1)
            else:
                wiz.suspense_account_id = False

    @api.depends(
        'st_line_id', 'amount_currency', 'currency_id', 'partner_id',
        'date', 'label', 'bank_account_id', 'balance_amount',
        'suspense_account_id', 'state', 'reconciled_aml_ids',
        'widget_line_ids.aml_id', 'widget_line_ids.match_amount',
    )
    def _compute_display_lines_data(self):
        """Synthesise the unified-table rows for the OWL widget.

        Row shape per entry:
          {
            'flag': 'liquidity' | 'aml' | 'auto_balance',
            'index': int,                  # stable id within the payload
            'aml_id': int | False,         # source jito.ledger.move.line id (counterpart rows)
            'widget_line_id': int | False, # bank.rec.widget.line id (counterpart rows)
            'account': {'id', 'display_name'},
            'partner': {'id', 'display_name'} | None,
            'date': 'MM/DD/YYYY' | None,
            'date_is_new': bool,
            'debit': float,                # in widget currency
            'credit': float,
            'source_move': {'id', 'display_name'} | None,
            'memo': str | None,
            'removable': bool,
          }
        """
        for wiz in self:
            rows = []
            bank_amount = wiz.amount_currency or 0.0
            bank_is_debit = bank_amount > 0
            reconciled_mode = wiz.state == 'reconciled'
            # 1) Liquidity / bank-side row
            if wiz.st_line_id:
                rows.append({
                    'flag': 'liquidity',
                    'index': 0,
                    'aml_id': wiz.st_line_id.id,
                    'widget_line_id': False,
                    'account': self._line_account(wiz.bank_account_id),
                    'partner': self._line_partner(wiz.partner_id),
                    'date': self._format_date(wiz.date),
                    'date_is_new': False,
                    'debit': bank_amount if bank_is_debit else 0.0,
                    'credit': -bank_amount if not bank_is_debit else 0.0,
                    'source_move': self._line_source_move(wiz.st_line_id),
                    'memo': wiz.label or '',
                    'removable': False,
                    'reconciled': reconciled_mode,
                })
            # 1b) Already-reconciled counterparts (re-open mode)
            if reconciled_mode:
                for idx, aml in enumerate(wiz.reconciled_aml_ids, start=1):
                    aml_amount = aml.amount_currency or 0.0
                    rows.append({
                        'flag': 'aml',
                        'index': idx,
                        'aml_id': aml.id,
                        'widget_line_id': False,
                        'account': self._line_account(aml.account_id),
                        'partner': self._line_partner(aml.partner_id),
                        'date': self._format_date(aml.date),
                        'date_is_new': False,
                        'debit': aml_amount if aml_amount > 0 else 0.0,
                        'credit': -aml_amount if aml_amount < 0 else 0.0,
                        'source_move': self._line_source_move(aml),
                        'memo': aml.name or '',
                        'removable': False,
                        'reconciled': True,
                    })
                wiz.display_lines_data = json.dumps(rows)
                continue
            # 2) Picked counterparts (live editing mode)
            for idx, wl in enumerate(wiz.widget_line_ids, start=1):
                aml = wl.aml_id
                # Counterpart goes on the OPPOSITE side of the bank line.
                # When the bank line is a debit (incoming), the counterpart sits as a credit (e.g. AR clearing).
                if bank_is_debit:
                    debit = 0.0
                    credit = wl.match_amount or 0.0
                else:
                    debit = wl.match_amount or 0.0
                    credit = 0.0
                rows.append({
                    'flag': 'aml',
                    'index': idx,
                    'aml_id': aml.id if aml else False,
                    'widget_line_id': wl.id,
                    'account': self._line_account(aml.account_id) if aml else None,
                    'partner': self._line_partner(aml.partner_id) if aml else None,
                    'date': self._format_date(aml.date) if aml else None,
                    'date_is_new': False,
                    'debit': debit,
                    'credit': credit,
                    'source_move': self._line_source_move(aml) if aml else None,
                    'memo': (aml.name or '') if aml else '',
                    'removable': True,
                    'reconciled': False,
                })
            # 3) Auto-balance / suspense row (only when off-balance)
            if wiz.currency_id and not wiz.currency_id.is_zero(wiz.balance_amount):
                # balance = bank + counterpart_total. When balance > 0
                # the picks left some DEBIT uncovered → suspense takes the
                # missing CREDIT. Mirror logic when balance < 0.
                bal = wiz.balance_amount
                if bal > 0:
                    debit = 0.0
                    credit = bal
                else:
                    debit = -bal
                    credit = 0.0
                # Flip sign convention: the suspense row offsets the open
                # balance, so it goes on the SAME side as the missing
                # counterpart amount.
                rows.append({
                    'flag': 'auto_balance',
                    'index': len(rows),
                    'aml_id': False,
                    'widget_line_id': False,
                    'account': self._line_account(wiz.suspense_account_id),
                    'partner': None,
                    'date': None,
                    'date_is_new': True,
                    'debit': debit,
                    'credit': credit,
                    'source_move': None,
                    'memo': _('NOT RECONCILED'),
                    'removable': False,
                    'reconciled': False,
                })
            wiz.display_lines_data = json.dumps(rows)

    # ---- helpers --------------------------------------------------------

    @staticmethod
    def _line_account(account):
        if not account:
            return None
        return {'id': account.id, 'display_name': account.display_name}

    @staticmethod
    def _line_partner(partner):
        if not partner:
            return None
        return {'id': partner.id, 'display_name': partner.display_name}

    @staticmethod
    def _line_source_move(line):
        if not line:
            return None
        move = getattr(line, 'move_id', False) or getattr(line, 'source_move_id', False)
        if not move:
            name = getattr(line, 'move_name', '') or ''
            return {'id': False, 'display_name': name} if name else None
        return {'id': move.id, 'display_name': move.display_name}

    @staticmethod
    def _format_date(value):
        if not value:
            return None
        return value.strftime('%m/%d/%Y')

    @api.depends(
        'amount_currency', 'widget_line_ids.match_amount',
        'widget_line_ids.aml_id',
        'currency_id', 'reconciled_aml_ids',
    )
    def _compute_state(self):
        for wiz in self:
            # 17.0.8.6.0 — if the bank line is already reconciled,
            # surface that state regardless of widget_line_ids (which
            # will be empty on a fresh re-open).
            if wiz.reconciled_aml_ids:
                wiz.state = 'reconciled'
                wiz.balance_amount = 0.0
                continue
            # Bank-side amount is positive if it's a debit; the
            # counterparts should add up to the opposite sign of the
            # bank line for full match.
            bank_amount = wiz.amount_currency or 0.0
            # Sum widget-line match amounts (positive numbers entered by
            # the user; sign matches the COUNTERPART side, opposite of
            # the bank line).
            counterpart_total = sum(
                wl.signed_match_amount for wl in wiz.widget_line_ids
            )
            # For a debit bank line (+100), counterpart_total should be
            # -100. For a credit bank line (-100), counterpart_total
            # should be +100. Balance = bank + counterpart should be 0.
            balance = bank_amount + counterpart_total
            wiz.balance_amount = balance
            curr = wiz.currency_id
            if not wiz.widget_line_ids:
                wiz.state = 'invalid'
            elif curr and curr.is_zero(balance):
                wiz.state = 'valid'
            else:
                wiz.state = 'invalid'

    # ---- actions --------------------------------------------------------

    @api.model
    def action_open_for_st_line(self, st_line_id):
        """Factory: create a widget bound to st_line_id and return its id.

        Called from the OWL controller when the user clicks a card.
        """
        if not st_line_id:
            raise UserError(_("No bank line selected."))
        line = self.env['jito.ledger.move.line'].browse(st_line_id)
        if not line.exists():
            raise UserError(_("Selected line no longer exists."))
        if not line.account_id.reconcile:
            raise UserError(_(
                "Account '%s' is not reconcilable. Enable 'Allow "
                "Reconciliation' on the account first.",
                line.account_id.code,
            ))
        widget = self.create({'st_line_id': line.id})
        return widget.id

    def action_add_new_aml(self, aml_id):
        """Add a candidate aml as a widget line. Public; called from
        the OWL ``jito_bank_rec_amls_list_view`` row-click handler.

        Match-amount defaults to the absolute residual of the
        candidate so a single click on an open AR/AP item that matches
        the bank amount immediately balances the widget.
        """
        self.ensure_one()
        if self.state == 'reconciled':
            raise UserError(_(
                "This bank line has already been reconciled. Reverse "
                "the bridging journal entry first if you need to "
                "re-match it against different counterparts."
            ))
        aml = self.env['jito.ledger.move.line'].browse(int(aml_id))
        if not aml.exists():
            raise UserError(_("Candidate line no longer exists."))
        if aml.id in self.widget_line_ids.aml_id.ids:
            return False
        self.env['jito.bank.rec.widget.line'].create({
            'widget_id': self.id,
            'aml_id': aml.id,
            'match_amount': abs(aml.amount_residual_currency),
            'flag': 'aml_match',
        })
        return True

    def action_remove_new_aml(self, aml_id):
        """Remove any widget line(s) pointing at this aml. Public;
        called from the same row-click handler when the user clicks
        an already-selected row.
        """
        self.ensure_one()
        aml_id = int(aml_id)
        lines = self.widget_line_ids.filtered(lambda l: l.aml_id.id == aml_id)
        lines.unlink()
        return True

    def action_reset(self):
        self.ensure_one()
        self.widget_line_ids.unlink()
        return True

    def action_reset_reconciliation(self):
        """Unwind a previously-validated reconciliation for this bank
        line (17.0.8.8.0). Two paths, both end with the originals open
        again so the user can pick different counterparts:

        * **Bridged** (Patch 3): for every bridging move whose
          ``bank_rec_source_line_id`` is this bank line, unlink the
          partials touching its lines, reset to draft, and delete the
          move. Auto-spawned bridging entries are owned by this widget
          flow, so dropping them is safe and keeps the books balanced
          (no reversal counter-entry needed — the move never existed,
          so there's nothing to offset).
        * **Direct** (opposite-side reconcile, no bridge): unlink the
          partials directly on the bank line.

        Returns an ``ir.actions.client`` reload so the kanban + form
        re-render with the originals back to "open" status.
        """
        self.ensure_one()
        bank_line = self.st_line_id
        if not bank_line:
            return False
        Move = self.env['jito.ledger.move'].sudo()

        # 1) Bridging moves first — they carry the partials and the
        # synthetic double-entry. Unlink partials → action_draft →
        # unlink the move itself.
        bridges = Move.search([
            ('bank_rec_source_line_id', '=', bank_line.id),
        ])
        for bridge in bridges:
            for line in bridge.line_ids:
                (line.matched_debit_ids
                 | line.matched_credit_ids).unlink()
            if bridge.state == 'posted':
                bridge.action_draft()
            bridge.unlink()

        # 2) Direct partials on the bank line — opposite-side fast path.
        (bank_line.matched_debit_ids
         | bank_line.matched_credit_ids).unlink()

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_validate(self):
        """Reconcile the bank line against every picked counterpart.

        Two paths, picked per widget-line by sign:

        * **Opposite-side counterparts** (bank DR ↔ counterpart CR or
          vice versa): create one ``jito.ledger.partial.reconcile``
          directly between the bank line and the counterpart. This is
          the cheap case that worked before 17.0.8.5.0.
        * **Same-side counterparts** (both DR or both CR, e.g.
          ``DR DeFi Wallet`` matched against an open
          ``DR MGT.RECEIVABLE`` from the invoice — the user's reported
          scenario): a direct partial would violate the
          DR>0 / CR<0 invariant on partial reconcile. Auto-spawn a
          balanced bridging ``jito.ledger.move`` that routes the open
          balance through the bank move's counter-account, then
          reconcile each side on its own account.

        Both paths are wrapped in the same transaction — if anything
        raises, nothing is persisted.
        """
        self.ensure_one()
        if self.state != 'valid':
            raise UserError(_(
                "Cannot validate — the selection is not balanced "
                "(open balance: %s).", self.balance_amount,
            ))
        Partial = self.env['jito.ledger.partial.reconcile']
        bank_line = self.st_line_id
        bank_sign = 1 if bank_line.amount_currency > 0 else -1

        # Partition counterparts: same-side ones need bridging.
        direct = []
        same_side = []
        for wl in self.widget_line_ids:
            if not wl.match_amount or wl.match_amount <= 0:
                continue
            aml = wl.aml_id
            aml_sign = 1 if aml.amount_currency > 0 else -1
            if bank_sign != aml_sign:
                direct.append((aml, wl.match_amount))
            else:
                same_side.append((aml, wl.match_amount, aml_sign))

        # Opposite-side reconciles — single partial each, no bridge.
        for aml, match in direct:
            if bank_sign > 0:
                Partial.create({
                    'debit_line_id': bank_line.id,
                    'credit_line_id': aml.id,
                    'amount': match,
                })
            else:
                Partial.create({
                    'debit_line_id': aml.id,
                    'credit_line_id': bank_line.id,
                    'amount': match,
                })

        # Same-side reconciles — auto-bridge through the bank move's
        # counter-account.
        if same_side:
            self._action_validate_bridged(bank_line, bank_sign, same_side)

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def _action_validate_bridged(self, bank_line, bank_sign, pairs):
        """Post a bridging move for same-side picks and reconcile both
        legs.

        For each (aml, match, aml_sign) pair the bridging move grows by
        two lines:

        * One on ``aml.account_id`` with sign ``-aml_sign * match`` —
          this is the leg that closes ``aml`` (same account, opposite
          sign → satisfies the partial-reconcile invariant).
        * One on the bank move's counter-account with sign
          ``+bank_sign * match`` — this is the leg that nets against
          the bank move's own counter-line (whose sign is
          ``-bank_sign``).

        The two legs per pair always sum to zero, so the bridging move
        balances per-currency regardless of how many pairs there are.

        If the counter-account is not marked ``reconcile=True``, the
        counter-side partial is skipped — the AR/AP side still closes
        cleanly and the open balance simply rolls forward on the
        income/clearing account, which is the typical state of
        non-reconcilable accounts.
        """
        Line = self.env['jito.ledger.move.line']
        Partial = self.env['jito.ledger.partial.reconcile']
        bank_move = bank_line.move_id

        counter_lines = (bank_move.line_ids - bank_line).filtered(
            lambda l: l.currency_id == bank_line.currency_id
        )
        if len(counter_lines) != 1:
            raise UserError(_(
                "Auto-bridging requires the bank move '%s' to have "
                "exactly one counter-line in %s (found %d). Either "
                "re-book the receipt as a clean two-line move or post "
                "a manual reclassification entry that places a %s on "
                "%s, then reconcile that line with the open AR/AP "
                "balance.",
                bank_move.name or bank_move.id,
                bank_line.currency_id.name,
                len(counter_lines),
                'credit' if bank_sign > 0 else 'debit',
                pairs[0][0].account_id.code,
            ))
        bridge_original = counter_lines
        bridge_account = bridge_original.account_id
        if bridge_original.reconciled:
            raise UserError(_(
                "The counter-line on '%s' (%s) is already fully "
                "reconciled. Cannot auto-bridge — choose a counterpart "
                "that has not been settled yet, or post a manual "
                "reclassification.",
                bank_move.name or bank_move.id,
                bridge_account.code,
            ))

        # Build the bridging move's line vals; remember each pair's
        # mirror indices so we can find them again after creation.
        line_vals = []
        pair_indices = []
        for aml, match, aml_sign in pairs:
            aml_mirror_idx = len(line_vals)
            line_vals.append({
                'account_id': aml.account_id.id,
                'currency_id': aml.currency_id.id,
                'amount_currency': -aml_sign * match,
                'partner_id': aml.partner_id.id or False,
                'name': _("Bank-rec bridge — %s",
                          aml.move_name or aml.name or ''),
            })
            bridge_mirror_idx = len(line_vals)
            line_vals.append({
                'account_id': bridge_account.id,
                'currency_id': bank_line.currency_id.id,
                'amount_currency': bank_sign * match,
                'partner_id': bank_line.partner_id.id or False,
                'name': _("Bank-rec bridge — %s",
                          bank_move.name or ''),
            })
            pair_indices.append((aml, match, aml_sign,
                                  aml_mirror_idx, bridge_mirror_idx))

        bridging_move = self.env['jito.ledger.move'].create({
            'ledger_id': bank_line.ledger_id.id,
            'journal_id': bank_move.journal_id.id,
            'entry_type': 'nl_doc',
            'date': fields.Date.context_today(self),
            'ref': _("Bank-rec bridge for %s",
                     bank_move.name or bank_move.id),
            # 17.0.8.6.0 — back-reference for re-open surface.
            'bank_rec_source_line_id': bank_line.id,
            'line_ids': [(0, 0, v) for v in line_vals],
        })
        bridging_move.action_post()

        # `_order = 'move_id, id'` on the line model and sequential ID
        # allocation in the same transaction guarantee that
        # bridging_move.line_ids preserves the order we passed.
        created_lines = bridging_move.line_ids
        for aml, match, aml_sign, aml_idx, bridge_idx in pair_indices:
            aml_mirror = created_lines[aml_idx]
            bridge_mirror = created_lines[bridge_idx]

            # AR/AP-side partial — same account on both lines, opposite
            # signs by construction.
            if aml_sign > 0:
                Partial.create({
                    'debit_line_id': aml.id,
                    'credit_line_id': aml_mirror.id,
                    'amount': match,
                })
            else:
                Partial.create({
                    'debit_line_id': aml_mirror.id,
                    'credit_line_id': aml.id,
                    'amount': match,
                })

            # Counter-account partial — skipped silently if the bridge
            # account isn't reconcilable (typical for income accounts).
            if not bridge_account.reconcile:
                continue
            if bank_sign > 0:
                # original counter-line is CR (negative), bridge mirror
                # is DR (positive)
                Partial.create({
                    'debit_line_id': bridge_mirror.id,
                    'credit_line_id': bridge_original.id,
                    'amount': match,
                })
            else:
                Partial.create({
                    'debit_line_id': bridge_original.id,
                    'credit_line_id': bridge_mirror.id,
                    'amount': match,
                })
