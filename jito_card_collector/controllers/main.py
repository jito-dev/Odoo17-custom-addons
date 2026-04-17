# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request
from odoo.tools import consteq

_logger = logging.getLogger(__name__)


class CardCollectorWebsite(http.Controller):
    """Website controllers for card gallery, personal collection, and shared cards."""

    @http.route('/cards', type='http', auth='public', website=True, sitemap=True)
    def card_gallery(self, **kwargs):
        """Public gallery showing all shared cards."""
        cards = request.env['card.card'].sudo().search([
            ('is_shared', '=', True),
            ('image', '!=', False),
        ], order='create_date desc')
        return request.render('jito_card_collector.card_gallery', {
            'cards': cards,
            'page_title': 'Card Gallery',
            'is_public': True,
        })

    @http.route('/cards/my', type='http', auth='user', website=True, sitemap=False)
    def my_collection(self, **kwargs):
        """Personal collection for logged-in users with the Card Collector role."""
        # Users without the Card Collector role have no model-level access to
        # card.card — short-circuit to the public gallery instead of 500ing.
        if not request.env.user.has_group('jito_card_collector.group_card_user'):
            return request.redirect('/cards')

        cards = request.env['card.card'].search([
            ('user_id', '=', request.env.user.id),
            ('image', '!=', False),
        ], order='create_date desc')

        return request.render('jito_card_collector.card_gallery', {
            'cards': cards,
            'page_title': 'My Collection',
            'is_public': False,
            'total_count': len(cards),
        })

    @http.route('/cards/share/<int:card_id>/<string:token>',
                type='http', auth='public', website=True, sitemap=False)
    def shared_card(self, card_id, token, **kwargs):
        """Single shared card view with animated presentation."""
        card = request.env['card.card'].sudo().browse(card_id)
        if not card.exists() or not card.is_shared or not card.access_token:
            return request.redirect('/cards')
        if not consteq(token, card.access_token):
            return request.redirect('/cards')

        return request.render('jito_card_collector.shared_card_page', {
            'card': card,
        })

    @http.route('/cards/back/<int:card_id>', type='http', auth='public',
                website=True, sitemap=False)
    def card_back_image(self, card_id, **kwargs):
        """Serve the effective back image for a card.

        Resolution order:
          1. The card's own ``back_image`` (per-card override), if set.
          2. The owner's default ``card.back.image``, if set.
          3. 404 if neither is available.

        Access: a card's back is served only if the card is shared or the
        requester is its owner — this mirrors the access rules for the front.
        """
        card = request.env['card.card'].sudo().browse(card_id)
        if not card.exists():
            return request.not_found()

        user = request.env.user
        is_owner = (not user._is_public() and card.user_id.id == user.id)
        if not (card.is_shared or is_owner):
            return request.not_found()

        # Per-card override takes priority
        if card.back_image:
            stream = request.env['ir.binary']._get_image_stream_from(
                card, field_name='back_image')
            stream.public = card.is_shared
            return stream.get_response()

        # Fall back to the owner's default back
        back = request.env['card.back'].sudo().search(
            [('user_id', '=', card.user_id.id)], limit=1)
        if back and back.image:
            stream = request.env['ir.binary']._get_image_stream_from(
                back, field_name='image')
            stream.public = card.is_shared
            return stream.get_response()

        return request.not_found()
