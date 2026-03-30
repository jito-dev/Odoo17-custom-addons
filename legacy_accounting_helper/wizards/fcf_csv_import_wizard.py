import base64
import csv
import hashlib
import io
import logging
import re
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Currency symbols to strip when parsing value column
CURRENCY_SYMBOLS = re.compile(r'[$€£]')

# ISIN pattern (2 letter country + 10 alphanumeric)
ISIN_RE = re.compile(r'\b([A-Z]{2}[A-Z0-9]{10})\b')

# Currency code pattern in description (e.g. "BUY USD Class R ...")
CURRENCY_CODE_RE = re.compile(r'\b(USD|EUR|GBP|CHF|PLN|CZK|SEK|NOK|DKK|HUF|RON|BGN|HRK)\b')


def _parse_date(date_str):
    """Parse date like 'Jan 2, 2025' into a datetime at noon UTC."""
    date_str = date_str.strip()
    dt = datetime.strptime(date_str, '%b %d, %Y')
    return dt.replace(hour=12, minute=0, second=0)


def _parse_value(value_str):
    """Parse value like '$-1.23' or '€5.67' into a float."""
    cleaned = CURRENCY_SYMBOLS.sub('', value_str.strip())
    cleaned = cleaned.replace(',', '')
    return float(cleaned)


def _determine_transaction_type(description):
    """Map CSV description to fcf transaction type."""
    desc_upper = description.upper().strip()
    if desc_upper.startswith('BUY'):
        return 'fcf_buy'
    if desc_upper.startswith('SELL'):
        return 'fcf_sell'
    if 'SERVICE FEE' in desc_upper:
        return 'fcf_fee'
    if 'INTEREST' in desc_upper:
        return 'fcf_interest'
    return 'fcf_buy'  # fallback


def _extract_currency(description):
    """Extract currency code from description text."""
    match = CURRENCY_CODE_RE.search(description)
    return match.group(1) if match else None


def _extract_isin(description):
    """Extract ISIN code from description if present."""
    match = ISIN_RE.search(description)
    return match.group(1) if match else None


def _generate_revolut_id(date_str, description, value_str):
    """Generate a deterministic revolut_id for deduplication."""
    key = f'{date_str}|{description}|{value_str}'
    digest = hashlib.md5(key.encode()).hexdigest()[:16]
    return f'fcf_{digest}'


class FcfCsvImportWizard(models.TransientModel):
    _name = 'fcf.csv.import.wizard'
    _description = 'Flexible Cash Funds CSV Import'

    account_map_id = fields.Many2one(
        'revolut.account.journal.map',
        string='Account Mapping',
        readonly=True,
    )
    csv_file = fields.Binary(string='CSV File', required=True)
    csv_filename = fields.Char(string='Filename')

    def action_import(self):
        """Parse CSV and create revolut.transaction records."""
        self.ensure_one()
        if not self.csv_file:
            raise UserError('Please upload a CSV file.')
        if not self.account_map_id:
            raise UserError('No account mapping selected.')

        mapping = self.account_map_id

        # Decode CSV
        try:
            raw = base64.b64decode(self.csv_file)
            text = raw.decode('utf-8-sig')  # handle BOM
        except Exception as e:
            raise UserError(f'Cannot read CSV file: {e}')

        reader = csv.DictReader(io.StringIO(text))

        # Validate columns
        expected_cols = {'Date (UTC)', 'Description', 'Value'}
        if not expected_cols.issubset(set(reader.fieldnames or [])):
            raise UserError(
                f'CSV must contain columns: {", ".join(sorted(expected_cols))}. '
                f'Found: {", ".join(reader.fieldnames or [])}'
            )

        RevTx = self.env['revolut.transaction']
        created_count = 0
        skipped_count = 0
        errors = []

        for row_num, row in enumerate(reader, start=2):
            date_str = (row.get('Date (UTC)') or '').strip()
            description = (row.get('Description') or '').strip()
            value_str = (row.get('Value') or '').strip()

            if not date_str or not description or not value_str:
                continue  # skip empty rows

            try:
                created_at = _parse_date(date_str)
                amount = _parse_value(value_str)
            except (ValueError, TypeError) as e:
                errors.append(f'Row {row_num}: {e}')
                continue

            revolut_id = _generate_revolut_id(date_str, description, value_str)

            # Check for duplicates
            existing = RevTx.search([
                ('revolut_id', '=', revolut_id),
                ('company_id', '=', mapping.company_id.id),
            ], limit=1)
            if existing:
                skipped_count += 1
                continue

            tx_type = _determine_transaction_type(description)
            currency = _extract_currency(description) or (
                mapping.currency_id.name if mapping.currency_id else 'USD'
            )
            reference = _extract_isin(description) or ''

            tx_vals = {
                'revolut_id': revolut_id,
                'company_id': mapping.company_id.id,
                'account_revolut_id': mapping.revolut_account_id,
                'account_name': mapping.revolut_account_name or mapping.revolut_account_id,
                'account_map_id': mapping.id,
                'source': 'csv',
                'transaction_type': tx_type,
                'state': 'completed',
                'created_at': created_at,
                'amount': amount,
                'currency': currency,
                'description': description,
                'reference': reference,
            }

            # FCF buy/sell are inherently internal transfers
            if tx_type in ('fcf_buy', 'fcf_sell'):
                tx_vals['transfer_between_accounts'] = True

            RevTx.create(tx_vals)
            created_count += 1

        msg_parts = [f'{created_count} transactions imported']
        if skipped_count:
            msg_parts.append(f'{skipped_count} duplicates skipped')
        if errors:
            msg_parts.append(f'{len(errors)} rows with errors')
            _logger.warning('FCF CSV import errors: %s', '; '.join(errors))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'FCF CSV Import Complete',
                'message': '. '.join(msg_parts) + '.',
                'type': 'success' if not errors else 'warning',
                'sticky': True,
            },
        }
