import logging

_logger = logging.getLogger(__name__)

_STALE_XML_IDS = [
    'hpc_contractor_info.menu_hpc_legal_relationships',
    'hpc_contractor_info.menu_hpc_invoicing_logic',
    'hpc_contractor_info.menu_hpc_contract_templates',
    'hpc_contractor_info.action_hpc_contract_templates',
    'hpc_contractor_info.action_hpc_legal_relationship',
    'hpc_contractor_info.action_hpc_invoicing_logic',
]


def post_migrate_hook(env):
    """Populate Required Context defaults on existing hpc.service.agreement records
    that have empty acceptable_entity_type_ids or acceptable_payment_type_ids.
    Also cleans up stale menu/action records from removed features."""

    # ── Clean up stale menu items and actions ───────────────────────────────
    for xml_id in _STALE_XML_IDS:
        try:
            record = env.ref(xml_id, raise_if_not_found=False)
            if record:
                record.unlink()
                _logger.info('hpc_contractor_info: removed stale record %s', xml_id)
        except Exception as e:
            _logger.warning('hpc_contractor_info: could not remove %s: %s', xml_id, e)

    # ── Drop stale service_agreement_id column from contract table ──────────
    # The field is now a non-stored computed field; the old DB column + FK must
    # be removed to prevent the FK constraint from blocking SA deletions.
    env.cr.execute("""
        ALTER TABLE hr_payroll_contractor_contract
        DROP COLUMN IF EXISTS service_agreement_id
    """)
    _logger.info(
        'hpc_contractor_info: dropped stale service_agreement_id column '
        'from hr_payroll_contractor_contract (if it existed)'
    )

    # ── Populate Required Context defaults ──────────────────────────────────
    agreements = env['hpc.service.agreement'].search([])
    for agreement in agreements:
        vals = {}

        if not agreement.acceptable_entity_type_ids:
            ua_pe = env.ref(
                'hpc_contractor_info.entity_type_ua_pe', raise_if_not_found=False
            )
            if ua_pe:
                vals['acceptable_entity_type_ids'] = [(4, ua_pe.id)]

        if not agreement.acceptable_payment_type_ids:
            sepa = env.ref(
                'hpc_contractor_info.payment_type_sepa', raise_if_not_found=False
            )
            swift = env.ref(
                'hpc_contractor_info.payment_type_swift', raise_if_not_found=False
            )
            ids = [(4, r.id) for r in (sepa, swift) if r]
            if ids:
                vals['acceptable_payment_type_ids'] = ids

        if vals:
            agreement.write(vals)
            _logger.info(
                'hpc_contractor_info: populated Required Context defaults on '
                'service agreement %s', agreement.agreement_category
            )
