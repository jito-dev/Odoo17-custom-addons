# -*- coding: utf-8 -*-
import base64
import logging
import uuid

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

AI_STATUS_SELECTION = [
    ('draft', 'Draft'),
    ('generating', 'Generating'),
    ('done', 'Done'),
    ('failed', 'Failed'),
]

# Default master prompt for card back artwork — used when the system parameter
# card_collector.back_master_prompt is not set.
DEFAULT_BACK_MASTER_PROMPT = (
    "Generate a trading card BACK design: ornate symmetrical pattern or emblem, "
    "no human characters, no text, no borders, rich detail, consistent art style "
    "suitable for the reverse side of a collectible card. Square aspect ratio."
)


def generate_image_with_gemini(env, user_prompt, is_back=False):
    """Call Google Nano Banana (Gemini) and return base64-encoded image bytes.

    Shared by `card.card` (front/back) and `card.back` (per-user default back).

    :param env: Odoo environment
    :param user_prompt: the user-supplied description
    :param is_back: when True, use the back-specific master prompt
    """
    try:
        from google import genai
    except ImportError:
        raise UserError(_(
            'The google-genai Python package is not installed. '
            'Run: pip install google-genai'))

    ICP = env['ir.config_parameter'].sudo()
    api_key = ICP.get_param('card_collector.api_key', '')
    if not api_key:
        raise UserError(_(
            'Google AI API key is not configured. '
            'Go to Settings > Card Collector to set it up.'))

    model_name = ICP.get_param('card_collector.model', 'gemini-2.5-flash-image')

    if is_back:
        master_prompt = ICP.get_param(
            'card_collector.back_master_prompt', DEFAULT_BACK_MASTER_PROMPT)
    else:
        master_prompt = ICP.get_param(
            'card_collector.master_prompt',
            'Generate a trading card illustration in a consistent fantasy-anime art style.')

    full_prompt = '%s\n\n%s' % (master_prompt, user_prompt)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=full_prompt,
        config=genai.types.GenerateContentConfig(
            response_modalities=['TEXT', 'IMAGE'],
        ),
    )

    for part in response.parts:
        if part.inline_data is not None:
            return base64.b64encode(part.inline_data.data)

    raise UserError(_('The AI model did not return an image. Try a different prompt.'))


class CardCard(models.Model):
    _name = 'card.card'
    _description = 'Collectible Card'
    _order = 'create_date desc'

    name = fields.Char(string='Card Title', required=True)
    description = fields.Text(string='Card Description')
    image = fields.Image(string='Card Artwork', max_width=1024, max_height=1024)
    user_prompt = fields.Text(string='Image Prompt',
                              help='Describe what the card artwork should look like')
    user_id = fields.Many2one('res.users', string='Owner',
                              default=lambda self: self.env.user,
                              required=True, index=True)
    ai_generation_status = fields.Selection(AI_STATUS_SELECTION,
                                            string='AI Status',
                                            default='draft')

    # --- Per-card back image (optional override of the user's default back) ---
    back_image = fields.Image(string='Card Back Artwork',
                              max_width=1024, max_height=1024,
                              help='Optional. If set, overrides your default card back for this card.')
    back_user_prompt = fields.Text(string='Back Image Prompt',
                                   help='Describe what the back of this card should look like')
    back_ai_status = fields.Selection(AI_STATUS_SELECTION,
                                      string='Back AI Status',
                                      default='draft')

    is_shared = fields.Boolean(string='Shared', default=False)
    access_token = fields.Char(string='Access Token', copy=False, index=True,
                                default=lambda self: str(uuid.uuid4()))
    # Non-stored: recomputed live from web.base.url on every read so shared links
    # always use the instance's current domain (never a stale value from a DB restore).
    share_url = fields.Char(string='Share URL', compute='_compute_share_url')

    @api.depends('is_shared', 'access_token')
    def _compute_share_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for card in self:
            if card.is_shared and card.access_token:
                card.share_url = '%s/cards/share/%s/%s' % (
                    base_url, card.id, card.access_token)
            else:
                card.share_url = False

    def action_toggle_share(self):
        """Toggle card sharing on/off."""
        self.ensure_one()
        if not self.access_token:
            self.access_token = str(uuid.uuid4())
        self.is_shared = not self.is_shared

    def action_generate_image(self):
        """Generate the FRONT artwork using Google Nano Banana (Gemini) API."""
        self.ensure_one()
        if not self.user_prompt:
            raise UserError(_('Please enter an image prompt before generating artwork.'))

        front_prompt = 'Card Title: %s\nCard Description: %s' % (
            self.name, self.user_prompt)

        self.ai_generation_status = 'generating'
        try:
            image_data = generate_image_with_gemini(self.env, front_prompt, is_back=False)
            self.write({
                'image': image_data,
                'ai_generation_status': 'done',
            })
        except Exception as e:
            self.ai_generation_status = 'failed'
            _logger.error('Card front generation failed for card %s: %s', self.id, e)
            raise UserError(_('Image generation failed: %s') % str(e))

    def action_generate_back_image(self):
        """Generate a per-card BACK image using Google Nano Banana (Gemini) API."""
        self.ensure_one()
        if not self.back_user_prompt:
            raise UserError(_('Please enter a back image prompt before generating artwork.'))

        self.back_ai_status = 'generating'
        try:
            image_data = generate_image_with_gemini(self.env, self.back_user_prompt, is_back=True)
            self.write({
                'back_image': image_data,
                'back_ai_status': 'done',
            })
        except Exception as e:
            self.back_ai_status = 'failed'
            _logger.error('Card back generation failed for card %s: %s', self.id, e)
            raise UserError(_('Back image generation failed: %s') % str(e))

    def action_clear_back_image(self):
        """Remove per-card back override so the card falls back to the user default."""
        self.ensure_one()
        self.write({
            'back_image': False,
            'back_ai_status': 'draft',
        })
