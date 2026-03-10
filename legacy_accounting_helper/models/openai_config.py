import json
import logging
import urllib.error
import urllib.request

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

OPENAI_MODELS_ENDPOINT = 'https://api.openai.com/v1/models'
OPENAI_CHAT_ENDPOINT = 'https://api.openai.com/v1/chat/completions'

MODEL_SELECTION = [
    ('gpt-4o', 'GPT-4o'),
    ('gpt-4o-mini', 'GPT-4o mini'),
    ('gpt-4-turbo', 'GPT-4 Turbo'),
    ('gpt-4', 'GPT-4'),
    ('gpt-3.5-turbo', 'GPT-3.5 Turbo'),
    ('o1', 'o1'),
    ('o1-mini', 'o1-mini'),
    ('o3-mini', 'o3-mini'),
]

CONNECTION_STATUS_SELECTION = [
    ('untested', 'Not Tested'),
    ('ok', 'Connected'),
    ('failed', 'Failed'),
]


class OpenAIConfig(models.Model):
    _name = 'openai.config'
    _description = 'OpenAI API Configuration'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    api_key = fields.Char(
        string='API Key',
        copy=False,
        help='Your OpenAI API key (starts with sk-…)',
    )
    model_name = fields.Selection(
        MODEL_SELECTION,
        string='Default Model',
        default='gpt-4o-mini',
        required=True,
    )
    connection_status = fields.Selection(
        CONNECTION_STATUS_SELECTION,
        string='Connection Status',
        default='untested',
        readonly=True,
    )
    test_result = fields.Text(
        string='Last Test Result',
        readonly=True,
    )

    _sql_constraints = [
        (
            'openai_config_company_uniq',
            'unique(company_id)',
            'An OpenAI configuration already exists for this company.',
        ),
    ]

    @api.model
    def action_open_config(self):
        """Get or create the singleton config for the current company and open it."""
        if not self.env.user.has_group('legacy_accounting_helper.group_revolut_admin'):
            raise UserError(
                "You need Revolut Business API Integration / Administrator access "
                "to open this configuration page."
            )
        config = self.sudo().search([('company_id', '=', self.env.company.id)], limit=1)
        if not config:
            config = self.sudo().create({'company_id': self.env.company.id})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': config.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def _get_headers(self):
        self.ensure_one()
        key = (self.api_key or '').strip()
        if not key:
            raise UserError(
                'No API key configured. Please enter your OpenAI API key and save first.'
            )
        return {
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
        }

    def action_test_connection(self):
        """Verify the API key by listing available models and running a minimal chat call."""
        self.ensure_one()
        headers = self._get_headers()

        # Step 1 — list models (confirms key is valid + has access)
        req = urllib.request.Request(OPENAI_MODELS_ENDPOINT, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                msg = json.loads(body).get('error', {}).get('message', body)
            except Exception:
                msg = body[:300]
            self.write({
                'connection_status': 'failed',
                'test_result': f'HTTP {e.code}: {msg}',
            })
            return False
        except Exception as e:
            self.write({
                'connection_status': 'failed',
                'test_result': f'Request failed: {e}',
            })
            return False

        model_ids = [m.get('id', '') for m in data.get('data', [])]
        model_count = len(model_ids)

        # Step 2 — minimal chat completion with the configured model
        chat_payload = json.dumps({
            'model': self.model_name,
            'messages': [{'role': 'user', 'content': 'Reply with the single word: OK'}],
            'max_tokens': 5,
        }).encode()
        chat_req = urllib.request.Request(
            OPENAI_CHAT_ENDPOINT,
            data=chat_payload,
            headers=headers,
            method='POST',
        )
        chat_reply = ''
        try:
            with urllib.request.urlopen(chat_req, timeout=20) as resp:
                chat_data = json.loads(resp.read().decode())
            chat_reply = (
                chat_data.get('choices', [{}])[0]
                .get('message', {})
                .get('content', '')
                .strip()
            )
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                msg = json.loads(body).get('error', {}).get('message', body)
            except Exception:
                msg = body[:300]
            # Key is valid (Step 1 passed) but model may be unavailable — still report
            chat_reply = f'Chat test failed (HTTP {e.code}): {msg}'
        except Exception as e:
            chat_reply = f'Chat test failed: {e}'

        result_lines = [
            f'API key: valid',
            f'Models available: {model_count}',
            f'Model "{self.model_name}" response: {chat_reply}',
        ]
        self.write({
            'connection_status': 'ok',
            'test_result': '\n'.join(result_lines),
        })
        return False
