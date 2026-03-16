import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

UPWORK_AUTH_URL = 'https://www.upwork.com/ab/account-security/oauth2/authorize'
UPWORK_TOKEN_ENDPOINT = 'https://www.upwork.com/api/v3/oauth2/token'
UPWORK_GRAPHQL_URL = 'https://api.upwork.com/graphql'

QUERY_COMPANY_SELECTOR = """
{
  companySelector {
    items {
      title
      photoUrl
      organizationId
      organizationRid
      organizationType
    }
  }
}
"""

QUERY_ACCOUNTING_ENTITY = """
{
  accountingEntity {
    id
  }
}
"""

QUERY_TRANSACTION_HISTORY = """
{
  transactionHistory(transactionHistoryFilter: {
    transactionDateTime_bt: {
      rangeStart: "%s",
      rangeEnd: "%s",
    }
    aceIds_any: [%s]
  }) {
    transactionDetail {
      transactionHistoryRow {
        rowNumber
        runningChargeableBalance { rawValue currency displayValue }
        recordId
        remainder
        amountCreditedToUser { rawValue currency displayValue }
        transactionReviewDueDate
        transactionCreationDate
        relatedUserPaymentMethod
        accountingSubtype
        descriptionUI
        relatedAssignment
        amountSentInOrigCurrency { rawValue currency displayValue }
        paymentGuaranteed
        fixedPriceEARMark
        relatedTransactionId
        relatedInvoiceId
        fullyPaidDate
        type
        transactionAmount { rawValue currency displayValue }
        relatedAccountingEntity
        description
        purchaseOrderNumber
        assignmentAgencyName
        assignmentCompanyName
        assignmentDeveloperName
        assignmentTeamCompanyId
        assignmentTeamCompanyReference
        assignmentTeamId
        assignmentTeamReference
        assignmentTeamUserId
        assignmentTeamUserReference
        payment { rawValue currency displayValue }
        paymentStatus
        prefix
      }
    }
  }
}
"""


class UsaSettings(models.Model):
    """Singleton configuration record for Upwork Simple Accounting integration."""

    _name = 'usa.settings'
    _description = 'Upwork Simple Accounting Settings'
    _inherit = ['mail.thread']

    lock_field = fields.Char(default='global', copy=False)

    _sql_constraints = [
        (
            'singleton',
            'UNIQUE(lock_field)',
            'Only one Upwork settings record is allowed.',
        ),
    ]

    # ── OAuth / API Credentials ───────────────────────────────────────────────

    upwork_key = fields.Char(
        string='API Key (Client ID)',
        copy=False,
        tracking=True,
    )
    upwork_secret = fields.Char(
        string='API Secret (Client Secret)',
        copy=False,
    )
    callback_url = fields.Char(
        string='Callback URL for OAuth',
        compute='_compute_callback_url',
        store=True,
        readonly=False,
    )
    access_token = fields.Char(string='Access Token', copy=False)
    refresh_token = fields.Char(string='Refresh Token', copy=False)
    token_expiry = fields.Datetime(string='Token Expiry', copy=False, readonly=True)
    oauth_state = fields.Selection(
        selection=[
            ('not_connected', 'Not Connected'),
            ('connected', 'Connected'),
        ],
        string='Connection Status',
        compute='_compute_oauth_state',
        store=False,
    )

    # ── Organization ─────────────────────────────────────────────────────────

    selected_organization_id = fields.Many2one(
        'usa.organization',
        string='Organization',
        ondelete='set null',
        tracking=True,
    )
    accounting_entity_id = fields.Char(
        string='Accounting Entity ID',
        readonly=True,
        copy=False,
    )

    # ── Ledger Sync ───────────────────────────────────────────────────────────

    sync_date_start = fields.Date(
        string='Period Start',
        default=lambda self: fields.Date.today().replace(month=1, day=1),
    )
    sync_date_end = fields.Date(
        string='Period End',
        default=fields.Date.today,
    )
    last_sync_date = fields.Datetime(
        string='Last Synced',
        readonly=True,
        copy=False,
    )
    transaction_count = fields.Integer(
        string='Transactions Synced',
        compute='_compute_transaction_count',
    )

    # ── Computed ──────────────────────────────────────────────────────────────

    @api.depends('access_token')
    def _compute_oauth_state(self):
        for rec in self:
            rec.oauth_state = 'connected' if rec.sudo().access_token else 'not_connected'

    @api.depends()
    def _compute_callback_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')
        for rec in self:
            if not rec.callback_url:
                rec.callback_url = '%s/upwork/callback' % base_url

    def _compute_transaction_count(self):
        for rec in self:
            rec.transaction_count = self.env['usa.transaction'].sudo().search_count([])

    # ── Singleton helpers ─────────────────────────────────────────────────────

    @api.model
    def _get_singleton(self):
        """Return the singleton record, creating it if needed."""
        record = self.sudo().search([], limit=1)
        if not record:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')
            record = self.sudo().create({
                'callback_url': '%s/upwork/callback' % base_url,
            })
        return record

    @api.model
    def action_open_settings(self):
        """Open the singleton settings form."""
        record = self._get_singleton()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def action_open_ledger(self):
        """Open settings singleton scrolled to Ledger tab (same form, different view)."""
        record = self._get_singleton()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_active_tab': 'ledger'},
        }

    # ── OAuth Actions ─────────────────────────────────────────────────────────

    def action_connect_upwork(self):
        """Build the Upwork OAuth2 authorization URL and open it in a new tab."""
        self.ensure_one()
        if not self.upwork_key:
            raise UserError(_('Please enter the Upwork API Key (Client ID) first.'))
        if not self.callback_url:
            raise UserError(_('Callback URL is not set.'))
        auth_url = (
            '%s?client_id=%s&redirect_uri=%s&response_type=code'
            % (
                UPWORK_AUTH_URL,
                urllib.parse.quote(self.upwork_key, safe=''),
                urllib.parse.quote(self.callback_url, safe=''),
            )
        )
        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }

    def action_disconnect(self):
        """Clear OAuth tokens and disconnect from Upwork."""
        self.ensure_one()
        self.sudo().write({
            'access_token': False,
            'refresh_token': False,
            'token_expiry': False,
            'selected_organization_id': False,
            'accounting_entity_id': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Token management ──────────────────────────────────────────────────────

    def _is_token_valid(self):
        self.ensure_one()
        return (
            self.sudo().token_expiry
            and self.sudo().token_expiry >= (fields.Datetime.now() + timedelta(minutes=1))
        )

    def _refresh_access_token(self):
        """Silently refresh the access token using the stored refresh token."""
        self.ensure_one()
        refresh_token = self.sudo().refresh_token
        if not refresh_token:
            raise UserError(_(
                'No refresh token available. Please reconnect your Upwork account.'
            ))

        post_data = urllib.parse.urlencode({
            'refresh_token': refresh_token,
            'client_id': self.upwork_key or '',
            'client_secret': self.sudo().upwork_secret or '',
            'grant_type': 'refresh_token',
        }).encode()

        req = urllib.request.Request(
            UPWORK_TOKEN_ENDPOINT,
            data=post_data,
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'Mozilla/5.0 (compatible; OdooUpworkIntegration/1.0)',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            try:
                err = json.loads(body).get('error_description', body)
            except Exception:
                err = body[:200]
            if exc.code in (400, 401):
                self.sudo().write({
                    'access_token': False,
                    'refresh_token': False,
                    'token_expiry': False,
                })
            raise UserError(_('Failed to refresh Upwork access token: %s', err))
        except Exception as exc:
            raise UserError(_('Failed to refresh Upwork access token: %s', str(exc)))

        ttl = data.get('expires_in', 3600)
        self.sudo().write({
            'access_token': data.get('access_token'),
            'token_expiry': fields.Datetime.now() + timedelta(seconds=int(ttl)),
        })

    def _get_valid_access_token(self):
        """Return a valid access token, refreshing if needed."""
        self.ensure_one()
        if not self.sudo().access_token:
            raise UserError(_(
                'Upwork account is not connected. '
                'Please go to Configuration → Upwork Configuration and connect.'
            ))
        if not self._is_token_valid():
            self._refresh_access_token()
        return self.sudo().access_token

    # ── GraphQL helper ────────────────────────────────────────────────────────

    def _graphql_query(self, query, tenant_id=None):
        """Execute a GraphQL query against the Upwork API.

        Returns the parsed JSON response dict.
        Raises UserError on HTTP or API errors.
        """
        self.ensure_one()
        token = self._get_valid_access_token()
        headers = {
            'Authorization': 'Bearer %s' % token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (compatible; OdooUpworkIntegration/1.0)',
        }
        if tenant_id:
            headers['X-Upwork-API-TenantId'] = str(tenant_id)

        payload = json.dumps({'query': query}).encode()
        req = urllib.request.Request(
            UPWORK_GRAPHQL_URL,
            data=payload,
            headers=headers,
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            _logger.error("Upwork GraphQL HTTP error %s: %s", exc.code, body[:500])
            raise UserError(_('Upwork API error %s: %s', exc.code, body[:200]))
        except Exception as exc:
            raise UserError(_('Upwork API request failed: %s', str(exc)))

        if result.get('errors'):
            msgs = '; '.join(e.get('message', str(e)) for e in result['errors'])
            raise UserError(_('Upwork GraphQL error: %s', msgs))
        return result

    # ── Organization actions ──────────────────────────────────────────────────

    def action_load_organizations(self):
        """Fetch organizations from Upwork companySelector and populate the dropdown."""
        self.ensure_one()
        result = self._graphql_query(QUERY_COMPANY_SELECTOR)
        items = (
            result.get('data', {})
            .get('companySelector', {})
            .get('items', [])
        )
        if not items:
            raise UserError(_('No organizations returned from Upwork API.'))

        # Sync organizations: delete all and recreate from API response
        self.env['usa.organization'].sudo().search([]).unlink()
        for item in items:
            self.env['usa.organization'].sudo().create({
                'title': item.get('title') or '',
                'organization_id': item.get('organizationId') or '',
                'organization_rid': item.get('organizationRid') or '',
                'organization_type': item.get('organizationType') or '',
                'photo_url': item.get('photoUrl') or '',
            })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.onchange('selected_organization_id')
    def _onchange_selected_organization(self):
        """Auto-load accounting entity when organization changes."""
        if self.selected_organization_id and self.sudo().access_token:
            try:
                org_id = self.selected_organization_id.organization_id
                result = self._graphql_query(QUERY_ACCOUNTING_ENTITY, tenant_id=org_id)
                entity_id = (
                    result.get('data', {})
                    .get('accountingEntity', {})
                    .get('id')
                )
                self.accounting_entity_id = str(entity_id) if entity_id else False
            except Exception as exc:
                _logger.warning("Could not auto-load accounting entity: %s", exc)
                self.accounting_entity_id = False

    def action_load_accounting_entity(self):
        """Manually reload the accounting entity ID for the selected organization."""
        self.ensure_one()
        if not self.selected_organization_id:
            raise UserError(_('Please select an organization first.'))
        org_id = self.selected_organization_id.organization_id
        result = self._graphql_query(QUERY_ACCOUNTING_ENTITY, tenant_id=org_id)
        entity_id = (
            result.get('data', {})
            .get('accountingEntity', {})
            .get('id')
        )
        self.accounting_entity_id = str(entity_id) if entity_id else False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Transaction sync ──────────────────────────────────────────────────────

    def action_sync_transactions(self):
        """Download all transactions for the configured period and accounting entity."""
        self.ensure_one()
        if not self.accounting_entity_id:
            raise UserError(_(
                'No accounting entity configured. '
                'Please select an organization first.'
            ))
        if not self.sync_date_start or not self.sync_date_end:
            raise UserError(_('Please set Period Start and Period End before syncing.'))

        period_start = '%sT00:00:00+00:00' % self.sync_date_start.strftime('%Y-%m-%d')
        period_end = '%sT23:59:59+00:00' % self.sync_date_end.strftime('%Y-%m-%d')
        ace_id = self.accounting_entity_id

        query = QUERY_TRANSACTION_HISTORY % (period_start, period_end, ace_id)
        org_id = (
            self.selected_organization_id.organization_id
            if self.selected_organization_id
            else None
        )
        result = self._graphql_query(query, tenant_id=org_id)

        rows = (
            result.get('data', {})
            .get('transactionHistory', {})
            .get('transactionDetail', {})
            .get('transactionHistoryRow', [])
        )

        created = 0
        updated = 0
        Transaction = self.env['usa.transaction'].sudo()

        for row in rows:
            vals = self._map_transaction_row(row)
            record_id = vals.get('record_id')
            if not record_id:
                continue
            existing = Transaction.search([('record_id', '=', record_id)], limit=1)
            if existing:
                existing.write(vals)
                updated += 1
            else:
                Transaction.create(vals)
                created += 1

        self.sudo().write({'last_sync_date': fields.Datetime.now()})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': _('Synced %d transactions (%d new, %d updated).', len(rows), created, updated),
                'type': 'success',
                'sticky': False,
            },
        }

    def _map_transaction_row(self, row):
        """Map a transactionHistoryRow dict to usa.transaction field values."""

        def _money_raw(obj):
            if not obj:
                return 0.0
            try:
                return float(obj.get('rawValue') or 0)
            except (ValueError, TypeError):
                return 0.0

        def _money_currency(obj):
            if not obj:
                return ''
            return obj.get('currency') or ''

        def _dt(val):
            if not val:
                return False
            # Upwork returns ISO8601: '2025-12-31T00:00:00+0000'
            from datetime import datetime, timezone
            import re
            # Normalize offset format +0000 → +00:00
            val_norm = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', val)
            try:
                dt = datetime.fromisoformat(val_norm)
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                return False

        return {
            'record_id': str(row.get('recordId') or ''),
            'row_number': int(row.get('rowNumber') or 0),
            'transaction_creation_date': _dt(row.get('transactionCreationDate')),
            'transaction_review_due_date': _dt(row.get('transactionReviewDueDate')),
            'fully_paid_date': _dt(row.get('fullyPaidDate')),
            'transaction_type': row.get('type') or '',
            'accounting_subtype': row.get('accountingSubtype') or '',
            'payment_status': row.get('paymentStatus') or '',
            'payment_guaranteed': bool(row.get('paymentGuaranteed')),
            'prefix': row.get('prefix') or '',
            'transaction_amount_raw': _money_raw(row.get('transactionAmount')),
            'transaction_amount_currency': _money_currency(row.get('transactionAmount')),
            'amount_credited_raw': _money_raw(row.get('amountCreditedToUser')),
            'amount_credited_currency': _money_currency(row.get('amountCreditedToUser')),
            'running_balance_raw': _money_raw(row.get('runningChargeableBalance')),
            'running_balance_currency': _money_currency(row.get('runningChargeableBalance')),
            'amount_sent_orig_raw': _money_raw(row.get('amountSentInOrigCurrency')),
            'amount_sent_orig_currency': _money_currency(row.get('amountSentInOrigCurrency')),
            'payment_raw': _money_raw(row.get('payment')),
            'payment_currency': _money_currency(row.get('payment')),
            'remainder': str(row.get('remainder') or ''),
            'description': row.get('description') or '',
            'description_ui': row.get('descriptionUI') or '',
            'purchase_order_number': row.get('purchaseOrderNumber') or '',
            'related_transaction_id': str(row.get('relatedTransactionId') or ''),
            'related_invoice_id': str(row.get('relatedInvoiceId') or ''),
            'related_assignment': str(row.get('relatedAssignment') or ''),
            'related_accounting_entity': str(row.get('relatedAccountingEntity') or ''),
            'related_user_payment_method': str(row.get('relatedUserPaymentMethod') or ''),
            'fixed_price_earmark': str(row.get('fixedPriceEARMark') or ''),
            'assignment_agency_name': row.get('assignmentAgencyName') or '',
            'assignment_company_name': row.get('assignmentCompanyName') or '',
            'assignment_developer_name': row.get('assignmentDeveloperName') or '',
            'assignment_team_id': str(row.get('assignmentTeamId') or ''),
            'assignment_team_reference': str(row.get('assignmentTeamReference') or ''),
            'assignment_team_company_id': str(row.get('assignmentTeamCompanyId') or ''),
            'assignment_team_company_reference': str(row.get('assignmentTeamCompanyReference') or ''),
            'assignment_team_user_id': str(row.get('assignmentTeamUserId') or ''),
            'assignment_team_user_reference': str(row.get('assignmentTeamUserReference') or ''),
            'raw_json': json.dumps(row, default=str, indent=2),
            'sync_date': fields.Datetime.now(),
        }

    def action_open_transactions(self):
        """Open the transaction list view."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Upwork Transactions'),
            'res_model': 'usa.transaction',
            'view_mode': 'tree,form',
            'target': 'current',
        }

    def action_open_invoice_config_full(self):
        """Open the invoice generation configuration standalone form."""
        self.ensure_one()
        return self.env['usa.invoice.config'].action_open()
