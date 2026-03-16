import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

QUERY_CONTRACT_DETAILS = """
{
  contractDetails(id: "%s") {
    id
    title
    status
    deliveryModel
    createDate
    modifyDate
    startDate
    endDate
    offerId
    metadata {
      agencyContract
    }
    terms {
      fixedPriceTerms {
        id
        fpCharge { currency rawValue displayValue }
        fixedAmount { currency rawValue displayValue }
        createDate
        modifyDate
        changeDate
        createdBy { id name }
        creatorUserType
        changedBy { id name }
        startDate
        endDate
        jobType
        ptcData { startDate endDate }
        milestones {
          id
          createdBy { id name }
          dueDateTime
          state
          description
          currentEscrowAmount { currency rawValue displayValue }
          depositAmount { currency rawValue displayValue }
          fundedAmount { currency rawValue displayValue }
          paid { currency rawValue displayValue }
          overpayment { currency rawValue displayValue }
          bonus { currency rawValue displayValue }
          previousMilestoneUnusedDeposit { currency rawValue displayValue }
          submissionCount
          sequenceId
          payComments
          lastSubmissionCreatedTime
          createdDateTime
          modifiedDateTime
          instructions
        }
      }
      hourlyTerms {
        id
        hourlyRate { currency rawValue displayValue }
        createDate
        modifyDate
        changeDate
        createdBy { id name }
        startDate
        manualTimeAllowed
        endDate
      }
    }
  }
}
"""


class UsaContractDetail(models.Model):
    """Contract details fetched from Upwork contractDetails GraphQL query."""

    _name = 'usa.contract.detail'
    _description = 'Upwork Contract Detail'
    _inherit = ['mail.thread']
    _rec_name = 'title'
    _order = 'upwork_create_date desc'

    # ── Identity ──────────────────────────────────────────────────────────────

    contract_id = fields.Char(
        string='Contract ID', index=True, copy=False, readonly=True)
    title = fields.Char(string='Title', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    delivery_model = fields.Char(string='Delivery Model', readonly=True)
    offer_id = fields.Char(string='Offer ID', readonly=True)
    agency_contract = fields.Boolean(string='Agency Contract', readonly=True)
    last_fetched = fields.Datetime(string='Last Fetched', readonly=True, copy=False)

    # ── Dates ─────────────────────────────────────────────────────────────────

    upwork_create_date = fields.Datetime(string='Created (Upwork)', readonly=True)
    upwork_modify_date = fields.Datetime(string='Modified (Upwork)', readonly=True)
    start_date = fields.Date(string='Start Date', readonly=True)
    end_date = fields.Date(string='End Date', readonly=True)

    # ── Hourly Terms ──────────────────────────────────────────────────────────

    hourly_term_id = fields.Char(string='Hourly Term ID', readonly=True)
    hourly_rate_raw = fields.Float(
        string='Hourly Rate', digits=(8, 2), readonly=True)
    hourly_rate_currency = fields.Char(string='Rate Currency', readonly=True)
    hourly_rate_display = fields.Char(string='Rate Display', readonly=True)
    hourly_start_date = fields.Date(string='Hourly Start', readonly=True)
    hourly_end_date = fields.Date(string='Hourly End', readonly=True)
    hourly_manual_time_allowed = fields.Boolean(
        string='Manual Time Allowed', readonly=True)

    # ── Fixed Price Terms ─────────────────────────────────────────────────────

    fixed_term_id = fields.Char(string='Fixed Term ID', readonly=True)
    fp_charge_raw = fields.Float(
        string='FP Charge', digits=(8, 2), readonly=True)
    fp_charge_currency = fields.Char(string='FP Charge Currency', readonly=True)
    fixed_amount_raw = fields.Float(
        string='Fixed Amount', digits=(8, 2), readonly=True)
    fixed_amount_currency = fields.Char(string='Fixed Amount Currency', readonly=True)
    fixed_start_date = fields.Date(string='Fixed Start', readonly=True)
    fixed_end_date = fields.Date(string='Fixed End', readonly=True)
    job_type = fields.Char(string='Job Type', readonly=True)

    # ── Relations ─────────────────────────────────────────────────────────────

    milestone_ids = fields.One2many(
        'usa.contract.milestone', 'contract_detail_id', string='Milestones')
    transaction_ids = fields.One2many(
        'usa.transaction', 'contract_detail_id', string='Transactions')
    transaction_count = fields.Integer(
        string='Transactions', compute='_compute_transaction_count')

    # ── Raw ───────────────────────────────────────────────────────────────────

    raw_json = fields.Text(string='Raw JSON', readonly=True, copy=False)

    # ── Computed ──────────────────────────────────────────────────────────────

    def _compute_transaction_count(self):
        for rec in self:
            rec.transaction_count = len(rec.transaction_ids)

    def action_view_transactions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Transactions',
            'res_model': 'usa.transaction',
            'view_mode': 'tree,form',
            'domain': [('contract_detail_id', '=', self.id)],
            'context': {},
        }

    def action_refresh(self):
        """Re-fetch this contract's data from Upwork and update the record."""
        self.ensure_one()
        self.env['usa.contract.detail'].fetch_and_save(self.contract_id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Contract Refreshed'),
                'message': _('Contract %s data updated from Upwork.') % self.contract_id,
                'type': 'success',
            },
        }

    # ── Fetch ─────────────────────────────────────────────────────────────────

    @api.model
    def fetch_and_save(self, contract_id):
        """Fetch contractDetails from Upwork and create/update the record.

        Returns the (created or updated) usa.contract.detail record.
        """
        if not contract_id:
            raise UserError(_('No Contract ID provided.'))

        settings = self.env['usa.settings'].sudo()._get_singleton()
        org_id = (
            settings.selected_organization_id.organization_id
            if settings.selected_organization_id else None
        )
        query = QUERY_CONTRACT_DETAILS % contract_id
        result = settings._graphql_query(query, tenant_id=org_id)

        data = result.get('data', {}).get('contractDetails')
        if not data:
            raise UserError(_(
                'No contract details returned for Contract ID %s. '
                'Check that the ID is correct and the organization is selected.',
                contract_id,
            ))

        vals = self._map_contract_data(data)
        vals['raw_json'] = json.dumps(data, default=str, indent=2)
        vals['last_fetched'] = fields.Datetime.now()

        existing = self.sudo().search([('contract_id', '=', contract_id)], limit=1)
        if existing:
            # Remove old milestones before re-creating
            existing.milestone_ids.sudo().unlink()
            milestones = vals.pop('milestone_ids', [])
            existing.sudo().write(vals)
            for m_vals in milestones:
                self.env['usa.contract.milestone'].sudo().create(
                    dict(m_vals, contract_detail_id=existing.id)
                )
            return existing
        else:
            milestones = vals.pop('milestone_ids', [])
            record = self.sudo().create(vals)
            for m_vals in milestones:
                self.env['usa.contract.milestone'].sudo().create(
                    dict(m_vals, contract_detail_id=record.id)
                )
            return record

    @staticmethod
    def _map_contract_data(data):
        """Map contractDetails GraphQL response to usa.contract.detail field values."""

        def _dt(val):
            if not val:
                return False
            from datetime import datetime, timezone
            import re
            val_norm = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', str(val))
            try:
                dt = datetime.fromisoformat(val_norm)
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                return False

        def _date(val):
            dt = UsaContractDetail._map_contract_data.__func__ if False else None
            if not val:
                return False
            from datetime import datetime
            for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d'):
                try:
                    return datetime.strptime(str(val)[:10], '%Y-%m-%d').date()
                except ValueError:
                    pass
            return False

        def _money_raw(obj):
            if not obj:
                return 0.0
            try:
                return float(obj.get('rawValue') or 0)
            except (ValueError, TypeError):
                return 0.0

        def _money_cur(obj):
            return (obj or {}).get('currency') or ''

        metadata = data.get('metadata') or {}
        terms = data.get('terms') or {}
        hourly = (terms.get('hourlyTerms') or [None])[0] if isinstance(
            terms.get('hourlyTerms'), list) else terms.get('hourlyTerms')
        fixed = (terms.get('fixedPriceTerms') or [None])[0] if isinstance(
            terms.get('fixedPriceTerms'), list) else terms.get('fixedPriceTerms')

        vals = {
            'contract_id': str(data.get('id') or ''),
            'title': data.get('title') or '',
            'status': data.get('status') or '',
            'delivery_model': data.get('deliveryModel') or '',
            'offer_id': str(data.get('offerId') or ''),
            'agency_contract': bool(metadata.get('agencyContract')),
            'upwork_create_date': _dt(data.get('createDate')),
            'upwork_modify_date': _dt(data.get('modifyDate')),
            'start_date': _date(data.get('startDate')),
            'end_date': _date(data.get('endDate')),
        }

        if hourly:
            vals.update({
                'hourly_term_id': str(hourly.get('id') or ''),
                'hourly_rate_raw': _money_raw(hourly.get('hourlyRate')),
                'hourly_rate_currency': _money_cur(hourly.get('hourlyRate')),
                'hourly_rate_display': (hourly.get('hourlyRate') or {}).get('displayValue') or '',
                'hourly_start_date': _date(hourly.get('startDate')),
                'hourly_end_date': _date(hourly.get('endDate')),
                'hourly_manual_time_allowed': bool(hourly.get('manualTimeAllowed')),
            })

        if fixed:
            vals.update({
                'fixed_term_id': str(fixed.get('id') or ''),
                'fp_charge_raw': _money_raw(fixed.get('fpCharge')),
                'fp_charge_currency': _money_cur(fixed.get('fpCharge')),
                'fixed_amount_raw': _money_raw(fixed.get('fixedAmount')),
                'fixed_amount_currency': _money_cur(fixed.get('fixedAmount')),
                'fixed_start_date': _date(fixed.get('startDate')),
                'fixed_end_date': _date(fixed.get('endDate')),
                'job_type': fixed.get('jobType') or '',
            })

            milestones_data = fixed.get('milestones') or []
            milestone_vals_list = []
            for ms in milestones_data:
                ms_vals = {
                    'milestone_id': str(ms.get('id') or ''),
                    'sequence_id': int(ms.get('sequenceId') or 0),
                    'state': ms.get('state') or '',
                    'description': ms.get('description') or '',
                    'due_date_time': _dt(ms.get('dueDateTime')),
                    'created_datetime': _dt(ms.get('createdDateTime')),
                    'modified_datetime': _dt(ms.get('modifiedDateTime')),
                    'submission_count': int(ms.get('submissionCount') or 0),
                    'pay_comments': ms.get('payComments') or '',
                    'instructions': ms.get('instructions') or '',
                    'escrow_raw': _money_raw(ms.get('currentEscrowAmount')),
                    'escrow_currency': _money_cur(ms.get('currentEscrowAmount')),
                    'deposit_raw': _money_raw(ms.get('depositAmount')),
                    'deposit_currency': _money_cur(ms.get('depositAmount')),
                    'funded_raw': _money_raw(ms.get('fundedAmount')),
                    'funded_currency': _money_cur(ms.get('fundedAmount')),
                    'paid_raw': _money_raw(ms.get('paid')),
                    'paid_currency': _money_cur(ms.get('paid')),
                    'overpayment_raw': _money_raw(ms.get('overpayment')),
                    'overpayment_currency': _money_cur(ms.get('overpayment')),
                    'bonus_raw': _money_raw(ms.get('bonus')),
                    'bonus_currency': _money_cur(ms.get('bonus')),
                }
                milestone_vals_list.append(ms_vals)
            vals['milestone_ids'] = milestone_vals_list

        return vals
