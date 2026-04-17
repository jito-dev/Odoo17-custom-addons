# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .card_card import AI_STATUS_SELECTION, generate_image_with_gemini

_logger = logging.getLogger(__name__)


class CardBack(models.Model):
    """Default card-back artwork, one per user.

    Each Card Collector user has a single ``card.back`` record storing their
    preferred default back image. Individual cards can override this with their
    own ``card.card.back_image`` — otherwise every card falls back to the
    owner's default stored here.
    """
    _name = 'card.back'
    _description = 'Default Card Back (per user)'
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users', string='User', required=True, index=True,
        ondelete='cascade', default=lambda self: self.env.user)
    image = fields.Image(string='Default Back Artwork',
                         max_width=1024, max_height=1024)
    user_prompt = fields.Text(
        string='Image Prompt',
        help='Describe what the default back of your cards should look like')
    ai_generation_status = fields.Selection(
        AI_STATUS_SELECTION, string='AI Status', default='draft')

    _sql_constraints = [
        ('user_uniq', 'unique(user_id)',
         'Each user can only have one default card back.'),
    ]

    @api.model
    def _get_or_create_for_user(self, user=None):
        """Return the current user's card.back record, creating it if missing."""
        user = user or self.env.user
        back = self.search([('user_id', '=', user.id)], limit=1)
        if not back:
            back = self.create({'user_id': user.id})
        return back

    @api.model
    def action_open_current_user(self):
        """Open the current user's card.back form view (called from menu)."""
        back = self._get_or_create_for_user()
        return {
            'type': 'ir.actions.act_window',
            'name': _('My Card Back'),
            'res_model': 'card.back',
            'res_id': back.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_generate_image(self):
        """Generate the default back artwork via Google Nano Banana (Gemini)."""
        self.ensure_one()
        if not self.user_prompt:
            raise UserError(_(
                'Please enter an image prompt before generating your card back.'))

        self.ai_generation_status = 'generating'
        try:
            image_data = generate_image_with_gemini(
                self.env, self.user_prompt, is_back=True)
            self.write({
                'image': image_data,
                'ai_generation_status': 'done',
            })
        except Exception as e:
            self.ai_generation_status = 'failed'
            _logger.error(
                'Card back generation failed for user %s: %s', self.user_id.id, e)
            raise UserError(_('Back image generation failed: %s') % str(e))
