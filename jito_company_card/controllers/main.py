import base64

from odoo import http
from odoo.http import request
from werkzeug.exceptions import NotFound


class CompanyCardController(http.Controller):

    def _get_published_company(self, token):
        """Look up a published company by its share token."""
        return request.env['res.company'].sudo().search([
            ('card_share_token', '=', token),
            ('card_published', '=', True),
        ], limit=1)

    @http.route(
        '/company/card/<string:token>',
        type='http',
        auth='public',
        website=True,
        sitemap=False,
    )
    def company_card(self, token, **kwargs):
        company = self._get_published_company(token)
        if not company:
            raise NotFound()

        # Build concatenated legal address
        address_parts = [
            company.street,
            company.street2,
            company.city,
            company.state_id.name if company.state_id else None,
            company.zip,
            company.country_id.name if company.country_id else None,
        ]
        legal_address = ', '.join(part for part in address_parts if part)

        representative = company.hpc_representative_id
        director_email = representative.email if representative else None
        director_name = representative.name if representative else None
        director_has_photo = bool(representative and representative.image_512)
        director_title = (
            representative.function if representative else None
        )

        # Build "copy all" text block
        copy_all_parts = [company.name or '']
        if legal_address:
            copy_all_parts.append(f'Address: {legal_address}')
        if company.website:
            copy_all_parts.append(f'Website: {company.website}')
        if company.vat:
            copy_all_parts.append(f'VAT: {company.vat}')
        if director_name:
            copy_all_parts.append(f'Representative: {director_name}')
        if director_email:
            copy_all_parts.append(f'Email: {director_email}')
        if company.card_registration_number:
            copy_all_parts.append(
                f'Registration Number: {company.card_registration_number}')
        if company.card_registration_date:
            copy_all_parts.append(
                f'Registration Date: {company.card_registration_date}')
        copy_all_text = '\n'.join(copy_all_parts)

        registration_date_formatted = None
        if company.card_registration_date:
            registration_date_formatted = company.card_registration_date.strftime('%d %B %Y')

        values = {
            'company': company,
            'legal_address': legal_address,
            'director_email': director_email,
            'director_name': director_name,
            'director_has_photo': director_has_photo,
            'director_title': director_title,
            'token': token,
            'copy_all_text': copy_all_text,
            'registration_date_formatted': registration_date_formatted,
            'no_header': company.card_hide_header_footer,
            'no_footer': company.card_hide_header_footer,
        }
        return request.render('jito_company_card.company_card_page', values)

    @http.route(
        '/company/card/<string:token>/representative.png',
        type='http',
        auth='public',
        sitemap=False,
    )
    def company_card_representative_photo(self, token, **kwargs):
        """Serve the representative's photo publicly via the card token."""
        company = self._get_published_company(token)
        if not company or not company.hpc_representative_id:
            raise NotFound()

        image_data = company.hpc_representative_id.image_512
        if not image_data:
            raise NotFound()

        return request.make_response(
            base64.b64decode(image_data),
            headers=[
                ('Content-Type', 'image/png'),
                ('Cache-Control', 'public, max-age=3600'),
            ],
        )
