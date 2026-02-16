from odoo import api, SUPERUSER_ID

def pre_init_hook(env):
    """
    Remove the External IDs (XML IDs) of the stages that were previously 
    defined in data/stage_data.xml. This prevents Odoo from attempting 
    to delete these stages (and failing due to FK constraints) now that 
    we have removed the XML file to manage them dynamically in Python.
    """
    xml_ids_to_remove = [
        'hr_recruitment_test_task.stage_test_given',
        'hr_recruitment_test_task.stage_test_submitted',
        'hr_recruitment_test_task.stage_ai_analysis',
    ]
    
    IrModelData = env['ir.model.data']
    for xml_id in xml_ids_to_remove:
        try:
            module, name = xml_id.split('.')
            imd = IrModelData.search([('module', '=', module), ('name', '=', name)], limit=1)
            if imd:
                imd.unlink()
        except Exception:
            pass