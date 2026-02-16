# -*- coding: utf-8 -*-
from odoo import models, fields, api

class HrRecruitmentTrackingConfig(models.Model):
    _name = 'hr.recruitment.tracking.config'
    _description = 'Configuration for Custom Parameters'
    
    # The name of this record determines the Group Header in the list view (e.g. "Custom Parameters")
    name = fields.Char(default='Custom Parameters', required=True)
    # Stores the JSON schema for the dynamic properties
    properties_definition = fields.PropertiesDefinition('Properties Definition')

    @api.model
    def get_config(self):
        """ Singleton pattern to get/create the configuration record """
        config = self.search([], limit=1)
        if not config:
            config = self.create({'name': 'Custom Parameters'})
        return config


class HrTrackingParamKey(models.Model):
    _name = 'hr.tracking.param.key'
    _description = 'Tracking Parameter Key'
    _order = 'name'

    name = fields.Char(string='Parameter Name', required=True, index=True)
    value_ids = fields.One2many('hr.tracking.param.value', 'key_id', string='Allowed Values')
    
    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Parameter Key name must be unique!')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._update_definitions()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'name' in vals:
            self._update_definitions()
        return res

    def unlink(self):
        res = super().unlink()
        self._update_definitions()
        return res

    @api.model
    def _update_definitions(self):
        """
        Rebuilds the properties definition schema based on all existing keys.
        Updates the centralized config record.
        """
        keys = self.search([])
        definition = []
        for key in keys:
            definition.append({
                'name': f'param_{key.id}',  # Internal key
                'string': key.name,         # Display Label in List View
                'type': 'char',             # We store values as simple strings
            })
        
        # Update the config record using sudo to avoid permission issues for regular users
        config = self.env['hr.recruitment.tracking.config'].sudo().get_config()
        config.write({'properties_definition': definition})


class HrTrackingParamValue(models.Model):
    _name = 'hr.tracking.param.value'
    _description = 'Tracking Parameter Value'
    _order = 'name'

    name = fields.Char(string='Value', required=True, index=True)
    key_id = fields.Many2one('hr.tracking.param.key', string='Key', required=True, ondelete='cascade', help="The key this value belongs to.")
    
    _sql_constraints = [
        ('key_name_uniq', 'unique (key_id, name)', 'Value must be unique per Key!')
    ]

class HrApplicantTrackingValue(models.Model):
    _name = 'hr.applicant.tracking.value'
    _description = 'Applicant Tracking Value'
    
    applicant_id = fields.Many2one('hr.applicant', string='Applicant', required=True, ondelete='cascade')
    key_id = fields.Many2one('hr.tracking.param.key', string='Key', required=True, ondelete='restrict')
    value_id = fields.Many2one('hr.tracking.param.value', string='Value', required=True, ondelete='cascade')