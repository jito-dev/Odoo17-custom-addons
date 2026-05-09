from odoo import api, fields, models


class HpcContractorLegalEntity(models.Model):
    _name = 'hpc.contractor.legal.entity'
    _description = 'Contractor Legal Entity'
    _order = 'contractor_id, entity_type'

    contractor_id = fields.Many2one(
        'hpc.contractor',
        string='Contractor',
        required=True,
        ondelete='cascade',
    )
    entity_type = fields.Selection(
        selection=[
            ('ua_pe', 'Ukrainian Private Entrepreneur'),
            ('ca_sp', 'Canadian Sole Proprietor'),
            ('individual', 'Individual'),
        ],
        string='Entity Type',
        required=True,
        default='ua_pe',
    )
    display_name = fields.Char(
        compute='_compute_display_name',
        store=True,
    )

    # ── Contract Meta ──────────────────────────────────────────────────────────
    ua_contract_id = fields.Char(string='Contract №')
    ua_contract_conclusion_date = fields.Date(string='Conclusion Date')
    ua_contract_location_ua = fields.Char(string='Location (UA)', help='e.g. м. Київ')
    ua_contract_location_en = fields.Char(string='Location (EN)', help='e.g. Kyiv, Ukraine')
    ua_pay_duration = fields.Integer(string='Payment Duration (days)')

    # ── Personal Info — Ukrainian ──────────────────────────────────────────────
    ua_pe_sex = fields.Selection(
        selection=[('male', 'Male'), ('female', 'Female')],
        string='Sex',
    )
    ua_pe_last_name_ua = fields.Char(
        string='Last Name (UA)',
        help='Прізвище як у паспорті, українською мовою.',
    )
    ua_pe_first_name_ua = fields.Char(
        string='First Name (UA)',
        help="Ім'я як у паспорті, українською мовою.",
    )
    ua_pe_by_father_ua = fields.Char(
        string='Patronymic (UA)',
        help='По батькові українською мовою.',
    )

    # ── Registered Address — Ukrainian ────────────────────────────────────────
    ua_pe_addr_country_id = fields.Many2one(
        'res.country',
        string='Country',
        default=lambda self: self.env.ref('base.ua', raise_if_not_found=False),
        readonly=True,
        ondelete='restrict',
    )
    ua_pe_addr_state_ua = fields.Char(string='Region (UA)', help='e.g. Дніпропетровська область')
    ua_pe_addr_city_ua = fields.Char(string='City (UA)', help='e.g. місто Дніпро')
    ua_pe_addr_street1_ua = fields.Char(string='Street Address Line 1 (UA)', help='e.g. вул. Українська, буд. 1a, кв. 1')
    ua_pe_addr_street2_ua = fields.Char(string='Street Address Line 2 (UA)')
    ua_pe_addr_postal_code = fields.Char(string='Postal Code', help='e.g. 49000')

    # Computed concatenation for use in document templates
    ua_pe_address_ua = fields.Text(
        string='Registered Address (UA)',
        compute='_compute_ua_pe_address_ua',
        store=True,
    )

    # ── Personal Info — English ────────────────────────────────────────────────
    ua_pe_last_name_en = fields.Char(
        string='Last Name (EN)',
        help='Last name as written in the passport in English.',
    )
    ua_pe_first_name_en = fields.Char(
        string='First Name (EN)',
        help='First name as written in the passport in English.',
    )

    # ── Registered Address — English ──────────────────────────────────────────
    ua_pe_addr_state_en = fields.Char(string='Region (EN)', help='e.g. Dnipropetrovsk region')
    ua_pe_addr_city_en = fields.Char(string='City (EN)', help='e.g. Dnipro')
    ua_pe_addr_street1_en = fields.Char(string='Street Address Line 1 (EN)', help='e.g. 1a, Ukrayin\'ska Street')
    ua_pe_addr_street2_en = fields.Char(string='Street Address Line 2 (EN)')

    # Computed concatenation for use in document templates
    ua_pe_address_en = fields.Text(
        string='Registered Address (EN)',
        compute='_compute_ua_pe_address_en',
        store=True,
    )

    # ── Identity Document ──────────────────────────────────────────────────────
    ua_id_doc_type = fields.Selection(
        selection=[
            ('id_card', 'ID Card'),
            ('paper_passport', 'Paper Passport'),
            ('international_passport', 'International Passport'),
        ],
        string='Identity Document Type',
        default='id_card',
        required=True,
    )
    # ID Card
    ua_id_card_number = fields.Char(
        string='ID Card №',
        help='Номер паспорту ID-картки. Повинно бути 9 цифр.',
    )
    ua_id_card_record_number = fields.Char(
        string='Record № (РНОКПП)',
        help='Номер запису РНОКПП. Формат: XXXXXXXX-XXXXX (8 цифр, дефіс, 5 цифр).',
    )
    ua_id_card_date_of_issue = fields.Date(string='Date of Issue')
    ua_id_card_authority = fields.Char(
        string='Issued By',
        help='4-значний код органу, що видав ID-картку.',
    )
    ua_id_card_front_photo = fields.Binary(
        string='Photo/Scan — Front Side (Full Name)',
        attachment=True,
        help='Photo or scan of the front side of the ID card showing the full name (ПІБ).',
    )
    ua_id_card_front_photo_filename = fields.Char()
    ua_id_card_back_photo = fields.Binary(
        string='Photo/Scan — Back Side (Issuing Authority)',
        attachment=True,
        help='Photo or scan of the back side of the ID card showing the issuing authority.',
    )
    ua_id_card_back_photo_filename = fields.Char()

    # Paper Passport
    ua_passport_series = fields.Char(
        string='Passport Series',
        help='Серія та номер паспорта-книжки. Перші дві букви — латиницею, далі 6 цифр.',
    )
    ua_passport_authority = fields.Char(
        string='Issued By',
        help='Орган, що видав паспорт, українською мовою.',
    )
    ua_passport_date_of_issue = fields.Date(string='Date of Issue')
    ua_passport_name_page_photo = fields.Binary(
        string='Photo — Page with Full Name',
        attachment=True,
        help='Photo of the passport page showing the full name (ПІБ).',
    )
    ua_passport_name_page_photo_filename = fields.Char()
    ua_passport_authority_page_photo = fields.Binary(
        string='Photo — Page with Issuing Authority',
        attachment=True,
        help='Photo of the passport page showing the issuing authority.',
    )
    ua_passport_authority_page_photo_filename = fields.Char()

    # International Passport
    intl_passport_number = fields.Char(string='Document Number')
    intl_passport_first_name = fields.Char(string='First Name')
    intl_passport_last_name = fields.Char(string='Last Name')
    intl_passport_nationality_id = fields.Many2one(
        'res.country', string='Nationality', ondelete='restrict')
    intl_passport_date_of_birth = fields.Date(string='Date of Birth')
    intl_passport_sex = fields.Selection(
        selection=[('male', 'Male'), ('female', 'Female')],
        string='Sex',
    )
    intl_passport_place_of_birth = fields.Char(string='Place of Birth')
    intl_passport_date_of_issue = fields.Date(string='Date of Issue')
    intl_passport_date_of_expiry = fields.Date(string='Date of Expiry')
    intl_passport_authority = fields.Char(string='Authority')
    intl_passport_photo = fields.Binary(
        string='Passport Photo',
        attachment=True,
    )
    intl_passport_photo_filename = fields.Char()

    # ── Canadian Sole Proprietor ──────────────────────────────────────────────
    # Personal info + business identifiers + principal address. Reuses the
    # intl_passport_* fields above for the Identity Document section (only
    # International Passport is supported for now).

    ca_sp_first_name = fields.Char(
        string='First Name',
        help='Sole proprietor first name. e.g. John.',
    )
    ca_sp_last_name = fields.Char(
        string='Last Name',
        help='Sole proprietor last name. e.g. Doe.',
    )
    ca_sp_business_name = fields.Char(
        string='Business Name',
        help='Registered business name. e.g. JOHN DOE.',
    )
    ca_sp_business_id_number = fields.Char(
        string='Business Identification Number',
        help='Provincial / municipal business identification number. e.g. 1000654321.',
    )
    ca_sp_tax_id_number = fields.Char(
        string='Tax Identification Number',
        help='Personal Social Insurance Number or equivalent tax ID. e.g. 123-456-789.',
    )
    ca_sp_principal_address = fields.Text(
        string='Address of Principal Place of Business',
        help='Full registered address. e.g. 123-456 Johnathan Street, '
             'Vancouver, BC, Canada, AB1 CD4.',
    )
    ca_sp_federal_business_number = fields.Char(
        string='Federal Business Number (BN)',
        help='CRA-assigned 9-digit Business Number. e.g. 123456789.',
    )

    # Identity Document type for Canadian Sole Proprietor — only the
    # International Passport option is supported for now. Kept as a Selection
    # so future doc types can be added without a schema change.
    ca_sp_id_doc_type = fields.Selection(
        selection=[
            ('international_passport', 'International Passport'),
        ],
        string='Identity Document Type',
        default='international_passport',
    )

    # ── Tax & PE Register ──────────────────────────────────────────────────────
    ua_vat_itn = fields.Char(
        string='Tax ID (ІПН)',
        help='Індивідуальний Податковий Номер (ІПН). Повинно бути рівно 10 цифр.',
    )
    ua_register_extract_number = fields.Char(
        string='PE Register Extract №',
        help='[Дані з єдиного державного реєстру юридичних осіб та фізичних осіб підприємців]\n'
             'Наприклад: 22240000000133274\n'
             'Повинно бути 17+ цифр\n'
             'Якщо, поки що нема — пропуск',
    )
    ua_register_extract_date = fields.Date(
        string='Extract Date',
        help='[Дані з єдиного державного реєстру юридичних осіб та фізичних осіб підприємців]\n'
             'Якщо, поки що нема — пропуск',
    )

    # ── Computed addresses ─────────────────────────────────────────────────────

    @api.depends(
        'ua_pe_addr_postal_code', 'ua_pe_addr_state_ua',
        'ua_pe_addr_city_ua', 'ua_pe_addr_street1_ua', 'ua_pe_addr_street2_ua',
    )
    def _compute_ua_pe_address_ua(self):
        for rec in self:
            parts = filter(None, [
                rec.ua_pe_addr_postal_code,
                rec.ua_pe_addr_state_ua,
                rec.ua_pe_addr_city_ua,
                rec.ua_pe_addr_street1_ua,
                rec.ua_pe_addr_street2_ua,
                'Україна',
            ])
            rec.ua_pe_address_ua = ', '.join(parts)

    @api.depends(
        'ua_pe_addr_street1_en', 'ua_pe_addr_street2_en',
        'ua_pe_addr_city_en', 'ua_pe_addr_state_en', 'ua_pe_addr_postal_code',
    )
    def _compute_ua_pe_address_en(self):
        for rec in self:
            parts = filter(None, [
                rec.ua_pe_addr_street1_en,
                rec.ua_pe_addr_street2_en,
                rec.ua_pe_addr_city_en,
                rec.ua_pe_addr_state_en,
                rec.ua_pe_addr_postal_code,
                'Ukraine',
            ])
            rec.ua_pe_address_en = ', '.join(parts)

    @api.depends('entity_type', 'contractor_id', 'contractor_id.employee_id.name')
    def _compute_display_name(self):
        labels = {
            'ua_pe': 'Ukrainian PE',
            'ca_sp': 'Canadian Sole Proprietor',
            'individual': 'Individual',
        }
        for rec in self:
            entity_label = labels.get(rec.entity_type, rec.entity_type or '')
            employee_name = rec.contractor_id.employee_id.name or ''
            rec.display_name = f"{entity_label} — {employee_name}" if employee_name else entity_label
