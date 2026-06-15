# -*- coding: utf-8 -*-
"""Client billing-address enrichment from Upwork invoice PDFs.

The Upwork API has no client address, but the service-invoice PDF does. We run
the existing OpenAI extraction (`_extract_data_from_invoice_core`) at most once
per *address-less* client and write street/zip/country onto the client's partner
card (fill-empty only). Triggered by a bulk action and (optionally) automatically
during customer-invoice creation. A per-partner `upwork_address_enrich_state` flag
de-duplicates so a client is extracted only once.
"""

import logging

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UsaTransactionClientEnrichment(models.Model):
    _inherit = 'usa.transaction'

    # ── Partner lookup / gate ──────────────────────────────────────────────────

    def _find_customer_partner(self):
        """Read-only: find the client partner by company name (no create)."""
        self.ensure_one()
        Partner = self.env['res.partner']
        name = (self.assignment_company_name or '').strip()
        if not name:
            return Partner
        return Partner.search([
            ('name', '=ilike', name),
            ('company_id', 'in', [self.env.company.id, False]),
        ], limit=1) or Partner.search([
            ('name', 'ilike', name),
            ('company_id', 'in', [self.env.company.id, False]),
        ], limit=1)

    def _partner_needs_address(self, partner):
        """A client needs enrichment when it has no address at all."""
        return (not partner) or (not partner.street and not partner.country_id)

    # ── Country mapping + writing ──────────────────────────────────────────────

    def _match_country(self, value):
        """Map an extracted country name / ISO code to a res.country (or empty)."""
        value = (value or '').strip()
        Country = self.env['res.country']
        if not value:
            return Country
        return (Country.search([('code', '=ilike', value)], limit=1)
                or Country.search([('name', '=ilike', value)], limit=1)
                or Country.search([('name', 'ilike', value)], limit=1))

    def _match_state(self, country, value):
        """Map an extracted state/province (name or code) to a res.country.state."""
        value = (value or '').strip()
        States = self.env['res.country.state']
        if not value or not country:
            return States
        return (States.search(
                    [('country_id', '=', country.id), ('code', '=ilike', value)], limit=1)
                or States.search(
                    [('country_id', '=', country.id), ('name', '=ilike', value)], limit=1))

    def action_open_client_partner(self):
        """Open the client partner (customer) card for this transaction."""
        self.ensure_one()
        partner = self.customer_invoice_id.partner_id or self._find_customer_partner()
        if not partner:
            raise UserError(_("No client partner found for this transaction."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': partner.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_force_address_update(self):
        """Overwrite the client partner's address with the extracted data
        (extracting first if structured data is missing). Bypasses fill-empty."""
        self.ensure_one()
        if not self.upwork_invoice_pdf:
            raise UserError(_('No invoice PDF attached.'))
        if not self.extracted_client_street:
            extracted = self._extract_data_from_invoice_core()
            self._apply_extracted(extracted)
            self.write({'extraction_state': 'done', 'extraction_status': _('Done.')})
        partner = self._find_customer_partner() or self._find_or_create_customer_partner()
        if not partner:
            raise UserError(_('No client company name on this transaction.'))
        self._write_partner_address(partner, force=True)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Address Updated'),
                'message': _('Client address overwritten for %s.')
                % (self.assignment_company_name or self.record_id),
                'type': 'success', 'sticky': False,
            },
        }

    def _write_partner_address(self, partner, force=False):
        """Write the client partner's address fields (street / city / state / zip /
        country) from this tx's structured extracted data. By default fills only
        empty fields; force=True overwrites. Posts a provenance note, marks done."""
        self.ensure_one()
        if not partner:
            return False
        vals = {}
        street = self.extracted_client_street or self.extracted_client_address
        if street and (force or not partner.street):
            vals['street'] = street
        if self.extracted_client_city and (force or not partner.city):
            vals['city'] = self.extracted_client_city
        if self.extracted_client_zip and (force or not partner.zip):
            vals['zip'] = self.extracted_client_zip
        country = self.env['res.country']
        if self.extracted_client_country and (force or not partner.country_id):
            country = self._match_country(self.extracted_client_country)
            if country:
                vals['country_id'] = country.id
        if self.extracted_client_state and (force or not partner.state_id):
            state = self._match_state(
                country or partner.country_id, self.extracted_client_state)
            if state:
                vals['state_id'] = state.id
        if vals:
            partner.write(vals)
            partner.message_post(
                body=_("Billing address %s from Upwork invoice T%s.")
                % (_('overwritten') if force else _('filled'), self.record_id))
        partner.upwork_address_enrich_state = 'done'
        return bool(vals)

    # ── Extraction + enrichment job ────────────────────────────────────────────

    def _run_enrich_client_job(self, user_id):
        """queue_job worker: extract (if needed) then enrich the client partner."""
        self.ensure_one()
        try:
            if not self.extracted_client_street:
                # (Re)extract when structured street is missing — also upgrades old
                # "full address" extractions to the structured components.
                self.write({
                    'extraction_state': 'processing',
                    'extraction_status': _('Processing: calling OpenAI API…'),
                })
                extracted = self._extract_data_from_invoice_core()
                self._apply_extracted(extracted)
                self.write({
                    'extraction_state': 'done',
                    'extraction_status': _('Done.'),
                })
            partner = self._find_or_create_customer_partner()
            self._write_partner_address(partner)
            self._notify_user(user_id, {
                'title': _('Client Enriched'),
                'message': _('Billing address set for %s.')
                % (self.assignment_company_name or self.record_id),
                'type': 'success', 'sticky': False,
            })
        except Exception as exc:
            self.write({'extraction_state': 'failed', 'extraction_status': str(exc)[:255]})
            partner = self._find_customer_partner()
            if partner:
                partner.upwork_address_enrich_state = 'failed'
            self._notify_user(user_id, {
                'title': _('Client Enrichment Failed'),
                'message': _('Failed for %s: %s')
                % (self.assignment_company_name or self.record_id, str(exc)[:200]),
                'type': 'danger', 'sticky': True,
            })
            raise

    def _enqueue_client_enrichment(self, partner):
        """Mark the partner pending (sync — de-dups) and queue the enrich job."""
        self.ensure_one()
        if partner:
            partner.upwork_address_enrich_state = 'pending'
        self.with_delay()._run_enrich_client_job(self.env.user.id)

    # ── Bulk action ────────────────────────────────────────────────────────────

    def action_enrich_client_addresses(self):
        """Enrich client partner cards with billing address — at most one
        extraction per address-less client across the selection. Already-extracted
        clients are filled synchronously (no AI call)."""
        enriched = queued = skipped = 0
        seen = set()
        for rec in self:
            name = (rec.assignment_company_name or '').strip()
            if not name or not rec.upwork_invoice_pdf:
                skipped += 1
                continue
            key = name.lower()
            if key in seen:
                skipped += 1
                continue
            seen.add(key)

            partner = rec._find_customer_partner()
            if not rec._partner_needs_address(partner):
                skipped += 1
                continue
            if partner and partner.upwork_address_enrich_state in ('pending', 'done'):
                skipped += 1
                continue

            if rec.extracted_client_street:
                # Already structured-extracted — enrich now, no AI call
                rec._find_or_create_customer_partner()
                enriched += 1
            else:
                rec._enqueue_client_enrichment(partner)
                queued += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Enrich Client Addresses'),
                'message': _('%(e)d enriched now, %(q)d queued for extraction, %(s)d skipped '
                             '(already had an address / no PDF / duplicate client).',
                             e=enriched, q=queued, s=skipped),
                'type': 'success' if (enriched or queued) else 'info',
                'sticky': False,
            },
        }
