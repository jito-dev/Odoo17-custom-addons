# -*- coding: utf-8 -*-
import requests
import json
import logging
import base64
from pydantic import BaseModel, Field
from typing import List, Optional
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .openai_prompts import JOB_CONTEXT_EXTRACTION_PROMPT

_logger = logging.getLogger(__name__)

# --- Constants ---
HOURS_PER_WEEK = 40.0 # Assuming full-time 40 hours/week
HOURS_PER_MONTH = 160.0 # Approximation: 40 hours/week * 4 weeks
HOURS_PER_YEAR = 1920.0 # Approximation: 40 hours/week * 48 weeks (accounting for holidays)

# --- Pydantic Models ---
class ScheduleObj(BaseModel):
    timezone: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    note: Optional[str] = None

class SalaryObj(BaseModel):
    payment_type: Optional[str] = Field(description="One of: 'range_month', 'range_year', 'hourly', 'fixed_project'")
    currency: Optional[str] = Field(description="Currency code (e.g. USD, EUR). Default to USD if unclear.")
    min: Optional[float] = None
    max: Optional[float] = None
    note: Optional[str] = None

class NotesObj(BaseModel):
    english_note: Optional[str] = None
    hiring_note: Optional[str] = None
    relocation_note: Optional[str] = None
    commitment_note: Optional[str] = None

class JobContextExtraction(BaseModel):
    english_expectations: List[str] = Field(default_factory=list)
    hiring_reasons: List[str] = Field(default_factory=list)
    schedule: Optional[ScheduleObj] = None
    relocation: List[str] = Field(default_factory=list)
    workplace_type: Optional[str] = None
    workplace_note: Optional[str] = None
    other_conditions: Optional[str] = None
    salary: Optional[SalaryObj] = None
    commitment: List[str] = Field(default_factory=list)
    notes: Optional[NotesObj] = None


class HrJobNoteLine(models.Model):
    """ 
    Stores individual note lines for specific job context categories. 
    This allows for structured note-taking in the wizard (One2many) rather than a single text block.
    """
    _name = 'hr.job.note.line'
    _description = 'Job Context Note Line'
    _order = 'sequence, id'

    job_id = fields.Many2one('hr.job', string="Job", required=True, ondelete='cascade')
    sequence = fields.Integer("Sequence", default=10)
    content = fields.Char("Content", required=True)
    
    note_type = fields.Selection([
        ('english', 'English Expectations'),
        ('hiring', 'Why Hiring'),
        ('relocation', 'Relocation'),
        ('commitment', 'Commitment'),
        ('workplace', 'Workplace'),
        ('schedule', 'Schedule'),
        ('salary', 'Salary'),
    ], string="Note Category", required=True)


class HrJob(models.Model):
    _inherit = 'hr.job'

    # --- Job Context Fields ---

    # 1. English Expectations
    english_expectation_ids = fields.Many2many(
        'hr.job.english.level', string="English Expectations")
    # Computed flag for UI icon
    has_english_note = fields.Boolean(compute='_compute_has_notes')

    # 2. Why Hiring
    hiring_reason_ids = fields.Many2many(
        'hr.job.hiring.reason', string="Why Hiring")
    has_hiring_note = fields.Boolean(compute='_compute_has_notes')

    # 3. Schedule
    schedule_timezone = fields.Char("Timezone")
    schedule_start = fields.Float("Start Time")
    schedule_end = fields.Float("End Time")
    has_schedule_note = fields.Boolean(compute='_compute_has_notes')

    # 4. Relocation
    relocation_ids = fields.Many2many(
        'hr.job.relocation.status', string="Relocation Needed")
    has_relocation_note = fields.Boolean(compute='_compute_has_notes')

    # 5. Workplace
    workplace_type = fields.Selection([
        ('remote', 'Remote'),
        ('office', 'Office'),
        ('hybrid', 'Hybrid')
    ], string="Workplace Type")
    has_workplace_note = fields.Boolean(compute='_compute_has_notes')

    # 6. Other
    other_conditions = fields.Text("Other Conditions")

    # --- 7. Salary Section (Redesigned) ---
    
    # 7.1 Currency Configuration
    salary_currency_mode = fields.Selection([
        ('fiat', 'Fiat'),
        ('crypto', 'Crypto')
    ], string="Currency Type", default='fiat')

    salary_fiat_currency_id = fields.Many2one(
        'res.currency', string="Fiat Currency", 
        default=lambda self: self.env.company.currency_id
    )
    salary_crypto_currency = fields.Selection([
        ('USDT', 'USDT'),
        ('USDC', 'USDC'),
        ('EURC', 'EURC'),
        ('ETH', 'ETH'),
        ('BTC', 'BTC'),
    ], string="Crypto Currency")

    display_currency_label = fields.Char(
        string="Currency Label",
        compute="_compute_display_currency_label"
    )

    # 7.2 Compensation Type
    salary_compensation_type = fields.Selection([
        ('per_project', 'Per Project'),
        ('based_on_time', 'Based on Time'),
    ], string="Compensation", default='based_on_time')

    # 7.3 Per Project Fields
    salary_project_budget = fields.Float("Project Budget")
    
    # 7.4 Based on Time Fields (Hourly/Weekly/Monthly/Yearly)
    
    salary_hourly_min = fields.Float("Hourly Min")
    salary_hourly_max = fields.Float("Hourly Max")
    
    salary_weekly_min = fields.Float("Weekly Min")
    salary_weekly_max = fields.Float("Weekly Max")
    
    salary_monthly_min = fields.Float("Monthly Min")
    salary_monthly_max = fields.Float("Monthly Max")
    
    salary_yearly_min = fields.Float("Yearly Min")
    salary_yearly_max = fields.Float("Yearly Max")

    # 7.5 Meta info
    salary_extracted_period = fields.Selection([
        ('hourly', 'Hourly'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
        ('project', 'Project'),
    ], string="Extracted Period", help="Used to highlight the row extracted from AI")
    
    has_salary_note = fields.Boolean(compute='_compute_has_notes')

    # --- 8. Commitment ---
    commitment_ids = fields.Many2many(
        'hr.job.commitment', string="Commitment Expectation")
    has_commitment_note = fields.Boolean(compute='_compute_has_notes')

    # --- Notes (One2many Storage) ---
    job_note_ids = fields.One2many('hr.job.note.line', 'job_id', string="Context Notes")

    # --- Action Fields ---
    fireflies_meeting_link = fields.Char(
        string="Fireflies Link",
        help="Paste a Fireflies meeting link or ID here."
    )
    
    # State tracking for Async Job
    context_extract_state = fields.Selection(
        selection=[
            ('idle', 'Idle'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('error', 'Error'),
        ],
        string="Context Extract State",
        default='idle',
        copy=False
    )
    context_extract_status = fields.Text(
        string="Context Extract Status",
        readonly=True,
        copy=False
    )

    # --- Compute Methods ---

    @api.depends('job_note_ids')
    def _compute_has_notes(self):
        """
        Computes boolean flags indicating if specific sections have existing notes.
        Used to control the visibility of the 'Has Note' icon in the view.
        """
        for job in self:
            notes = job.job_note_ids
            job.has_english_note = any(n.note_type == 'english' for n in notes)
            job.has_hiring_note = any(n.note_type == 'hiring' for n in notes)
            job.has_relocation_note = any(n.note_type == 'relocation' for n in notes)
            job.has_commitment_note = any(n.note_type == 'commitment' for n in notes)
            job.has_workplace_note = any(n.note_type == 'workplace' for n in notes)
            job.has_schedule_note = any(n.note_type == 'schedule' for n in notes)
            job.has_salary_note = any(n.note_type == 'salary' for n in notes)

    @api.depends('salary_currency_mode', 'salary_fiat_currency_id', 'salary_crypto_currency')
    def _compute_display_currency_label(self):
        """
        Computes the currency label (e.g., 'USD', 'BTC') for display in salary calculation rows.
        """
        for job in self:
            if job.salary_currency_mode == 'crypto':
                job.display_currency_label = job.salary_crypto_currency or ''
            else:
                job.display_currency_label = job.salary_fiat_currency_id.name or 'USD'

    # --- Salary Onchange Methods ---
    
    def _validate_non_negative(self, value, field_name):
        """
        Helper method to check for negative values.
        Returns a warning dictionary compatible with Odoo's onchange return format if invalid.
        """
        if value < 0:
             return {
                'warning': {
                    'title': _("Invalid Value"),
                    'message': _("%s cannot be negative. The value has been reverted.") % field_name
                }
            }
        return None

    @api.onchange('salary_hourly_min')
    def _onchange_hourly_min(self):
        """
        Updates Weekly, Monthly, and Yearly Min salaries when Hourly Min changes.
        Reverts value if negative.
        """
        if self.salary_hourly_min < 0:
            old_val = self._origin.salary_hourly_min if self._origin else 0.0
            self.salary_hourly_min = old_val
            return self._validate_non_negative(-1, "Hourly Min")

        self.salary_weekly_min = self.salary_hourly_min * HOURS_PER_WEEK
        self.salary_monthly_min = self.salary_hourly_min * HOURS_PER_MONTH
        self.salary_yearly_min = self.salary_hourly_min * HOURS_PER_YEAR

    @api.onchange('salary_hourly_max')
    def _onchange_hourly_max(self):
        """
        Updates Weekly, Monthly, and Yearly Max salaries when Hourly Max changes.
        Reverts value if negative.
        """
        if self.salary_hourly_max < 0:
            old_val = self._origin.salary_hourly_max if self._origin else 0.0
            self.salary_hourly_max = old_val
            return self._validate_non_negative(-1, "Hourly Max")

        self.salary_weekly_max = self.salary_hourly_max * HOURS_PER_WEEK
        self.salary_monthly_max = self.salary_hourly_max * HOURS_PER_MONTH
        self.salary_yearly_max = self.salary_hourly_max * HOURS_PER_YEAR

    @api.onchange('salary_weekly_min')
    def _onchange_weekly_min(self):
        """
        Updates Hourly, Monthly, and Yearly Min salaries when Weekly Min changes.
        Reverts value if negative.
        """
        if self.salary_weekly_min < 0:
            old_val = self._origin.salary_weekly_min if self._origin else 0.0
            self.salary_weekly_min = old_val
            return self._validate_non_negative(-1, "Weekly Min")

        hourly = self.salary_weekly_min / HOURS_PER_WEEK
        self.salary_hourly_min = hourly
        self.salary_monthly_min = hourly * HOURS_PER_MONTH
        self.salary_yearly_min = hourly * HOURS_PER_YEAR

    @api.onchange('salary_weekly_max')
    def _onchange_weekly_max(self):
        """
        Updates Hourly, Monthly, and Yearly Max salaries when Weekly Max changes.
        Reverts value if negative.
        """
        if self.salary_weekly_max < 0:
            old_val = self._origin.salary_weekly_max if self._origin else 0.0
            self.salary_weekly_max = old_val
            return self._validate_non_negative(-1, "Weekly Max")

        hourly = self.salary_weekly_max / HOURS_PER_WEEK
        self.salary_hourly_max = hourly
        self.salary_monthly_max = hourly * HOURS_PER_MONTH
        self.salary_yearly_max = hourly * HOURS_PER_YEAR

    @api.onchange('salary_monthly_min')
    def _onchange_monthly_min(self):
        """
        Updates Hourly, Weekly, and Yearly Min salaries when Monthly Min changes.
        Reverts value if negative.
        """
        if self.salary_monthly_min < 0:
            old_val = self._origin.salary_monthly_min if self._origin else 0.0
            self.salary_monthly_min = old_val
            return self._validate_non_negative(-1, "Monthly Min")

        hourly = self.salary_monthly_min / HOURS_PER_MONTH
        self.salary_hourly_min = hourly
        self.salary_weekly_min = hourly * HOURS_PER_WEEK
        self.salary_yearly_min = hourly * HOURS_PER_YEAR

    @api.onchange('salary_monthly_max')
    def _onchange_monthly_max(self):
        """
        Updates Hourly, Weekly, and Yearly Max salaries when Monthly Max changes.
        Reverts value if negative.
        """
        if self.salary_monthly_max < 0:
            old_val = self._origin.salary_monthly_max if self._origin else 0.0
            self.salary_monthly_max = old_val
            return self._validate_non_negative(-1, "Monthly Max")

        hourly = self.salary_monthly_max / HOURS_PER_MONTH
        self.salary_hourly_max = hourly
        self.salary_weekly_max = hourly * HOURS_PER_WEEK
        self.salary_yearly_max = hourly * HOURS_PER_YEAR

    @api.onchange('salary_yearly_min')
    def _onchange_yearly_min(self):
        """
        Updates Hourly, Weekly, and Monthly Min salaries when Yearly Min changes.
        Reverts value if negative.
        """
        if self.salary_yearly_min < 0:
            old_val = self._origin.salary_yearly_min if self._origin else 0.0
            self.salary_yearly_min = old_val
            return self._validate_non_negative(-1, "Yearly Min")

        hourly = self.salary_yearly_min / HOURS_PER_YEAR
        self.salary_hourly_min = hourly
        self.salary_weekly_min = hourly * HOURS_PER_WEEK
        self.salary_monthly_min = hourly * HOURS_PER_MONTH

    @api.onchange('salary_yearly_max')
    def _onchange_yearly_max(self):
        """
        Updates Hourly, Weekly, and Monthly Max salaries when Yearly Max changes.
        Reverts value if negative.
        """
        if self.salary_yearly_max < 0:
            old_val = self._origin.salary_yearly_max if self._origin else 0.0
            self.salary_yearly_max = old_val
            return self._validate_non_negative(-1, "Yearly Max")

        hourly = self.salary_yearly_max / HOURS_PER_YEAR
        self.salary_hourly_max = hourly
        self.salary_weekly_max = hourly * HOURS_PER_WEEK
        self.salary_monthly_max = hourly * HOURS_PER_MONTH
        
    @api.onchange('salary_project_budget')
    def _onchange_project_budget(self):
        """
        Validates the Project Budget field.
        Reverts value if negative.
        """
        check = self._check_negative(self.salary_project_budget, 'Project Budget')
        if check:
            self.salary_project_budget = check['value']
            return check['warning']

    @api.constrains('salary_hourly_min', 'salary_hourly_max', 'salary_project_budget')
    def _check_salary_positivity(self):
        """
        Backend constraint to ensure salary values are not negative when saving the record.
        """
        for record in self:
            if (record.salary_hourly_min < 0 or record.salary_hourly_max < 0 or
                record.salary_weekly_min < 0 or record.salary_weekly_max < 0 or
                record.salary_monthly_min < 0 or record.salary_monthly_max < 0 or
                record.salary_yearly_min < 0 or record.salary_yearly_max < 0 or
                record.salary_project_budget < 0):
                raise ValidationError(_("Salary values cannot be negative."))

    # --- Actions ---

    def action_open_note_wizard(self):
        """ 
        Opens the generic note wizard (`hr.job.note.wizard`) for a specific category.
        This allows the user to add/edit lines of notes (e.g., 'English Expectations').
        
        Context arguments:
        - note_type: The category key (e.g., 'english', 'hiring').
        - note_label: The display label for the wizard title.
        """
        self.ensure_one()
        # Context must contain 'note_type' and 'note_label'
        note_type = self.env.context.get('note_type')
        note_label = self.env.context.get('note_label')
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Edit Notes: %s', note_label),
            'res_model': 'hr.job.note.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_job_id': self.id,
                'default_note_type': note_type,
                'default_note_label': note_label,
            }
        }

    def action_fill_context_from_file(self):
        """ 
        Button Action: Initiates background extraction of Job Context from the attached JD file.
        Sets state to 'processing' and triggers the queue job.
        """
        self.ensure_one()
        if not self.job_description_attachment_ids:
            raise UserError(_("Please upload a Job Description file first."))
        
        attachment = self.job_description_attachment_ids[0]
        
        # Set state to processing
        self.write({
            'context_extract_state': 'processing',
            'context_extract_status': _("Processing: Reading JD File with OpenAI..."),
        })
        
        # Trigger Background Job
        self.with_delay()._run_context_extraction_job(self.env.user.id, attachment.id)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Processing Started'),
                'message': _('Job Context extraction started in background.'),
                'type': 'info',
            }
        }

    def action_fill_context_from_fireflies(self):
        """ 
        Button Action: Initiates background extraction of Job Context from a Fireflies transcript.
        Fetches the transcript via API and then processes it with OpenAI.
        """
        self.ensure_one()
        if not self.fireflies_meeting_link:
            raise UserError(_("Please provide a Fireflies Meeting Link or ID."))
        
        # Set state to processing
        self.write({
            'context_extract_state': 'processing',
            'context_extract_status': _("Processing: Fetching Fireflies Transcript..."),
        })
        
        # Trigger Background Job
        self.with_delay()._run_fireflies_extraction_job(self.env.user.id, self.fireflies_meeting_link)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Processing Started'),
                'message': _('Fireflies transcript fetch and extraction started in background.'),
                'type': 'info',
            }
        }

    # --- Background Jobs ---

    def _run_fireflies_extraction_job(self, user_id, meeting_link):
        """ 
        Background Task: 
        1. Parses the Fireflies link to get the meeting ID.
        2. Calls Fireflies GraphQL API to fetch the transcript sentences.
        3. Joins sentences into full text.
        4. Calls `_run_context_extraction_logic` with the text content.
        """
        self.ensure_one()
        try:
            # 1. Get ID from Link
            meeting_id = meeting_link.strip()
            if 'fireflies.ai' in meeting_id:
                if '::' in meeting_id:
                    meeting_id = meeting_id.split('::')[-1]
            
            # 2. Fetch Transcript
            api_key = self.env.company.fireflies_api_key
            if not api_key:
                raise UserError(_("Fireflies API Key is not configured in Settings."))
            
            query = """
            query Transcript($id: String!) {
                transcript(id: $id) {
                    sentences {
                        text
                    }
                }
            }
            """
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}'
            }
            
            response = requests.post(
                'https://api.fireflies.ai/graphql',
                json={'query': query, 'variables': {'id': meeting_id}},
                headers=headers,
                timeout=60
            )
            response.raise_for_status()
            data = response.json()
            
            if 'errors' in data:
                raise UserError(_("Fireflies Error: %s", data['errors'][0].get('message')))
            
            transcript_data = data.get('data', {}).get('transcript', {})
            if not transcript_data:
                raise UserError(_("No transcript found for this meeting ID."))
                
            full_text = "\n".join([s['text'] for s in transcript_data.get('sentences', [])])
            
            if not full_text:
                _logger.warning("Fireflies transcript was empty for ID %s", meeting_id)

            # 3. Run Extraction using Direct Text
            self.write({'context_extract_status': _("Analyzing Transcript...")})
            self._run_context_extraction_logic(text_content=full_text)
            
            self._notify_user(user_id, {
                'title': _('Fireflies Extraction Complete'),
                'message': _('Job Context updated from Fireflies transcript.'),
                'type': 'success',
            })

        except Exception as e:
            _logger.error("Fireflies Job Failed: %s", str(e), exc_info=True)
            self.write({
                'context_extract_state': 'error',
                'context_extract_status': _("Error: %s", str(e))
            })
            self._notify_user(user_id, {
                'title': _('Fireflies Processing Failed'),
                'message': str(e),
                'type': 'warning',
                'sticky': True
            })

    def _run_context_extraction_job(self, user_id, attachment_id):
        """ 
        Background Task: 
        Wrapper that prepares the attachment object and calls the main extraction logic.
        """
        self.ensure_one()
        attachment = self.env['ir.attachment'].browse(attachment_id)
        if not attachment.exists():
            self.write({
                'context_extract_state': 'error',
                'context_extract_status': _("Error: Attachment not found.")
            })
            return

        try:
            self._run_context_extraction_logic(attachment=attachment)
            self._notify_user(user_id, {
                'title': _('JD Extraction Complete'),
                'message': _('Job Context updated from JD file.'),
                'type': 'success',
            })
        except Exception as e:
            _logger.error("JD Extraction Job Failed: %s", str(e), exc_info=True)
            self.write({
                'context_extract_state': 'error',
                'context_extract_status': _("Error: %s", str(e))
            })
            self._notify_user(user_id, {
                'title': _('Extraction Failed'),
                'message': str(e),
                'type': 'warning',
                'sticky': True
            })

    def _run_context_extraction_logic(self, attachment=None, text_content=None):
        """
        Core Logic:
        1. Calls the `hr.applicant._openai_call` method (centralized API handler).
        2. Accepts either a file attachment OR raw text content.
        3. Parses the Pydantic response and calls `_apply_context_data` to save it.
        """
        self.ensure_one()
        
        try:
            # Call the central _openai_call method which now handles both text and file inputs
            parsed_obj = self.env['hr.applicant']._openai_call(
                attachment=attachment,
                prompt=JOB_CONTEXT_EXTRACTION_PROMPT,
                text_format=JobContextExtraction,
                text_content=text_content
            )

            # Process Results
            data = parsed_obj.model_dump()
            self._apply_context_data(data)
            
            self.write({
                'context_extract_state': 'done',
                'context_extract_status': _('Extraction Successful.'),
            })
            
        except Exception as e:
            raise UserError(_("Extraction Failed: %s", str(e)))

    def _apply_context_data(self, data):
        """ 
        Maps the structured JSON data from OpenAI to the Odoo fields.
        - Finds or creates Many2many tags.
        - Calculates all salary fields based on extracted values.
        - Clears old notes and creates new `hr.job.note.line` records.
        """
        vals = {}
        
        # Helper to find/create tags
        def get_tags(model_name, names):
            ids = []
            for name in names:
                if not name: continue
                tag = self.env[model_name].search([('name', '=ilike', name)], limit=1)
                if not tag:
                    tag = self.env[model_name].create({'name': name})
                ids.append(tag.id)
            return [(6, 0, ids)]
            
        # Helper to create note lines
        def get_notes(note_content, n_type):
            if not note_content:
                return []
            # Split by newlines to create multiple lines if possible, or just one
            lines = [l.strip() for l in note_content.split('\n') if l.strip()]
            return [(0, 0, {'note_type': n_type, 'content': l}) for l in lines]

        # 1. M2M Tags
        if data.get('english_expectations'):
            vals['english_expectation_ids'] = get_tags('hr.job.english.level', data['english_expectations'])
        if data.get('hiring_reasons'):
            vals['hiring_reason_ids'] = get_tags('hr.job.hiring.reason', data['hiring_reasons'])
        if data.get('relocation'):
            vals['relocation_ids'] = get_tags('hr.job.relocation.status', data['relocation'])
        if data.get('commitment'):
            vals['commitment_ids'] = get_tags('hr.job.commitment', data['commitment'])

        # 2. Simple fields
        if data.get('workplace_type'):
            w_type = data['workplace_type'].lower()
            if 'remote' in w_type: vals['workplace_type'] = 'remote'
            elif 'hybrid' in w_type: vals['workplace_type'] = 'hybrid'
            elif 'office' in w_type: vals['workplace_type'] = 'office'
        
        if data.get('other_conditions'): vals['other_conditions'] = data['other_conditions']

        # 3. Schedule
        sched = data.get('schedule')
        if sched:
            if sched.get('timezone'): vals['schedule_timezone'] = sched['timezone']
            if sched.get('start_time'): vals['schedule_start'] = sched['start_time']
            if sched.get('end_time'): vals['schedule_end'] = sched['end_time']
            
        # 4. Salary Logic (Updated)
        sal = data.get('salary')
        if sal:
            # Detect Compensation Type & Period
            p_type = (sal.get('payment_type') or '').lower()
            
            if 'fixed' in p_type or 'project' in p_type:
                vals['salary_compensation_type'] = 'per_project'
                vals['salary_extracted_period'] = 'project'
                if sal.get('min') or sal.get('max'):
                    # Use max as budget if range provided, or min
                    vals['salary_project_budget'] = sal.get('max') or sal.get('min')
            else:
                vals['salary_compensation_type'] = 'based_on_time'
                
                # Base amounts
                s_min = sal.get('min', 0.0)
                s_max = sal.get('max', 0.0)
                
                if 'hour' in p_type:
                    vals['salary_extracted_period'] = 'hourly'
                    vals['salary_hourly_min'] = s_min
                    vals['salary_hourly_max'] = s_max
                    # Trigger calculations manually for other fields
                    vals['salary_weekly_min'] = s_min * HOURS_PER_WEEK
                    vals['salary_weekly_max'] = s_max * HOURS_PER_WEEK
                    vals['salary_monthly_min'] = s_min * HOURS_PER_MONTH
                    vals['salary_monthly_max'] = s_max * HOURS_PER_MONTH
                    vals['salary_yearly_min'] = s_min * HOURS_PER_YEAR
                    vals['salary_yearly_max'] = s_max * HOURS_PER_YEAR
                    
                elif 'year' in p_type:
                    vals['salary_extracted_period'] = 'yearly'
                    vals['salary_yearly_min'] = s_min
                    vals['salary_yearly_max'] = s_max
                    # Reverse calculate
                    vals['salary_hourly_min'] = s_min / HOURS_PER_YEAR
                    vals['salary_hourly_max'] = s_max / HOURS_PER_YEAR
                    vals['salary_weekly_min'] = vals['salary_hourly_min'] * HOURS_PER_WEEK
                    vals['salary_weekly_max'] = vals['salary_hourly_max'] * HOURS_PER_WEEK
                    vals['salary_monthly_min'] = vals['salary_hourly_min'] * HOURS_PER_MONTH
                    vals['salary_monthly_max'] = vals['salary_hourly_max'] * HOURS_PER_MONTH
                    
                else: 
                    # Default to monthly if 'range_month' or unspecified time
                    vals['salary_extracted_period'] = 'monthly'
                    vals['salary_monthly_min'] = s_min
                    vals['salary_monthly_max'] = s_max
                    # Reverse calculate
                    vals['salary_hourly_min'] = s_min / HOURS_PER_MONTH
                    vals['salary_hourly_max'] = s_max / HOURS_PER_MONTH
                    vals['salary_weekly_min'] = vals['salary_hourly_min'] * HOURS_PER_WEEK
                    vals['salary_weekly_max'] = vals['salary_hourly_max'] * HOURS_PER_WEEK
                    vals['salary_yearly_min'] = vals['salary_hourly_min'] * HOURS_PER_YEAR
                    vals['salary_yearly_max'] = vals['salary_hourly_max'] * HOURS_PER_YEAR

            # Currency Detection
            curr_code = (sal.get('currency') or 'USD').upper()
            crypto_list = ['USDT', 'USDC', 'EURC', 'ETH', 'BTC']
            if curr_code in crypto_list:
                vals['salary_currency_mode'] = 'crypto'
                vals['salary_crypto_currency'] = curr_code
            else:
                vals['salary_currency_mode'] = 'fiat'
                # Find res.currency
                currency = self.env['res.currency'].search([('name', '=', curr_code)], limit=1)
                if currency:
                    vals['salary_fiat_currency_id'] = currency.id

        # 5. Notes Handling       
        notes_to_create = []
        notes = data.get('notes')
        
        if notes:
            if notes.get('english_note'): 
                notes_to_create.extend(get_notes(notes['english_note'], 'english'))
            if notes.get('hiring_note'):
                notes_to_create.extend(get_notes(notes['hiring_note'], 'hiring'))
            if notes.get('relocation_note'):
                notes_to_create.extend(get_notes(notes['relocation_note'], 'relocation'))
            if notes.get('commitment_note'):
                notes_to_create.extend(get_notes(notes['commitment_note'], 'commitment'))
        
        if data.get('workplace_note'):
             notes_to_create.extend(get_notes(data['workplace_note'], 'workplace'))
        if sched and sched.get('note'):
             notes_to_create.extend(get_notes(sched['note'], 'schedule'))
        if sal and sal.get('note'):
             notes_to_create.extend(get_notes(sal['note'], 'salary'))

        # Apply main values
        self.write(vals)

        # Apply notes: remove old ones of these types and add new ones
        if notes_to_create:
            # Usually extraction overwrites.
            types_to_clear = set(x[2]['note_type'] for x in notes_to_create)
            
            # Find existing lines to unlink
            lines_to_delete = self.job_note_ids.filtered(lambda l: l.note_type in types_to_clear)
            if lines_to_delete:
                lines_to_delete.unlink()
            
            # Create new lines
            self.write({'job_note_ids': notes_to_create})

    def _notify_user(self, user_id, params):
        """ 
        Utility to send non-blocking notifications to the user interface.
        """
        self.env['hr.applicant']._notify_user(user_id, params)