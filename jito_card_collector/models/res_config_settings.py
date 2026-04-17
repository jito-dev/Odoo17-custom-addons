# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    card_collector_api_key = fields.Char(
        string='Google AI API Key',
        config_parameter='card_collector.api_key',
        help='API key for Google Gemini (Nano Banana) image generation')

    card_collector_master_prompt = fields.Char(
        string='Master Style Prompt',
        config_parameter='card_collector.master_prompt',
        help='This prompt is prepended to every card image generation '
             'to ensure a consistent art style across all cards')

    card_collector_model = fields.Selection(
        [
            ('gemini-2.5-flash-image', 'Nano Banana (Fast)'),
            ('gemini-3.1-flash-image-preview', 'Nano Banana 2 (Higher Quality)'),
            ('gemini-3-pro-image-preview', 'Nano Banana Pro (Best Quality)'),
        ],
        string='AI Model',
        config_parameter='card_collector.model',
        default='gemini-2.5-flash-image',
        help='Select which Google Nano Banana model to use for image generation')
