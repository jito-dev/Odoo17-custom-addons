# -*- coding: utf-8 -*-
import logging
import odoo
from typing import List
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from pydantic import BaseModel, Field

from odoo.addons.hr_recruitment_extract_openai.models.openai_prompts import (
    OPENAI_CV_EXTRACTION_PROMPT,
    JD_EXTRACT_SINGLE_PROMPT,
)

_logger = logging.getLogger(__name__)

# --- Pydantic Models for JD Extraction ---

class JDRequirement(BaseModel):
    """Pydantic model for a single job requirement."""
    name: str = Field(description="The specific, measurable requirement.")
    weight: float = Field(description="Importance weight from 1.0 (low) to 10.0 (critical).")
    tag_name: str = Field(description="Category: 'Hard Skill', 'Soft Skill', 'Domain Knowledge', or 'Operational'.")

class JDRequirementList(BaseModel):
    """Pydantic model to wrap the list of requirements."""
    requirements: List[JDRequirement] = Field(description="A list of all extracted job requirements.")

class HrJob(models.Model):
    _inherit = 'hr.job'

    # --- 1. Fields for Bulk CV Upload ---
    cv_attachment_ids = fields.Many2many(
        'ir.attachment',
        'hr_job_cv_attachment_rel',
        'job_id',
        'attachment_id',
        string='CVs to Process',
        help="Upload multiple CVs here to create applicants in bulk."
    )
    processed_cv_attachment_ids = fields.Many2many(
        'ir.attachment',
        'hr_job_cv_attachment_processed_rel',
        'job_id',
        'attachment_id',
        string='Successfully Processed CVs',
        copy=False,
        readonly=True,
    )
    
    processed_cv_count = fields.Integer(string="Processed Count", readonly=True, copy=False, default=0)
    failed_cv_count = fields.Integer(string="Failed Count", readonly=True, copy=False, default=0)
    total_cv_count = fields.Integer(string="Total to Process", readonly=True, copy=False, default=0)

    # Logic field: Determines if AI match runs after extraction.
    # This will be hidden in the view as per request.
    run_ai_match_on_bulk = fields.Boolean(
        string="Run AI Match",
        default=False,
        help="If selected, the system will automatically run the AI Match process."
    )

    bulk_queue_job_uuid = fields.Char(string="Bulk CV Job UUID", copy=False, readonly=True)
    bulk_job_state = fields.Selection(
        [('pending', 'Pending'), ('enqueued', 'Enqueued'), ('started', 'Started'), ('done', 'Done'), ('failed', 'Failed')],
        string='Bulk Job State',
        compute='_compute_bulk_job_state',
        store=False,
        readonly=True
    )
    bulk_processing_in_progress = fields.Boolean(compute="_compute_bulk_processing_in_progress")
    bulk_processing_complete = fields.Boolean(default=False, copy=False)
    bulk_processing_failed = fields.Boolean(default=False, copy=False)
    bulk_processing_progress = fields.Integer(compute='_compute_bulk_processing_progress')

    # --- 2. Fields for JD Parsing & AI Match ---
    job_description_attachment_ids = fields.Many2many(
        'ir.attachment',
        'hr_job_jd_attachment_rel',
        'job_id',
        'attachment_id',
        string="Job Description File"
    )
    ai_match_mode = fields.Selection(
        selection=[
            ('single_prompt', 'Single Prompt (Fast)'),
            ('multi_prompt', 'Multi-Prompt (Detailed)'),
        ],
        string="Applicant Match Mode",
        default='single_prompt',
        required=True,
    )
    
    jd_extract_state = fields.Selection(
        selection=[
            ('no_extract', 'Not Extracted'),
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('error', 'Error'),
        ],
        string='JD Extract State',
        default='no_extract',
        required=True,
        copy=False,
    )
    jd_extract_status = fields.Text(string="JD Extract Status", readonly=True, copy=False)
    jd_processed_attachment_ids = fields.Many2many('ir.attachment', string="Processed JD File", readonly=True)
    
    jd_queue_job_uuid = fields.Char(string="JD Job UUID", copy=False, readonly=True)
    jd_job_state = fields.Selection(
        [('pending', 'Pending'), ('enqueued', 'Enqueued'), ('started', 'Started'), ('done', 'Done'), ('failed', 'Failed')],
        compute='_compute_jd_job_state',
        readonly=True
    )
    jd_processing_in_progress = fields.Boolean(compute="_compute_jd_processing_in_progress")
    
    requirement_statement_ids = fields.One2many('hr.job.requirement', 'job_id', string='Job Requirement Statements')

    # --- Compute Methods ---

    @api.depends('processed_cv_count', 'failed_cv_count', 'total_cv_count')
    def _compute_bulk_processing_progress(self):
        for job in self:
            if job.total_cv_count > 0:
                total = job.processed_cv_count + job.failed_cv_count
                job.bulk_processing_progress = (total * 100) / job.total_cv_count
            else:
                job.bulk_processing_progress = 0

    @api.depends('bulk_queue_job_uuid')
    def _compute_bulk_job_state(self):
        for job in self:
            if job.bulk_queue_job_uuid:
                job_record = self.env['queue.job'].sudo().search([('uuid', '=', job.bulk_queue_job_uuid)], limit=1)
                job.bulk_job_state = job_record.state if job_record else False
            else:
                job.bulk_job_state = False

    @api.depends('bulk_job_state')
    def _compute_bulk_processing_in_progress(self):
        for job in self:
            job.bulk_processing_in_progress = job.bulk_job_state in ('pending', 'enqueued', 'started')

    @api.depends('jd_queue_job_uuid')
    def _compute_jd_job_state(self):
        for job in self:
            if job.jd_queue_job_uuid:
                job_record = self.env['queue.job'].sudo().search([('uuid', '=', job.jd_queue_job_uuid)], limit=1)
                job.jd_job_state = job_record.state if job_record else False
            else:
                job.jd_job_state = False

    @api.depends('jd_job_state')
    def _compute_jd_processing_in_progress(self):
        for job in self:
            job.jd_processing_in_progress = job.jd_job_state in ('pending', 'enqueued', 'started')

    # --- Actions: Bulk CV ---

    def action_process_cvs(self):
        self.ensure_one()
        try:
            self.env.cr.execute('SELECT * FROM hr_job WHERE id = %s FOR UPDATE NOWAIT', (self.id,), log_exceptions=False)
            job = self.browse(self.id)
            
            if job.bulk_processing_in_progress:
                raise UserError(_("Processing is already in progress."))
            if not job.cv_attachment_ids:
                raise UserError(_("Please attach CV files."))

            to_process = job.cv_attachment_ids - job.processed_cv_attachment_ids
            if not to_process:
                raise UserError(_("All attached CVs have already been processed."))

            job_record = job.with_delay()._process_cvs_thread(self.env.user.id, to_process.ids)

            job.write({
                'processed_cv_attachment_ids': [(5, 0, 0)],
                'processed_cv_count': 0, 'failed_cv_count': 0,
                'total_cv_count': len(to_process),
                'bulk_processing_complete': False, 'bulk_processing_failed': False,
                'bulk_queue_job_uuid': job_record.uuid,
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'title': _('Processing Started'), 'message': _('Started for %s CV(s).', len(to_process)), 'type': 'info'}
            }
        except odoo.exceptions.LockNotAvailable:
            raise UserError(_("Job locked. Try again later."))

    def action_delete_cv_attachments(self):
        self.ensure_one()
        (self.cv_attachment_ids | self.processed_cv_attachment_ids).unlink()
        self.write({
            'cv_attachment_ids': [(5, 0, 0)], 'processed_cv_attachment_ids': [(5, 0, 0)],
            'bulk_processing_complete': False, 'bulk_processing_failed': False, 'bulk_queue_job_uuid': False,
            'processed_cv_count': 0, 'failed_cv_count': 0, 'total_cv_count': 0,
        })
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'title': _('Files Deleted'), 'message': _('Files deleted.'), 'type': 'success'}}

    # --- Actions: JD Parsing ---

    def action_generate_requirements_from_file(self):
        self.ensure_one()
        if not self.job_description_attachment_ids: raise UserError(_("Please upload a JD file."))
        if len(self.job_description_attachment_ids) > 1: raise UserError(_("Only 1 file allowed."))
        if self.jd_processing_in_progress: raise UserError(_("Already in progress."))

        att = self.job_description_attachment_ids[0]
        if att in self.jd_processed_attachment_ids and self.jd_extract_state != 'error':
            self.requirement_statement_ids.unlink()

        self.write({'jd_extract_state': 'pending', 'jd_extract_status': _('Pending...'), 'jd_processed_attachment_ids': [(5, 0, 0)]})
        job_record = self.with_delay()._run_jd_extraction_job(self.env.user.id, att.id)
        self.jd_queue_job_uuid = job_record.uuid
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'title': _('Processing Started'), 'message': _('AI is analyzing the JD.'), 'type': 'info'}}

    def action_delete_jd_attachment(self):
        self.ensure_one()
        (self.job_description_attachment_ids | self.jd_processed_attachment_ids).unlink()
        self.write({'job_description_attachment_ids': [(5, 0, 0)], 'jd_processed_attachment_ids': [(5, 0, 0)], 'jd_extract_state': 'no_extract', 'jd_extract_status': False, 'jd_queue_job_uuid': False})
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'title': _('File Deleted'), 'message': _('File deleted.'), 'type': 'success'}}

    # --- Background: Bulk CV ---

    def _process_cvs_thread(self, user_id, attachment_ids):
        self.ensure_one()
        attachments = self.env['ir.attachment'].browse(attachment_ids)
        total_success, total_fail, errors = 0, 0, []
        
        for att in attachments:
            try:
                with odoo.registry(self.env.cr.dbname).cursor() as new_cr:
                    new_env = api.Environment(new_cr, self.env.uid, self.env.context)
                    job_in_tx = new_env['hr.job'].browse(self.id)
                    att_in_tx = new_env['ir.attachment'].browse(att.id)
                    
                    if not att_in_tx.datas: raise UserError("Empty data")
                    
                    cv_data, cv_name = att_in_tx.datas, att_in_tx.name
                    
                    # Phase 1: AI Extraction (No Lock)
                    from odoo.addons.hr_recruitment_extract_openai.models.hr_applicant import CVExtraction
                    response_model = new_env['hr.applicant']._openai_call(att_in_tx, prompt=OPENAI_CV_EXTRACTION_PROMPT, text_format=CVExtraction)
                    data_dict = response_model.model_dump(mode='json')

                    # Phase 2: Write (Lock)
                    new_env.cr.execute('SELECT * FROM hr_job WHERE id = %s FOR UPDATE', (self.id,), log_exceptions=False)
                    
                    create_vals = {
                        'name': _("%s's Application") % (data_dict.get('name') or cv_name.rsplit('.', 1)[0]),
                        'partner_name': data_dict.get('name'),
                        'email_from': data_dict.get('email'),
                        'partner_phone': data_dict.get('phone'),
                        'job_id': job_in_tx.id,
                        'openai_extract_state': 'done',
                        'openai_extract_status': _('Created from bulk import.'),
                    }
                    new_applicant = new_env['hr.applicant'].create(create_vals)
                    status = new_applicant._process_extracted_cv_data(data_dict)
                    new_applicant.write({'openai_extract_status': status})

                    new_attachment = new_env['ir.attachment'].create({'name': cv_name, 'datas': cv_data, 'res_model': 'hr.applicant', 'res_id': new_applicant.id})
                    new_applicant.write({'message_main_attachment_id': new_attachment.id})
                    
                    job_in_tx.write({'processed_cv_count': job_in_tx.processed_cv_count + 1, 'processed_cv_attachment_ids': [(4, att_in_tx.id)]})
                    
                    # Trigger AI Match if configured
                    if job_in_tx.run_ai_match_on_bulk and job_in_tx.requirement_statement_ids:
                         new_applicant.write({'ai_match_state': 'pending', 'ai_match_status': _('Pending auto-match...')})
                         new_applicant.with_delay(eta=10)._run_ai_match_job(user_id)

                    new_cr.commit()
                    total_success += 1
            except Exception as e:
                _logger.error("CV Fail: %s", e)
                total_fail += 1
                errors.append(f"{att.name}: {e}")
                try:
                    with odoo.registry(self.env.cr.dbname).cursor() as f_cr:
                        f_env = api.Environment(f_cr, self.env.uid, self.env.context)
                        f_env.cr.execute('SELECT * FROM hr_job WHERE id = %s FOR UPDATE', (self.id,), log_exceptions=False)
                        f_env['hr.job'].browse(self.id).write({'failed_cv_count': self.failed_cv_count + total_fail}) # Update current count logic
                        f_cr.commit()
                except Exception: pass

        # Finalize
        try:
            with odoo.registry(self.env.cr.dbname).cursor() as fin_cr:
                f_env = api.Environment(fin_cr, self.env.uid, self.env.context)
                f_env.cr.execute('SELECT * FROM hr_job WHERE id = %s FOR UPDATE', (self.id,), log_exceptions=False)
                job = f_env['hr.job'].browse(self.id)
                job.write({'bulk_processing_complete': True, 'bulk_processing_failed': total_fail > 0, 'bulk_queue_job_uuid': False})
                fin_cr.commit()
                
                msg = _("Finished. %s created, %s failed.", total_success, total_fail)
                if errors: msg += _("\nErrors:\n- ") + "\n- ".join(errors)
                f_env['hr.applicant']._notify_user(user_id, {'title': _('Processing Complete'), 'message': msg, 'type': 'warning' if total_fail else 'success'})
        except Exception as e:
            _logger.error("Finalize Error: %s", e)

    # --- Background: JD Parsing ---

    def _run_jd_extraction_job(self, user_id, attachment_id):
        self.ensure_one()
        job = self
        att = self.env['ir.attachment'].browse(attachment_id)
        if not att.exists(): return

        success, err = False, ""
        try:
            with self.env.cr.savepoint():
                job.write({'jd_extract_state': 'processing', 'jd_extract_status': _('Calling AI...')})
                reqs = self._execute_jd_extract_single(att)
            with self.env.cr.savepoint():
                self._process_jd_extract_data(reqs)
            job.write({'jd_extract_state': 'done', 'jd_extract_status': _('Success.'), 'jd_processed_attachment_ids': [(6, 0, [att.id])]})
            success = True
        except Exception as e:
            self.env.cr.rollback()
            err = str(e)
            job.write({'jd_extract_state': 'error', 'jd_extract_status': err})
            self.env.cr.commit()
        finally:
            job.write({'jd_queue_job_uuid': False})
            self.env['hr.applicant']._notify_user(user_id, {'title': _('JD Processing'), 'message': _('Success') if success else _('Failed: %s', err), 'type': 'success' if success else 'warning'})

    def _execute_jd_extract_single(self, attachment):
        res = self.env['hr.applicant']._openai_call(attachment, prompt=JD_EXTRACT_SINGLE_PROMPT, text_format=JDRequirementList)
        return [req.model_dump() for req in res.requirements]

    def _process_jd_extract_data(self, data):
        self.requirement_statement_ids.unlink()
        Tag = self.env['hr.job.requirement.tag']
        
        tag_map = {}
        names = list(set(r['tag_name'] for r in data if r.get('tag_name')))
        if names:
            existing = Tag.search([('name', 'in', names)])
            tag_map = {t.name.lower(): t.id for t in existing}
            new = [n for n in names if n.lower() not in tag_map]
            if new:
                for t in Tag.create([{'name': n} for n in new]): tag_map[t.name.lower()] = t.id

        vals = []
        for i, r in enumerate(data):
            tid = tag_map.get(r.get('tag_name', '').lower())
            vals.append({
                'name': r['name'], 'job_id': self.id, 'weight': r.get('weight', 1.0),
                'sequence': (i + 1) * 10, 'tag_ids': [(6, 0, [tid])] if tid else False
            })
        if vals: self.env['hr.job.requirement'].create(vals)