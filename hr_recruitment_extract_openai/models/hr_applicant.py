# -*- coding: utf-8 -*-
import openai
import json
import logging
import odoo
import re
from collections import defaultdict
from typing import List, Optional
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from pydantic import BaseModel, Field

from .openai_prompts import (
    OPENAI_CV_EXTRACTION_PROMPT,
    AI_MATCH_SINGLE_PROMPT_TEMPLATE,
    AI_MATCH_MULTI_PROMPT_TEMPLATE,
    AI_MATCH_MULTI_SUMMARY_PROMPT_TEMPLATE,
    EXPERIENCE_SCORING_PROMPT,
    COMPANY_ENRICHMENT_PROMPT,
)

_logger = logging.getLogger(__name__)


# --- Pydantic Models for CV Extraction ---

class Skill(BaseModel):
    """Pydantic model for a single extracted skill."""
    type: str = Field(
        description="Category of the skill (e.g., 'Programming Languages')."
    )
    skill: str = Field(description="Name of the skill (e.g., 'Python').")
    level: str = Field(
        description="Proficiency level (e.g., 'Advanced (80%)'). "
                    "Use 'Beginner (15%)' if not specified."
    )

class CVExtraction(BaseModel):
    """Pydantic model for the main CV extraction."""
    name: Optional[str] = Field(
        description="Full name of the applicant.", default=None
    )
    email: Optional[str] = Field(
        description="Primary email address.", default=None
    )
    phone: Optional[str] = Field(
        description="Primary phone number.", default=None
    )
    linkedin: Optional[str] = Field(
        description="Applicant's LinkedIn profile URL.", default=None
    )
    degree: Optional[str] = Field(
        description="Highest or most relevant academic degree.", default=None
    )
    skills: List[Skill] = Field(
        description="A list of professional skills found in the CV.",
        default_factory=list
    )


# --- Pydantic Models for AI Match ---

class AIStatementMatch(BaseModel):
    """Pydantic model for a single requirement match statement."""
    requirement_id: int = Field(
        description="The ID of the requirement being evaluated."
    )
    match_fit: str = Field(
        description="The fit score (not_fit, poor_fit, fit, "
                    "good_fit, excellent_fit)."
    )
    explanation: str = Field(
        description="Concise explanation for the score, citing CV evidence."
    )

class AISummary(BaseModel):
    """Pydantic model for the overall match summary."""
    overall_fit: str = Field(
        description="Brief overall fit (e.g., 'Strong potential')."
    )
    key_strengths: List[str] = Field(
        description="List of key strengths matching requirements."
    )
    missing_gaps: List[str] = Field(
        description="List of key requirements that are missing."
    )

class AISingleMatch(BaseModel):
    """Pydantic model for the Single-Prompt AI Match response."""
    summary: AISummary
    statement_matches: List[AIStatementMatch]

class AIMultiMatch(BaseModel):
    """Pydantic model for the Multi-Prompt (Category) AI Match response."""
    statement_matches: List[AIStatementMatch]

class AIMultiSummary(BaseModel):
    """Pydantic model for the Multi-Prompt (Summary) AI Match response."""
    summary: AISummary


# --- Pydantic Models for Experience/Credibility ---

class ExperienceItem(BaseModel):
    """Pydantic model for a single work experience item extracted from CV (Phase 1)."""
    role: str = Field(description="Role title")
    company: str = Field(description="Company name, or empty if pet/university/fun project")
    project: str = Field(description="Project name if applicable", default="")
    start_date: str = Field(description="Start date text (e.g. March 2025)")
    end_date: str = Field(description="End date text (e.g. September 2025 or 'Present')")
    duration_str: str = Field(description="Duration text (e.g. '6 months')")
    duration_months: int = Field(description="Calculated number of months")
    description: str = Field(description="Brief summary of tasks/responsibilities")
    
    # Scores (0-100%) & Explanations (from Phase 1)
    experience_relevance: float = Field(description="Relevance of role (0-100%)")
    experience_relevance_explanation: str = Field(description="Reasoning for the experience relevance score based on requirements")
    
    project_relevance: float = Field(description="Relevance of project (0-100%)")
    project_relevance_explanation: str = Field(description="Reasoning for the project relevance score")
    
    company_relevance: float = Field(description="Relevance of company industry (0-100%)")
    company_relevance_explanation: str = Field(description="Reasoning for the company relevance score")
    
    company_credibility: float = Field(description="Credibility/Stability of company (0-100%)")
    company_credibility_explanation: str = Field(description="Reasoning for the company credibility score")

    # Company Info
    comp_website: str = Field(description="Company website URL", default="")
    comp_linkedin: str = Field(description="Company LinkedIn URL", default="")
    comp_industry: str = Field(description="Industry sector", default="")
    comp_domain: str = Field(description="Business domain", default="")
    comp_geo: str = Field(description="Location/Team location", default="")
    comp_team_size: str = Field(description="Team size", default="")
    comp_type: str = Field(description="Type: Outsource/Product/Outstaff/Startup", default="")
    comp_clients: str = Field(description="Main clients if found", default="")
    
    # Company Summary
    comp_positive_signals: List[str] = Field(description="List of positive signals about credibility", default_factory=list)
    comp_areas_to_verify: List[str] = Field(description="List of uncertainties/red flags", default_factory=list)
    comp_summary: str = Field(description="Final summary about company credibility", default="")


class ExperienceScoring(BaseModel):
    """Pydantic model for the Experience Scoring (Phase 1) response."""
    job_hopping_coefficient: float = Field(
        description="Coefficient from 0.0 (stable) to 1.0 (highly unstable/high hopping)."
    )
    work_experience: List[ExperienceItem] = Field(description="List of scored work experiences")

class CompanyEnrichment(BaseModel):
    """Pydantic model for the Company Enrichment (Phase 2) response."""
    enriched_companies: List[ExperienceItem] = Field(
        description="List of company objects enriched with web search data."
    )


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'
    _order = (
        "openai_extract_state desc, "
        "ai_match_state desc, "
        "ai_experience_score desc, "
        "priority desc, "
        "id desc"
    )

    # --- 1. Fields for CV Extraction ---
    openai_extract_state = fields.Selection(
        selection=[
            ('no_extract', 'No Extraction'),
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('error', 'Error'),
        ],
        string='OpenAI Extract State',
        default='no_extract',
        required=True,
        copy=False,
    )
    openai_extract_status = fields.Text(
        string="OpenAI Extract Status",
        readonly=True,
        copy=False
    )
    can_extract_with_openai = fields.Boolean(
        compute='_compute_can_extract_with_openai',
        string="Can Extract with OpenAI"
    )
    linkedin_profile = fields.Char(
        "LinkedIn Profile",
        copy=False,
        help="Stores the LinkedIn profile URL extracted from the CV."
    )

    # --- 2. Fields for AI Match ---
    ai_match_percent = fields.Float(
        string='AI Match Score (%)',
        compute='_compute_ai_match_percent',
        store=True,
        digits=(16, 2),
        help="Overall match score calculated from weighted requirements.",
    )
    ai_match_summary_fit = fields.Char(
        string="AI Summary: Overall Fit",
        readonly=True,
        copy=False
    )
    ai_match_summary_strengths = fields.Text(
        string="AI Summary: Key Strengths",
        readonly=True,
        copy=False
    )
    ai_match_summary_gaps = fields.Text(
        string="AI Summary: Missing Gaps",
        readonly=True,
        copy=False
    )

    ai_match_statement_ids = fields.One2many(
        'hr.applicant.match.statement',
        'applicant_id',
        string="AI Match Details"
    )
    ai_match_state = fields.Selection(
        selection=[
            ('no_match', 'Not Matched'),
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('error', 'Error'),
        ],
        string='AI Match State',
        default='no_match',
        required=True,
        copy=False,
    )
    ai_match_status = fields.Text(
        string="AI Match Status",
        readonly=True,
        copy=False
    )

    can_run_ai_match = fields.Boolean(
        compute='_compute_can_run_ai_match',
        string="Can Run AI Match"
    )
    ai_match_mode = fields.Selection(
        related='job_id.ai_match_mode',
        string="Applicant Match Mode",
        readonly=True
    )

    # --- 3. Fields for Experience Evaluation ---
    experience_ids = fields.One2many(
        'hr.applicant.experience',
        'applicant_id',
        string="Work Experience & Experience Details"
    )
    
    ai_experience_score = fields.Float(
        string="AI Experience Score (Total Points)",
        compute="_compute_experience_total",
        store=True,
        digits=(16, 2),
        help="Sum of all experience line scores without normalization."
    )
    
    job_hopping_coefficient = fields.Float(
        string="Job Hopping Penalty (0.0-1.0)",
        default=0.0,
        digits=(16, 3),
        help="Coefficient to penalize frequent job changes. 0.0 is stable, 1.0 is maximum penalty."
    )
    
    experience_state = fields.Selection(
        selection=[
            ('no_check', 'Not Evaluated'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('error', 'Error'),
        ],
        string='Experience Evaluation State',
        default='no_check',
        copy=False,
    )
    experience_status = fields.Text(
        string="Experience Evaluation Status",
        readonly=True,
        copy=False
    )
    
    can_run_experience_analysis = fields.Boolean(
        string="Can Run Experience Evaluation",
        compute='_compute_can_run_experience_analysis',
    )


    # --- Compute Methods ---

    @api.depends('experience_ids.total_line_score')
    def _compute_experience_total(self):
        """
        Computes the final AI Experience Score by summing the line scores.
        and applying the job hopping penalty.
        """
        for app in self:
            if not app.experience_ids:
                app.ai_experience_score = 0.0
                continue
            
            # Simply sum all the line scores and apply job hopping penalty 
            total_sum = sum(line.total_line_score for line in app.experience_ids) * (1 - app.job_hopping_coefficient)
            
            app.ai_experience_score = total_sum

    @api.depends('message_main_attachment_id',
                 'openai_extract_state',
                 'company_id.openai_cv_extract_mode')
    def _compute_can_extract_with_openai(self):
        for applicant in self:
            company = applicant.company_id or self.env.company
            is_manual_mode = company.openai_cv_extract_mode == 'manual_send'
            can_retry = applicant.openai_extract_state in (
                'no_extract', 'error', 'done'
            )
            applicant.can_extract_with_openai = (
                is_manual_mode and
                applicant.message_main_attachment_id and
                can_retry
            )

    @api.depends('job_id.requirement_statement_ids',
                 'message_main_attachment_id',
                 'ai_match_state')
    def _compute_can_run_ai_match(self):
        for applicant in self:
            has_job = applicant.job_id
            has_reqs = has_job and applicant.job_id.requirement_statement_ids
            has_cv = applicant.message_main_attachment_id
            can_retry = applicant.ai_match_state in (
                'no_match', 'error', 'done'
            )
            applicant.can_run_ai_match = (
                has_job and has_reqs and has_cv and can_retry
            )
            
    @api.depends('message_main_attachment_id', 'experience_state')
    def _compute_can_run_experience_analysis(self):
        """
        Checks if the applicant has a CV and is not currently processing, 
        allowing for a new run or retry.
        """
        for applicant in self:
            has_cv = applicant.message_main_attachment_id
            can_retry = applicant.experience_state in (
                'no_check', 'error', 'done'
            )
            applicant.can_run_experience_analysis = has_cv and can_retry

    @api.depends('ai_match_statement_ids.match_score',
                 'ai_match_statement_ids.requirement_weight')
    def _compute_ai_match_percent(self):
        """
        Computes the overall AI Match Score as a weighted average of statement scores.
        """
        for applicant in self:
            if not applicant.ai_match_statement_ids:
                applicant.ai_match_percent = 0.0
                continue

            achieved_score = 0.0
            total_possible_weight = 0.0

            for statement in applicant.ai_match_statement_ids:
                normalized_score = statement.match_score / 100.0
                achieved_score += (
                    normalized_score * statement.requirement_weight
                )
                total_possible_weight += statement.requirement_weight

            if total_possible_weight == 0:
                applicant.ai_match_percent = 0.0
            else:
                applicant.ai_match_percent = (
                    (achieved_score / total_possible_weight) * 100.0
                )

    # --- Button Actions ---

    def action_extract_with_openai(self):
        """Action for bulk/single extraction via OpenAI."""
        applicants_to_process = self.filtered(
            lambda a: a.can_extract_with_openai
        )
        if not applicants_to_process:
            raise UserError(_(
                "There are no applicants here that are ready for extraction."
            ))

        applicants_to_process.write({
            'openai_extract_state': 'pending',
            'openai_extract_status': _('Pending: Queued for extraction...'),
        })

        user_id = self.env.user.id
        for applicant in applicants_to_process:
            applicant.with_delay()._run_openai_extraction_job(user_id)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Processing Started'),
                'message': _('The CV processing has been queued.'),
                'type': 'info',
                'sticky': False,
            }
        }

    def action_run_ai_match(self):
        """Action for bulk/single AI Match."""
        # 1. Check for requirements first
        no_req_applicants = self.filtered(lambda a: not a.job_id.requirement_statement_ids)
        if no_req_applicants:
             raise UserError(_(
                "Cannot run AI Match for the following applicants because their Job Position has no requirements:\n%s\n\n"
                "Please go to the Job Position -> AI Match Configuration -> Generate Requirements.",
                ", ".join(no_req_applicants.mapped('name'))
            ))

        applicants_to_process = self.filtered(lambda a: a.can_run_ai_match)
        if not applicants_to_process:
            raise UserError(_(
                "Cannot run AI Match. Ensure the applicant has a Job, "
                "a CV, and Job Requirements."
            ))

        applicants_to_process.write({
            'ai_match_state': 'pending',
            'ai_match_status': _('Pending: Queued for AI matching...'),
        })

        user_id = self.env.user.id
        for applicant in applicants_to_process:
            applicant.with_delay()._run_ai_match_job(user_id)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Processing Started'),
                'message': _('The AI matching has been queued.'),
                'type': 'info',
                'sticky': False,
            }
        }

    def action_analyze_experience(self):
        """
        Triggers the two-step Experience Evaluation (Scoring + Enrichment).
        Used by the action button on the form/list views.
        """
        # 1. Check for requirements first
        no_req_applicants = self.filtered(lambda a: not a.job_id.requirement_statement_ids)
        if no_req_applicants:
             raise UserError(_(
                "Cannot run Experience Evaluation for the following applicants because their Job Position has no requirements:\n%s\n\n"
                "Please go to the Job Position -> AI Match Configuration -> Generate Requirements.",
                ", ".join(no_req_applicants.mapped('name'))
            ))
            
        applicants_to_process = self.filtered(lambda a: a.can_run_experience_analysis)
        if not applicants_to_process:
            raise UserError(_("Cannot run Experience Evaluation. Ensure the applicant has a CV."))
            
        applicants_to_process.write({
            'experience_state': 'processing',
            'experience_status': _('Processing: Starting Experience Evaluation...'),
        })
        
        user_id = self.env.user.id
        for applicant in applicants_to_process:
            applicant.with_delay()._run_experience_analysis_job(user_id)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Evaluation Started'),
                'message': _('AI is analyzing experience and searching web data for %s applicants.', len(applicants_to_process)),
                'type': 'info',
                'sticky': False,
            }
        }
    
    def action_clear_experience(self):
        """
        Clears all AI experience data. Used by the action button on the form/list views.
        """
        for applicant in self:
            # 1. Unlink detailed experience records
            applicant.experience_ids.unlink()

            # 2. Reset Fields
            applicant.write({
                'experience_state': 'no_check',
                'ai_experience_score': 0.0,
                'job_hopping_coefficient': 0.0,
                'experience_status': False,
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Experience Data Cleared'),
                'message': _(
                    'AI Experience data has been cleared for %s applicant(s).',
                    len(self)
                ),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_clear_ai_match(self):
        """
        Clears all AI matching data, explanations, scores, and
        removes AI-related tags from the applicant.
        """
        for applicant in self:
            # 1. Remove specific AI match tags
            ai_tags = applicant.categ_ids.filtered(
                lambda t: t.name.startswith('AI Match:')
            )
            if ai_tags:
                applicant.write({'categ_ids': [(3, tag.id) for tag in ai_tags]})

            # 2. Unlink detailed statements
            applicant.ai_match_statement_ids.unlink()

            # 3. Reset Fields
            applicant.write({
                'ai_match_state': 'no_match',
                'ai_match_percent': 0.0,
                'ai_match_summary_fit': False,
                'ai_match_summary_strengths': False,
                'ai_match_summary_gaps': False,
                'ai_match_status': False,
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Data Cleared'),
                'message': _(
                    'AI Match data has been cleared for %s applicant(s).',
                    len(self)
                ),
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def _notify_user(self, user_id, params):
        """Utility function to send a non-blocking notification to a user."""
        try:
            with odoo.registry(self.env.cr.dbname).cursor() as notify_cr:
                notify_env = api.Environment(
                    notify_cr, self.env.uid, self.env.context
                )
                user = notify_env['res.users'].browse(user_id)
                if user.partner_id:
                    notify_env['bus.bus']._sendone(
                        user.partner_id, 'simple_notification', params
                    )
                notify_cr.commit()
        except Exception as e:
            _logger.error(
                "Failed to send notification to user %s: %s", user_id, str(e)
            )

    # --- Background Job: CV Extraction ---

    def _run_openai_extraction_job(self, user_id):
        """
        Job queue method to run the single applicant CV extraction.
        """
        self.ensure_one()
        applicant = self
        success = False
        error_message = ""

        try:
            with self.env.cr.savepoint():
                _logger.info(
                    "Starting OpenAI extraction for applicant ID: %s",
                    applicant.id
                )
                applicant.write({
                    'openai_extract_state': 'processing',
                    'openai_extract_status': _(
                        'Processing: Calling OpenAI API...'
                    ),
                })

                # Call OpenAI for data extraction
                response_model = self.env['hr.applicant']._openai_call(
                    applicant.message_main_attachment_id,
                    prompt=OPENAI_CV_EXTRACTION_PROMPT,
                    text_format=CVExtraction
                )

                applicant.write({
                    'openai_extract_status': _(
                        'Processing: Converting response...'
                    )
                })
                extracted_data = response_model.model_dump(mode='json')

                # Process and save the data
                skill_status_message = applicant._process_extracted_cv_data(
                    extracted_data
                )

            applicant.write({
                'openai_extract_state': 'done',
                'openai_extract_status': skill_status_message,
            })
            success = True

        except Exception as e:
            _logger.error(
                "OpenAI extraction failed: %s", str(e), exc_info=True
            )
            self.env.cr.rollback()
            error_message = _("Error: %s", str(e))
            applicant.write({
                'openai_extract_state': 'error',
                'openai_extract_status': error_message,
            })
            self.env.cr.commit()
            success = False

        finally:
            params = {}
            if success:
                params = {
                    'title': _('Processing Complete'),
                    'message': _("Extracted data for '%s'.", applicant.name),
                    'type': 'success'
                }
            elif error_message:
                params = {
                    'title': _('Processing Failed'),
                    'message': _(
                        "Failed to extract data.\n%s", error_message
                    ),
                    'type': 'warning',
                    'sticky': True
                }

            if params:
                self._notify_user(user_id, params)
    
    # --- Background Job: Experience Evaluation (2-step) ---
    
    def _run_experience_analysis_job(self, user_id):
        """
        Orchestrates the two-step process:
        Phase 1: Scoring, Job Hopping calculation AND initial Web Search.
        Phase 2: Company Verification and Deep Dive (Web Search).
        """
        self.ensure_one()
        applicant = self
        
        try:
            # PHASE 1: EXPERIENCE SCORING & JOB HOPPING (WITH WEB SEARCH)
            applicant.write({
                'experience_state': 'processing',
                'experience_status': _('Processing (1/2): Scoring experience & fetching company info...')
            })
            (experience_data, job_hopping_coeff) = self._run_experience_scoring()
            
            # PHASE 2: COMPANY ENRICHMENT AND FINAL CREDIBILITY (WITH VERIFICATION WEB SEARCH)
            applicant.write({
                'experience_status': _('Processing (2/2): Verifying and enriching company data...')
            })
            self._run_company_enrichment(experience_data, job_hopping_coeff)

            applicant.write({
                'experience_state': 'done',
                'experience_status': _('Evaluation complete. Score: %s', round(applicant.ai_experience_score, 2)),
            })
            
            self._notify_user(user_id, {
                'title': _('Experience Evaluation Complete'),
                'message': _(
                    "Experience evaluation complete for '%s'. Score: %s",
                    applicant.name, round(applicant.ai_experience_score, 2)
                ),
                'type': 'success'
            })

        except Exception as e:
            _logger.error("Experience Evaluation failed: %s", str(e), exc_info=True)
            applicant.write({
                'experience_state': 'error',
                'experience_status': _("Evaluation Failed: %s", str(e)),
            })
            self._notify_user(user_id, {
                'title': 'Evaluation Failed',
                'message': f'Error: {str(e)}',
                'type': 'warning',
                'sticky': True
            })

    def _run_experience_scoring(self):
        """
        Runs PROMPT 5: Extracts experience, scores it, AND uses Web Search
        to gather initial company data (website, industry, etc.).
        """
        self.ensure_one()
        
        # 1. Prepare Job Requirements for the Prompt
        job_reqs = self.job_id.requirement_statement_ids
        if job_reqs:
            formatted_requirements = "\n".join(
                [f"- {r.name} (Weight: {r.weight})" for r in job_reqs]
            )
        else:
            formatted_requirements = (
                self.job_id.description or 
                f"Job Position: {self.job_id.name}"
            )

        # 2. Inject Requirements into the Prompt
        final_prompt = EXPERIENCE_SCORING_PROMPT.format(
            job_requirements=formatted_requirements
        )

        # 3. Call OpenAI with Web Search enabled (Changed from False to True)
        response_model = self._openai_call(
            self.message_main_attachment_id,
            prompt=final_prompt,
            text_format=ExperienceScoring,
            web_search=True  # NOW TRUE for Prompt 5
        )
        
        data = response_model.model_dump(mode='json')
        
        job_hopping_coeff = min(max(data.get('job_hopping_coefficient', 0.0), 0.0), 1.0)
        
        return data.get('work_experience', []), job_hopping_coeff

    def _run_company_enrichment(self, experience_data, job_hopping_coeff):
        """
        Runs PROMPT 6: Takes the experience data (already containing initial web search info)
        and uses Web Search again to VERIFY links, correct errors, and deepen the analysis.
        """
        self.ensure_one()
        
        # 1. Prepare the data payload for the enrichment prompt
        # The enrichment prompt needs the company name and any existing data to refine the search.
        company_data_for_enrichment = [
            {'company': item.get('company'), 
             'role': item.get('role'), 
             'duration_str': item.get('duration_str'),
             # Pass the data found in Step 1 so Step 2 can verify it
             'comp_website': item.get('comp_website', ''),
             'comp_linkedin': item.get('comp_linkedin', ''),
             'comp_industry': item.get('comp_industry', ''),
             'comp_type': item.get('comp_type', ''),
             'comp_team_size': item.get('comp_team_size', ''),
             }
            for item in experience_data if item.get('company')
        ]
        
        final_prompt = COMPANY_ENRICHMENT_PROMPT.format(
            company_data_json=json.dumps(company_data_for_enrichment, indent=2)
        )
        
        # 2. Call OpenAI with Web Search Tool (Verification step)
        response_model = self._openai_call(
            self.message_main_attachment_id, # Use CV file as context
            prompt=final_prompt,
            text_format=CompanyEnrichment,
            web_search=True
        )
        
        enriched_data = response_model.model_dump(mode='json').get('enriched_companies', [])
        
        # 3. Map enriched data back to original data structure
        enriched_map = {item['company']: item for item in enriched_data}
        
        # 4. Clear existing lines and create new ones
        self.experience_ids.unlink()
        
        ExpEnv = self.env['hr.applicant.experience']
        new_lines = []
        
        # Fetch job weights from the current job to populate the experience lines
        job_weights = {
            'weight_experience': self.job_id.weight_experience,
            'weight_project': self.job_id.weight_project,
            'weight_company': self.job_id.weight_company,
            'weight_credibility': self.job_id.weight_credibility,
        } if self.job_id else {}

        for item in experience_data:
            company_name = item.get('company')
            enriched_item = enriched_map.get(company_name, {})
            
            # Combine scored data (item from Phase 1) with verified data (enriched_item from Phase 2)
            # enriched_item takes precedence for company details as it's the "verified" version.
            vals = {
                'applicant_id': self.id,
                'role': item.get('role'),
                'company_name': company_name,
                'project_name': item.get('project'),
                'start_date_str': item.get('start_date'),
                'end_date_str': item.get('end_date'),
                'duration_str': item.get('duration_str'),
                'duration_months': item.get('duration_months'),
                'description': item.get('description'),
                
                # Phase 1 Scores & Explanations
                'experience_relevance': item.get('experience_relevance'),
                'experience_relevance_explanation': item.get('experience_relevance_explanation'),
                'project_relevance': item.get('project_relevance'),
                'project_relevance_explanation': item.get('project_relevance_explanation'),
                'company_relevance': item.get('company_relevance'),
                'company_relevance_explanation': item.get('company_relevance_explanation'),
                'company_credibility': item.get('company_credibility'),
                'company_credibility_explanation': item.get('company_credibility_explanation'),
                
                # Weights from Job (used for total score calculation and display)
                **job_weights, 
                
                # Phase 2 Enrichment (Verified Data)
                'comp_website': enriched_item.get('comp_website', item.get('comp_website')),
                'comp_linkedin': enriched_item.get('comp_linkedin', item.get('comp_linkedin')),
                'comp_industry': enriched_item.get('comp_industry', item.get('comp_industry')),
                'comp_domain': enriched_item.get('comp_domain', item.get('comp_domain')),
                'comp_geo': enriched_item.get('comp_geo', item.get('comp_geo')),
                'comp_team_size': enriched_item.get('comp_team_size', item.get('comp_team_size')),
                'comp_type': enriched_item.get('comp_type', item.get('comp_type')),
                'comp_clients': enriched_item.get('comp_clients', item.get('comp_clients')),
                
                'comp_positive_signals': "\n".join(enriched_item.get('comp_positive_signals', item.get('comp_positive_signals', []))),
                'comp_areas_to_verify': "\n".join(enriched_item.get('comp_areas_to_verify', item.get('comp_areas_to_verify', []))),
                'comp_summary': enriched_item.get('comp_summary', item.get('comp_summary')),
            }
            new_lines.append(vals)
        
        if new_lines:
            ExpEnv.create(new_lines)
            
        # Update Job Hopping Coefficient
        self.write({'job_hopping_coefficient': job_hopping_coeff})


    # --- Background Job: AI Match ---

    def _get_or_create_ai_match_tag(self, percent=None):
        """
        Helper to classify the applicant's match percentage
        into a color-coded tag (e.g. "Fit", "Good Fit").
        """
        self.ensure_one()
        ApplicantTag = self.env['hr.applicant.category']
        tag_name = "AI Match: Failed"
        tag_color = 2  # Red

        if percent is not None:
            fit_display_name = "N/A"
            if percent <= 30:
                fit_display_name, tag_color = "Not a Fit", 2
            elif percent <= 50:
                fit_display_name, tag_color = "Poor Fit", 3
            elif percent <= 70:
                fit_display_name, tag_color = "Fit", 5
            elif percent <= 90:
                fit_display_name, tag_color = "Good Fit", 10
            else:
                fit_display_name, tag_color = "Excellent Fit", 20

            # Use floor to keep the tag name clean (e.g., 91.5% is 91%)
            tag_name = f"AI Match: {fit_display_name} - {int(percent)}%"

        tag = ApplicantTag.search(
            [('name', '=', tag_name), ('color', '=', tag_color)], limit=1
        )
        if not tag:
            tag = ApplicantTag.create({'name': tag_name, 'color': tag_color})

        old_tags = self.categ_ids.filtered(
            lambda t: t.name.startswith('AI Match:')
        )
        commands = []
        if old_tags:
            commands.extend(
                [(3, old_tag.id) for old_tag in old_tags if old_tag.id != tag.id]
            )
        if tag.id not in self.categ_ids.ids:
            commands.append((4, tag.id))
        if commands:
            self.write({'categ_ids': commands})

    def _run_ai_match_job(self, user_id):
        """
        Main job queue method to run the AI Match process (single or multi-prompt).
        """
        self.ensure_one()
        applicant = self
        success = False
        error_message = ""

        try:
            if not applicant.job_id.requirement_statement_ids:
                raise UserError(_(
                    "No job requirements found for job '%s'.",
                    applicant.job_id.name
                ))

            if applicant.ai_match_mode == 'multi_prompt':
                self._run_ai_match_job_multi(user_id)
            else:
                self._run_ai_match_job_single(user_id)

            success = True
            applicant.write({
                'ai_match_state': 'done',
                'ai_match_status': _(
                    'AI Match complete. Score: %s%%',
                    round(applicant.ai_match_percent, 2)
                ),
            })
            applicant._get_or_create_ai_match_tag(
                percent=applicant.ai_match_percent
            )

        except Exception as e:
            _logger.error("AI Match failed: %s", str(e), exc_info=True)
            self.env.cr.rollback()
            error_message = _("Error: %s", str(e))
            applicant.write({
                'ai_match_state': 'error',
                'ai_match_status': error_message,
            })
            try:
                applicant._get_or_create_ai_match_tag(percent=None)
            except Exception:
                self.env.cr.rollback()

            self.env.cr.commit()
            success = False

        finally:
            params = {}
            if success:
                params = {
                    'title': _('AI Match Complete'),
                    'message': _(
                        "Matched CV for '%s'. Score: %s%%",
                        applicant.name, round(applicant.ai_match_percent, 2)
                    ),
                    'type': 'success'
                }
            elif error_message:
                params = {
                    'title': _('AI Match Failed'),
                    'message': _(
                        "Failed to match CV.\n%s", error_message
                    ),
                    'type': 'warning',
                    'sticky': True
                }
            if params:
                self._notify_user(user_id, params)

    def _run_ai_match_job_single(self, user_id):
        """Runs the AI Match in single-prompt mode."""
        self.ensure_one()
        with self.env.cr.savepoint():
            self.write({
                'ai_match_state': 'processing',
                'ai_match_status': _(
                    'Processing (Single): Preparing requirements...'
                )
            })

            job_reqs = self.job_id.requirement_statement_ids
            # Prepare requirements data including relevant companies
            job_requirements_data = [{
                'id': req.id,
                'name': req.name,
                'weight': req.weight,
                'tags': [tag.name for tag in req.tag_ids],
                'relevant_companies': [
                    p.name for p in req.company_relevance_ids
                ]
            } for req in job_reqs]

            prompt = AI_MATCH_SINGLE_PROMPT_TEMPLATE.format(
                job_requirements_json=json.dumps(
                    job_requirements_data, indent=2
                )
            )

            self.write({
                'ai_match_status': _(
                    'Processing (Single): Calling AI service...'
                )
            })
            response_model = self.env['hr.applicant']._openai_call(
                self.message_main_attachment_id,
                prompt=prompt,
                text_format=AISingleMatch
            )

            self._process_ai_match_data(response_model.model_dump(mode='json'))

    def _run_ai_match_job_multi(self, user_id):
        """
        Executes the multi-step matching process:
        1. Split requirements by category.
        2. Call OpenAI for each category.
        3. Aggregate results and call OpenAI for a final summary.
        """
        self.ensure_one()
        with self.env.cr.savepoint():
            self.write({
                'ai_match_state': 'processing',
                'ai_match_status': _(
                    'Processing (Multi): Preparing requirements...'
                )
            })

            all_reqs = self.job_id.requirement_statement_ids
            reqs_by_category = defaultdict(list)
            cat_keys = {
                'hard skill': 'Hard Skills',
                'soft skill': 'Soft Skills',
                'domain knowledge': 'Domain Knowledge',
                'operational': 'Operational'
            }

            for req in all_reqs:
                found = False
                for tag in req.tag_ids:
                    key = tag.name.strip().lower()
                    if key in cat_keys:
                        reqs_by_category[cat_keys[key]].append(req)
                        found = True
                        break
                # Default to Operational if no specific tag matches
                if not found:
                    reqs_by_category['Operational'].append(req)

            all_statement_matches = []
            analysis_notes = []

            categories = [
                'Hard Skills',
                'Soft Skills',
                'Domain Knowledge',
                'Operational'
            ]

            for category in categories:
                reqs = reqs_by_category.get(category)
                if not reqs:
                    continue

                self.write({
                    'ai_match_status': _(
                        'Processing (Multi): Analyzing %s...', category
                    )
                })
                # Prepare data structure for the specific category prompt
                job_data = [{
                    'id': r.id,
                    'name': r.name,
                    'weight': r.weight,
                    'relevant_companies': [
                        p.name for p in r.company_relevance_ids
                    ]
                } for r in reqs]

                prompt = AI_MATCH_MULTI_PROMPT_TEMPLATE.format(
                    category_name=category,
                    job_requirements_json=json.dumps(job_data, indent=2)
                )
                
                # Call AI for match statements
                response = self.env['hr.applicant']._openai_call(
                    self.message_main_attachment_id,
                    prompt=prompt,
                    text_format=AIMultiMatch
                )

                matches = response.model_dump(mode='json').get(
                    'statement_matches', []
                )
                all_statement_matches.extend(matches)

                # Collect notes for the final summary
                for m in matches:
                    req_record = self.env['hr.job.requirement'].browse(
                        m.get('requirement_id')
                    )
                    analysis_notes.append({
                        'category': category,
                        'requirement': req_record.name,
                        'fit': m.get('match_fit'),
                        'explanation': m.get('explanation')
                    })

            if not all_statement_matches:
                raise UserError(_("Multi-Prompt analysis returned no results."))

            # Final summary call
            self.write({
                'ai_match_status': _('Processing (Multi): Generating summary...')
            })
            summary_prompt = AI_MATCH_MULTI_SUMMARY_PROMPT_TEMPLATE.format(
                analysis_notes_json=json.dumps(analysis_notes, indent=2)
            )
            summary_response = self.env['hr.applicant']._openai_call(
                self.message_main_attachment_id,
                prompt=summary_prompt,
                text_format=AIMultiSummary
            )

            final_data = {
                "summary": summary_response.model_dump(mode='json').get(
                    'summary'
                ),
                "statement_matches": all_statement_matches
            }
            self._process_ai_match_data(final_data)

    # --- Helpers ---

    @api.model
    def _openai_get_client(self, company_id=None):
        """
        Retrieves the OpenAI client and model name using company settings.
        """
        company = (
            self.env['res.company'].browse(company_id)
            if company_id else self.env.company
        )
        api_key = (company.openai_api_key or '').strip()
        model = (company.openai_model or 'gpt-4o').strip()
        if not api_key:
            raise UserError(_("OpenAI API Key is not set."))
        if not model:
            raise UserError(_("OpenAI Model is not set."))
        return openai.OpenAI(api_key=api_key), model

    @api.model
    def _openai_call(self, attachment, prompt, text_format, web_search=False, text_content=None, company=None):
        """
        Generic method to call OpenAI using the client.responses.parse SDK functionality.
        Supports both File Attachment analysis and Direct Text analysis.
        
        Arguments:
        - attachment: The file to analyze (optional if text_content is provided).
        - prompt: The system prompt or instructions.
        - text_format: The Pydantic model for structured output.
        - web_search: Boolean to enable web search tool.
        - text_content: Raw text string to analyze (optional if attachment is provided).
        - company: Company record to use for API key (optional, defaults to env.company or attachment.company_id).
        """
        # Determine company for API key
        if attachment:
            company = attachment.company_id or self.env.company
        elif not company:
            company = self.env.company
            
        client, model_name = self._openai_get_client(company.id)

        # Validate Inputs
        if not attachment and not text_content:
             raise UserError(_("No input provided for OpenAI (File or Text required)."))
        
        user_content = []

        # Case 1: File Input
        if attachment:
            if not attachment.datas:
                raise UserError(_("CV is empty: %s", attachment.name))

            base64_string = attachment.datas.decode('utf-8')
            file_data_uri = f"data:{attachment.mimetype};base64,{base64_string}"

            user_content.append({
                "type": "input_file",
                "filename": attachment.name,
                "file_data": file_data_uri
            })
            user_content.append({"type": "input_text", "text": "Analyze the attached file."})
        
        # Case 2: Text Input (e.g. Fireflies Transcript)
        elif text_content:
            user_content.append({"type": "input_text", "text": text_content})
        
        # Construct the full input list (System + User)
        input_messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content}
        ]

        try:
            log_msg = f"Calling client.responses.parse model '{model_name}'"
            if attachment:
                log_msg += f" for file '{attachment.name}'"
            else:
                log_msg += f" for text content (len: {len(text_content)})"
                
            _logger.info("%s (Web Search: %s)", log_msg, web_search)
            
            # Prepare API arguments for the Responses API
            api_args = {
                "model": model_name,
                "input": input_messages, 
                "text_format": text_format, 
            }
            
            if web_search:
                api_args["tools"] = [{"type": "web_search"}]

            # Call the OpenAI API
            response = client.responses.parse(**api_args)
            
            # The SDK might return the parsed object in different ways
            if hasattr(response, 'output_parsed'):
                 return response.output_parsed
            elif hasattr(response, 'parsed'):
                 return response.parsed
            else:
                 return response
            
        except Exception as e:
            _logger.error("OpenAI API call failed: %s", str(e), exc_info=True)
            raise UserError(_("OpenAI API call failed: %s", str(e)))

    def _process_extracted_cv_data(self, extracted_data):
        """Processes and saves simple data and skills after CV extraction."""
        self.ensure_one()
        status = _('Successfully extracted data.')
        skills_list = []

        try:
            with self.env.cr.savepoint():
                self._write_extracted_data(extracted_data)
                if (extracted_data.get('skills') and
                        self.env['ir.module.module']._get(
                            'hr_recruitment_skills'
                        ).state == 'installed'):
                    skills_list = extracted_data.get('skills')
        except Exception as e:
            _logger.error("Failed to write simple data: %s", str(e))
            raise UserError(_("Failed to write simple data: %s", str(e)))

        if skills_list:
            try:
                with self.env.cr.savepoint():
                    self._process_skills(skills_list)
            except Exception as e:
                _logger.error("Failed to process skills: %s", str(e))
                status = _("Saved simple data, but failed skills: %s", str(e))

        return status

    def _write_extracted_data(self, data):
        """Updates applicant record with basic extracted data (name, email, etc.)."""
        self.ensure_one()
        if not data:
            return
        vals = {}
        if data.get('name'):
            vals['partner_name'] = data['name']
            if not self.name or self.name.endswith("'s Application"):
                vals['name'] = _("%s's Application") % data['name']
        if data.get('email'):
            vals['email_from'] = data['email']
        if data.get('phone'):
            vals['partner_phone'] = data['phone']
        if data.get('linkedin'):
            # Basic URL validation/cleaning
            match = re.search(
                r'(https?://(?:www\.)?linkedin\.com/[^\s)\]]+)',
                str(data['linkedin'])
            )
            vals['linkedin_profile'] = (
                match.group(1) if match else str(data['linkedin']).strip()
            )

        if data.get('degree'):
            deg_name = data['degree']
            deg_env = self.env['hr.recruitment.degree']
            # Search for existing degree or create new one
            deg = deg_env.search([('name', '=ilike', deg_name)], limit=1)
            if not deg:
                try:
                    deg = deg_env.create({'name': deg_name})
                except Exception:
                    pass
            if deg:
                vals['type_id'] = deg.id

        if vals:
            self.write(vals)

    def _process_skills(self, skills_list):
        """Creates/links hr.skill records based on extracted skill data."""
        self.ensure_one()
        skill_type_env = self.env['hr.skill.type']
        skill_level_env = self.env['hr.skill.level']
        skill_env = self.env['hr.skill']

        default_level = None

        for item in skills_list:
            if not isinstance(item, dict):
                continue
            s_name = item.get('skill')
            s_type = item.get('type', 'General')
            s_level = item.get('level')
            if not s_name:
                continue

            try:
                # Get or create Skill Type
                st = skill_type_env.search(
                    [('name', '=ilike', s_type)], limit=1
                ) or skill_type_env.create({'name': s_type})

                sl = None
                if s_level:
                    # Try to parse the percentage format (e.g., 'Advanced (80%)')
                    match = re.match(r"(.+?)\s*\((\d+)%\)", s_level)
                    if match:
                        level_name = match.group(1).strip()
                        level_progress = int(match.group(2))
                        sl = skill_level_env.search([
                            ('name', '=ilike', level_name),
                            ('level_progress', '=', level_progress)
                        ], limit=1)
                        if not sl:
                            sl = skill_level_env.create({
                                'name': level_name,
                                'level_progress': level_progress
                            })
                    if not sl:
                        # Fallback for simple name match
                        sl = skill_level_env.search(
                            [('name', '=ilike', s_level)], limit=1
                        )

                if not sl:
                    # Use a default level if none found
                    if not default_level:
                        default_level = skill_level_env.search(
                            [('name', '=ilike', 'Beginner')], limit=1
                        ) or skill_level_env.create({
                            'name': 'Beginner', 'level_progress': 15
                        })
                    sl = default_level

                # Ensure level is linked to the type
                if sl not in st.skill_level_ids:
                    st.write({'skill_level_ids': [(4, sl.id)]})

                # Get or create Skill
                sk = skill_env.search(
                    [('name', '=ilike', s_name), ('skill_type_id', '=', st.id)],
                    limit=1
                )
                if not sk:
                    sk = skill_env.search(
                        [('name', '=ilike', s_name)], limit=1
                    )
                    if sk:
                        sk.write({'skill_type_id': st.id})
                    else:
                        sk = skill_env.create({
                            'name': s_name,
                            'skill_type_id': st.id
                        })

                # Create the hr.applicant.skill line if it doesn't exist
                if not self.env['hr.applicant.skill'].search([
                    ('applicant_id', '=', self.id),
                    ('skill_id', '=', sk.id)
                ], limit=1):
                    self.env['hr.applicant.skill'].create({
                        'applicant_id': self.id,
                        'skill_id': sk.id,
                        'skill_level_id': sl.id,
                        'skill_type_id': st.id
                    })

            except Exception:
                # Silently skip individual skill processing errors
                pass

    def _process_ai_match_data(self, match_data):
        """Updates applicant record with match scores and summary."""
        self.ensure_one()
        # Delete old statements before creating new ones
        self.ai_match_statement_ids.unlink()

        summary = match_data.get('summary', {})
        vals = {
            'ai_match_summary_fit': summary.get('overall_fit', 'N/A'),
            'ai_match_summary_strengths': "\n".join(
                f"- {s}" for s in summary.get('key_strengths', [])
            ),
            'ai_match_summary_gaps': "\n".join(
                f"- {g}" for g in summary.get('missing_gaps', [])
            ),
        }

        # Score map for the AI-generated fit field
        score_map = {
            'not_fit': 0.0,
            'poor_fit': 25.0,
            'fit': 50.0,
            'good_fit': 80.0,
            'excellent_fit': 100.0
        }
        # Only process statements for requirements that actually exist on the job
        valid_req_ids = set(self.job_id.requirement_statement_ids.ids)
        stmts = []

        for m in match_data.get('statement_matches', []):
            rid = m.get('requirement_id')
            if rid in valid_req_ids:
                fit = m.get('match_fit', 'not_fit')
                stmts.append((0, 0, {
                    'applicant_id': self.id,
                    'requirement_id': rid,
                    'explanation': m.get('explanation', ''),
                    'match_fit': fit,
                    'match_score': score_map.get(fit, 0.0)
                }))

        if stmts:
            vals['ai_match_statement_ids'] = stmts
        self.write(vals)