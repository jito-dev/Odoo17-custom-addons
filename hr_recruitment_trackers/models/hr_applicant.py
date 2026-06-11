# -*- coding: utf-8 -*-
import logging
from lxml import etree
from odoo import models, fields, api, tools
from odoo.http import request

_logger = logging.getLogger(__name__)

class Applicant(models.Model):
    _inherit = "hr.applicant"

    tracker_id = fields.Many2one('hr.recruitment.tracker', string="Source Tracker", help="The link tracker used to generate this application.")

    tracking_value_ids = fields.One2many('hr.applicant.tracking.value', 'applicant_id', string='Custom Parameters List')

    # -------------------------------------------------------------------------
    # CANDIDATE ORIGIN
    # A coarse 3-way *provenance* of the record (how it entered the system),
    # deliberately distinct from the marketing UTM `source_id` (which stays
    # Djinni / LinkedIn / Facebook / …). Computed & stored from signals that are
    # set once at create and never change afterwards, so it is correct both for
    # new records and retroactively for existing ones on upgrade.
    # -------------------------------------------------------------------------
    applicant_origin = fields.Selection(
        selection=[
            ('djinni', 'Djinni Integration'),
            ('tracking_link', 'Tracking Link'),
            ('manual', 'Manually Added'),
        ],
        string="Candidate Source",
        compute='_compute_applicant_origin',
        store=True,
        index=True,
        help="How this candidate entered the system: imported by the Djinni "
             "integration, captured via a tracking link, or added manually. "
             "Independent from the marketing Source (UTM).",
    )

    @api.depends('tracker_id')
    def _compute_applicant_origin(self):
        # `djinni_ref` is contributed by the hr_djinni module. Guard on its
        # presence so this stays a *soft* dependency — trackers keeps working
        # (no candidate is ever classified as Djinni) when hr_djinni is absent.
        # Both `tracker_id` and `djinni_ref` are set once at create and never
        # change, so depending on `tracker_id` alone is enough: stored computed
        # fields are always evaluated on create regardless of the trigger set.
        has_djinni = 'djinni_ref' in self._fields
        for applicant in self:
            if applicant.tracker_id:
                applicant.applicant_origin = 'tracking_link'
            elif has_djinni and applicant.djinni_ref:
                applicant.applicant_origin = 'djinni'
            else:
                applicant.applicant_origin = 'manual'

    def _get_default_tracking_config(self):
        return self.env['hr.recruitment.tracking.config'].sudo().get_config().id

    # Link to the configuration record that holds the definition.
    # We use a default to ensure it's set on creation, which is critical for the properties to work immediately.
    tracking_config_id = fields.Many2one(
        'hr.recruitment.tracking.config', 
        string="Tracking Config",
        default=_get_default_tracking_config,
        compute='_compute_tracking_config_id',
        store=True
    )

    # The dynamic properties field
    tracker_properties = fields.Properties(
        'Custom Parameters',
        definition='tracking_config_id.properties_definition',
        copy=True,
        compute='_compute_tracker_properties',
        store=True,
        readonly=False
    )

    # New: Static field for grouping/searching
    tracker_properties_text = fields.Char(
        string="Tracking Properties (Text)",
        compute='_compute_tracker_properties_text',
        store=True
    )

    @api.depends('tracker_properties')
    def _compute_tracker_properties_text(self):
        for applicant in self:
            # Convert properties dict to readable string
            if applicant.tracker_properties:
                props_list = [f"{k}: {v}" for k, v in applicant.tracker_properties.items()]
                applicant.tracker_properties_text = " | ".join(props_list)
            else:
                applicant.tracker_properties_text = ""

    # -------------------------------------------------------------------------
    # GROUPING SLOTS (15 Slots Pre-allocated) - not best practice but necessary for grouping in Odoo's current architecture
    # -------------------------------------------------------------------------
    tracker_group_1 = fields.Char(string="Custom Group 1", compute='_compute_tracker_groups', store=True)
    tracker_group_2 = fields.Char(string="Custom Group 2", compute='_compute_tracker_groups', store=True)
    tracker_group_3 = fields.Char(string="Custom Group 3", compute='_compute_tracker_groups', store=True)
    tracker_group_4 = fields.Char(string="Custom Group 4", compute='_compute_tracker_groups', store=True)
    tracker_group_5 = fields.Char(string="Custom Group 5", compute='_compute_tracker_groups', store=True)
    tracker_group_6 = fields.Char(string="Custom Group 6", compute='_compute_tracker_groups', store=True)
    tracker_group_7 = fields.Char(string="Custom Group 7", compute='_compute_tracker_groups', store=True)
    tracker_group_8 = fields.Char(string="Custom Group 8", compute='_compute_tracker_groups', store=True)
    tracker_group_9 = fields.Char(string="Custom Group 9", compute='_compute_tracker_groups', store=True)
    tracker_group_10 = fields.Char(string="Custom Group 10", compute='_compute_tracker_groups', store=True)
    tracker_group_11 = fields.Char(string="Custom Group 11", compute='_compute_tracker_groups', store=True)
    tracker_group_12 = fields.Char(string="Custom Group 12", compute='_compute_tracker_groups', store=True)
    tracker_group_13 = fields.Char(string="Custom Group 13", compute='_compute_tracker_groups', store=True)
    tracker_group_14 = fields.Char(string="Custom Group 14", compute='_compute_tracker_groups', store=True)
    tracker_group_15 = fields.Char(string="Custom Group 15", compute='_compute_tracker_groups', store=True)

    @api.depends('tracking_value_ids', 'tracking_value_ids.key_id', 'tracking_value_ids.value_id')
    def _compute_tracker_groups(self):
        SLOT_COUNT = 15
        # Fetch keys. If none exist (e.g. fresh install), this list is empty.
        # We ensure order is consistent (ID ascending) so a param always maps to the same slot.
        keys = self.env['hr.tracking.param.key'].search([], order='id asc')
        key_slot_map = {k.id: i for i, k in enumerate(keys) if i < SLOT_COUNT}

        for applicant in self:
            slots = [''] * SLOT_COUNT
            for val in applicant.tracking_value_ids:
                if val.key_id.id in key_slot_map:
                    slot_index = key_slot_map[val.key_id.id]
                    slots[slot_index] = val.value_id.name or ''
            
            for i in range(SLOT_COUNT):
                applicant[f'tracker_group_{i+1}'] = slots[i]

    # -------------------------------------------------------------------------
    # DYNAMIC VIEW MANIPULATION
    # -------------------------------------------------------------------------
    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        """
        Dynamically handles Custom Parameter placement in the Search View.
        1. Renames slots (tracker_group_X) to real names (e.g. 'Location').
        2. Hides unused slots from 'Add Custom Group'.
        3. Creates a dedicated 'Tracker Parameters' section in the Group By dropdown.
        """
        res = super().get_view(view_id, view_type, **options)
        
        if view_type == 'search':
            _logger.info("[TRACKER DEBUG] Processing get_view for Search View with Slots")
            try:
                SLOT_COUNT = 15
                ParamKey = self.env['hr.tracking.param.key'].sudo()
                
                # Fetch existing keys (might be empty after reinstall)
                keys = []
                if tools.table_exists(self.env.cr, ParamKey._table):
                    keys = ParamKey.search([], order='id asc', limit=SLOT_COUNT)

                if 'fields' not in res:
                    res['fields'] = {}
                else:
                    res['fields'] = res['fields'].copy()

                # Fetch definitions for ALL 15 slots so we can modify them
                all_slot_names = [f"tracker_group_{i+1}" for i in range(SLOT_COUNT)]
                slot_fields_def = self.sudo().fields_get(all_slot_names)

                doc = etree.XML(res['arch'])
                
                # Ensure 'tracker_properties' exists (for text search safety)
                if not doc.xpath("//field[@name='tracker_properties']"):
                    doc.insert(0, etree.Element('field', name='tracker_properties'))

                search_node = doc.xpath("//search")[0]
                
                # Prepare the "Tracker Parameters" group node
                tracker_group_node = None
                
                # We use 'group_tracker_properties_text' as our anchor to place the new group
                anchor_nodes = doc.xpath("//filter[@name='group_tracker_properties_text']")
                if not anchor_nodes:
                    # Fallback anchor if the text filter is missing
                    anchor_nodes = doc.xpath("//filter[@name='group_medium_id']")

                # Only create the group if we actually have keys to put in it
                if anchor_nodes and keys:
                    anchor_node = anchor_nodes[0]
                    parent_group = anchor_node.getparent()
                    
                    if parent_group is not None and parent_group.tag == 'group':
                        # Create a NEW Group for separation
                        tracker_group_node = etree.Element('group', string="Tracker Parameters", expand="0")
                        # Insert after the parent group (separating it from standard Odoo groups)
                        parent_group.addnext(tracker_group_node)

                # Loop through ALL 15 slots
                for i in range(SLOT_COUNT):
                    slot_field = f"tracker_group_{i+1}"
                    
                    if slot_field in slot_fields_def:
                        field_def = slot_fields_def[slot_field].copy()
                        
                        # 1. ALWAYS HIDE from 'Add Custom Group' dropdown to prevent clutter
                        field_def['groupable'] = False 
                        
                        if i < len(keys):
                            # ACTIVE SLOT: Rename to real key name (e.g., "Location")
                            field_def['string'] = keys[i].name
                            
                            # Inject Invisible Field into Arch (Required for client to know the field exists)
                            if not doc.xpath(f"//field[@name='{slot_field}']"):
                                search_node.insert(0, etree.Element('field', name=slot_field, invisible="1"))
                            
                            # Add specific filter to our new Custom Group
                            if tracker_group_node is not None:
                                context_str = "{'group_by': '%s'}" % slot_field
                                new_filter = etree.Element(
                                    'filter', 
                                    string=keys[i].name, 
                                    name=f"group_dynamic_slot_{i+1}", 
                                    context=context_str
                                )
                                tracker_group_node.append(new_filter)
                        else:
                            # INACTIVE SLOT: Rename to 'Unused' and ensure hidden
                            field_def['string'] = f"Unused Slot {i+1}"
                            field_def['searchable'] = False

                        res['fields'][slot_field] = field_def

                res['arch'] = etree.tostring(doc, encoding='unicode')

            except Exception as e:
                _logger.error("[TRACKER DEBUG] Failed to inject dynamic tracking filters: %s", e)
            
        return res

    @api.depends('company_id') # Trigger on any change to ensure it's set
    def _compute_tracking_config_id(self):
        # Always set to the singleton config
        config_id = self._get_default_tracking_config()
        for applicant in self:
            if not applicant.tracking_config_id:
                applicant.tracking_config_id = config_id

    @api.depends('tracking_value_ids', 'tracking_value_ids.key_id', 'tracking_value_ids.value_id')
    def _compute_tracker_properties(self):
        for applicant in self:
            properties = {}
            # Populate properties from existing tracking_value_ids
            # This ensures that if you have existing data, it fills the columns
            for tracking_val in applicant.tracking_value_ids:
                if tracking_val.key_id and tracking_val.value_id:
                    # Use 'param_<id>' to match the schema defined in hr_tracking_param.py
                    properties[f'param_{tracking_val.key_id.id}'] = tracking_val.value_id.name
            
            applicant.tracker_properties = properties

    @api.model_create_multi
    def create(self, vals_list):
        req = request
        cookies = {}
        
        # PREVENT COOKIE POISONING: 
        # Backend manual creates use JSON-RPC (application/json)
        # Website forms use standard HTTP POST. We only apply cookies if it is NOT a JSON-RPC request.
        if req and hasattr(req, 'httprequest'):
            if req.httprequest.mimetype != 'application/json':
                cookies = req.httprequest.cookies
        
        tracker_token = cookies.get('hr_recruitment_tracker_token')
        Tracker = self.env['hr.recruitment.tracker'].sudo()
        tracker = Tracker.search([('token', '=', tracker_token)], limit=1) if tracker_token else None
        
        standard_utms = ['utm_campaign', 'utm_source', 'utm_medium']

        ParamKey = self.env['hr.tracking.param.key'].sudo()
        ParamValue = self.env['hr.tracking.param.value'].sudo()

        # Ensure config is fetched once
        default_config_id = self._get_default_tracking_config()

        for vals in vals_list:
            captured_params = {}

            # 1. Try to get params from the Tracker
            if tracker:
                # IMPORTANT: Map the tracker and standard UTM fields to the applicant
                vals['tracker_id'] = tracker.id
                
                if tracker.campaign_id and 'campaign_id' not in vals:
                    vals['campaign_id'] = tracker.campaign_id.id
                if tracker.source_id and 'source_id' not in vals:
                    vals['source_id'] = tracker.source_id.id
                if tracker.medium_id and 'medium_id' not in vals:
                    vals['medium_id'] = tracker.medium_id.id

                for param in tracker.param_ids:
                    if param.key_id and param.value_id:
                        captured_params[param.key_id.name] = param.value_id.name
            
            # 2. Fallback to Cookies if no tracker
            elif not tracker:
                for cookie_key, cookie_val in cookies.items():
                    if cookie_key.startswith('odoo_utm_') and cookie_key not in standard_utms:
                        label = cookie_key.replace('odoo_utm_', '').replace('_', ' ').strip().title()
                        captured_params[label] = cookie_val

            if captured_params:
                tracking_values = []
                properties = {}
                
                for label, value in captured_params.items():
                    # Find or Create Key
                    key_rec = ParamKey.search([('name', '=ilike', label)], limit=1)
                    if not key_rec:
                        key_rec = ParamKey.create({'name': label})
                    
                    # Find or Create Value
                    val_rec = ParamValue.search([('name', '=ilike', value), ('key_id', '=', key_rec.id)], limit=1)
                    if not val_rec:
                        val_rec = ParamValue.create({'name': value, 'key_id': key_rec.id})

                    # Add to One2many
                    tracking_values.append((0, 0, {
                        'key_id': key_rec.id,
                        'value_id': val_rec.id
                    }))

                    # Prepare Properties dictionary
                    properties[f'param_{key_rec.id}'] = value
                
                vals['tracking_value_ids'] = tracking_values
                
                # Explicitly set properties on create to ensure columns are populated immediately
                vals['tracker_properties'] = properties
            
            # Ensure tracking config is linked
            if 'tracking_config_id' not in vals:
                vals['tracking_config_id'] = default_config_id

        return super(Applicant, self).create(vals_list)