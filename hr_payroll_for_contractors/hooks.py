import logging
from datetime import date
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

_STALE_XML_IDS = [
    'hr_payroll_for_contractors.menu_hpc_legal_relationships',
    'hr_payroll_for_contractors.menu_hpc_invoicing_logic',
    'hr_payroll_for_contractors.menu_hpc_contract_templates',
    'hr_payroll_for_contractors.action_hpc_contract_templates',
    'hr_payroll_for_contractors.action_hpc_legal_relationship',
    'hr_payroll_for_contractors.action_hpc_invoicing_logic',
]


def post_init_hook(env):
    """Initialize the singleton settings record on first install."""
    Settings = env['hr.payroll.contractor.settings']
    companies = env['res.company'].search([])
    for company in companies:
        existing = Settings.search([('company_id', '=', company.id)], limit=1)
        if not existing:
            today = date.today()
            date_start = today.replace(day=1)
            date_end = date_start + relativedelta(months=1, days=-1)
            Settings.create({
                'company_id': company.id,
                'dashboard_date_start': date_start,
                'dashboard_date_end': date_end,
            })


def post_migrate_hook(env):
    """Combined migration hook from hr_payroll_for_contractors and hpc_contractor_info."""

    # ── 1. Migrate 'locked' state to 'approved_and_locked' ──────────────────
    env.cr.execute(
        "UPDATE hr_payroll_contractor_salary_run "
        "SET state = 'approved_and_locked' WHERE state = 'locked'"
    )

    # ── 2. Clean up stale menu items and actions ─────────────────────────────
    for xml_id in _STALE_XML_IDS:
        try:
            record = env.ref(xml_id, raise_if_not_found=False)
            if record:
                record.unlink()
                _logger.info('hr_payroll_for_contractors: removed stale record %s', xml_id)
        except Exception as e:
            _logger.warning('hr_payroll_for_contractors: could not remove %s: %s', xml_id, e)

    # ── 3. Drop stale service_agreement_id column from contract table ────────
    # The field is now a non-stored computed field; the old DB column + FK must
    # be removed to prevent the FK constraint from blocking SA deletions.
    env.cr.execute("""
        ALTER TABLE hr_payroll_contractor_contract
        DROP COLUMN IF EXISTS service_agreement_id
    """)
    _logger.info(
        'hr_payroll_for_contractors: dropped stale service_agreement_id column '
        'from hr_payroll_contractor_contract (if it existed)'
    )

    # ── 4. Populate Required Context defaults on service agreements ──────────
    agreements = env['hpc.service.agreement'].search([])
    for agreement in agreements:
        vals = {}

        if not agreement.acceptable_entity_type_ids:
            ua_pe = env.ref(
                'hr_payroll_for_contractors.entity_type_ua_pe', raise_if_not_found=False
            )
            if ua_pe:
                vals['acceptable_entity_type_ids'] = [(4, ua_pe.id)]

        if not agreement.acceptable_payment_type_ids:
            sepa = env.ref(
                'hr_payroll_for_contractors.payment_type_sepa', raise_if_not_found=False
            )
            swift = env.ref(
                'hr_payroll_for_contractors.payment_type_swift', raise_if_not_found=False
            )
            ids = [(4, r.id) for r in (sepa, swift) if r]
            if ids:
                vals['acceptable_payment_type_ids'] = ids

        if vals:
            agreement.write(vals)
            _logger.info(
                'hr_payroll_for_contractors: populated Required Context defaults on '
                'service agreement %s', agreement.agreement_category
            )
