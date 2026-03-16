import json
import logging
import urllib.error
import urllib.request

from odoo import api, fields, models, _
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


class UsaOpenAIConfig(models.Model):
    """Singleton: OpenAI API configuration for this Upwork module."""

    _name = 'usa.openai.config'
    _description = 'OpenAI API Configuration'

    lock_field = fields.Char(default='global', copy=False)

    api_key = fields.Char(
        string='API Key',
        copy=False,
        help='Your OpenAI API key (starts with sk-…)',
    )
    model_name = fields.Selection(
        MODEL_SELECTION,
        string='Model',
        default='gpt-4o',
        required=True,
    )
    connection_status = fields.Selection(
        [('untested', 'Not Tested'), ('ok', 'Connected'), ('failed', 'Failed')],
        string='Connection Status',
        default='untested',
        readonly=True,
    )
    test_result = fields.Text(string='Last Test Result', readonly=True)

    _sql_constraints = [
        (
            'singleton',
            'UNIQUE(lock_field)',
            'Only one OpenAI configuration record is allowed.',
        ),
    ]

    @api.model
    def _get_singleton(self):
        rec = self.sudo().search([], limit=1)
        return rec or self.sudo().create({})

    @api.model
    def action_open(self):
        """Open the singleton form view."""
        rec = self._get_singleton()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': rec.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def _get_headers(self):
        """Return Authorization headers for OpenAI API requests."""
        self.ensure_one()
        key = (self.api_key or '').strip()
        if not key:
            raise UserError(_(
                'No OpenAI API key configured. '
                'Please enter your API key in Configuration → OpenAI Configuration.'
            ))
        return {
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
        }

    def action_test_connection(self):
        """Verify the API key by listing models and running a minimal chat call."""
        self.ensure_one()
        headers = self._get_headers()

        # Step 1 — list models (confirms key is valid)
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
            self.write({'connection_status': 'failed', 'test_result': f'HTTP {e.code}: {msg}'})
            return False
        except Exception as e:
            self.write({'connection_status': 'failed', 'test_result': f'Request failed: {e}'})
            return False

        model_count = len(data.get('data', []))

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
            chat_reply = f'Chat test failed (HTTP {e.code}): {msg}'
        except Exception as e:
            chat_reply = f'Chat test failed: {e}'

        result_lines = [
            'API key: valid',
            f'Models available: {model_count}',
            f'Model "{self.model_name}" response: {chat_reply}',
        ]
        self.write({'connection_status': 'ok', 'test_result': '\n'.join(result_lines)})
        return False
