from odoo import fields, models


class HpcContractUaPe(models.Model):
    _inherit = 'hr.payroll.contractor.contract'

    # ── Enable Flag ────────────────────────────────────────────────────────────
    is_ukrainian_pe = fields.Boolean(
        string='Ukrainian PE Info',
        default=False,
    )

    # ── Contract Meta ──────────────────────────────────────────────────────────
    ua_contract_id = fields.Char(string='Contract №')
    ua_contract_conclusion_date = fields.Date(string='Conclusion Date')
    ua_contract_location_ua = fields.Char(string='Location (UA)', help='e.g. м. Київ')
    ua_contract_location_en = fields.Char(string='Location (EN)', help='e.g. Kyiv, Ukraine')

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
    ua_pe_address_ua = fields.Text(
        string='Registered Address (UA)',
        help='Адреса реєстрації українською. Формат: [індекс], [область], місто [місто], вул. [вулиця], буд. [будинок], кв. [квартира]. Важливо дотримуватись формату.',
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
    ua_pe_address_en = fields.Text(
        string='Registered Address (EN)',
        help='Registration address in English. Format: [building], [Street] Street, [City], [Region] region, [postal code], Ukraine. Important: follow this exact format.',
    )

    # ── Identity Document ──────────────────────────────────────────────────────
    ua_id_doc_type = fields.Selection(
        selection=[('id_card', 'ID Card'), ('paper_passport', 'Paper Passport')],
        string='Document Type',
    )
    # ID Card fields
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
    # Paper Passport fields
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

    # ── Tax & PE Register ──────────────────────────────────────────────────────
    ua_vat_itn = fields.Char(
        string='Tax ID (ІПН)',
        help='Індивідуальний Податковий Номер (ІПН). Повинно бути рівно 10 цифр.',
    )
    ua_register_extract_number = fields.Char(
        string='PE Register Extract №',
        help='Номер запису в Єдиному державному реєстрі юридичних осіб та ФОП. Повинно бути 17 і більше цифр.',
    )
    ua_register_extract_date = fields.Date(string='Extract Date')

    # ── Payment ────────────────────────────────────────────────────────────────
    ua_pay_duration = fields.Integer(string='Payment Duration (days)')
