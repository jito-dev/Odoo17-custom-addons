# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class RecruitmentTrackerController(http.Controller):

    @http.route('/t/<string:token>', type='http', auth='public', website=True)
    def tracker_redirect(self, token, **kwargs):
        tracker_sudo = request.env['hr.recruitment.tracker'].sudo().search([('token', '=', token)], limit=1)

        if not tracker_sudo:
            return request.not_found()

        if not tracker_sudo.active:
            return request.render('http_routing.404')
        
        if tracker_sudo.expires_at and tracker_sudo.expires_at < fields.Datetime.now():
            return "This link has expired."

        if tracker_sudo.max_uses > 0 and tracker_sudo.use_count >= tracker_sudo.max_uses:
            return "This link has reached its maximum usage limit."

        vals = {
            'use_count': tracker_sudo.use_count + 1,
            'last_used_at': fields.Datetime.now(),
            'last_used_ip': request.httprequest.remote_addr,
            'last_used_user_agent': request.httprequest.user_agent.string,
        }
        tracker_sudo.write(vals)

        target_url = tracker_sudo.target_url
        if not target_url:
            return request.not_found()
            
        response = request.redirect(target_url, code=301, local=False)

        max_age = 30 * 24 * 60 * 60 # 30 days
        
        def set_tracker_cookie(key, value):
            if key and value:
                response.set_cookie(key, value, max_age=max_age, path='/')

        set_tracker_cookie('hr_recruitment_tracker_token', token)

        if tracker_sudo.campaign_id:
            set_tracker_cookie('odoo_utm_campaign', tracker_sudo.campaign_id.name)
            
        if tracker_sudo.source_id:
            set_tracker_cookie('odoo_utm_source', tracker_sudo.source_id.name)
            
        if tracker_sudo.medium_id:
            set_tracker_cookie('odoo_utm_medium', tracker_sudo.medium_id.name)

        # Updated to use new relational fields from the tracker
        for param in tracker_sudo.param_ids:
            key_name = param.key_id.name
            value_name = param.value_id.name
            
            key_clean = key_name.strip().lower().replace(' ', '_')
            cookie_name = f'odoo_utm_{key_clean}'
            set_tracker_cookie(cookie_name, value_name)

        return response