# -*- coding: utf-8 -*-
from odoo import fields, models, api

class HrApplicantExperience(models.Model):
    """
    Stores detailed work experience extracted from CV with
    AI-enriched credibility and relevance scores.
    """
    _name = 'hr.applicant.experience'
    _description = 'Applicant Work Experience & Credibility'
    _order = 'start_date desc, id desc'

    applicant_id = fields.Many2one(
        'hr.applicant',
        string='Applicant',
        required=True,
        ondelete='cascade'
    )

    # --- Column 1: Applicant Experience Data ---
    role = fields.Char(string="Role")
    company_name = fields.Char(string="Company")
    project_name = fields.Char(string="Project")
    
    start_date_str = fields.Char(string="Start Date (Txt)")
    end_date_str = fields.Char(string="End Date (Txt)")
    duration_str = fields.Char(string="Duration Display")
    duration_months = fields.Integer(string="Duration (Months)", default=0)
    
    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")

    description = fields.Text(string="Description / Tasks")

    # --- Column 2: Relevance & Scores ---
    # Scores
    experience_relevance = fields.Float(string="Exp Relevance %", default=0.0)
    project_relevance = fields.Float(string="Project Relevance %", default=0.0)
    company_relevance = fields.Float(string="Company Relevance %", default=0.0)
    company_credibility = fields.Float(string="Company Credibility %", default=0.0)

    # Explanations
    experience_relevance_explanation = fields.Text(
        string="Exp Relevance Explanation",
        help="AI justification for the experience relevance score."
    )
    project_relevance_explanation = fields.Text(
        string="Project Relevance Explanation",
        help="AI justification for the project relevance score."
    )
    company_relevance_explanation = fields.Text(
        string="Company Relevance Explanation",
        help="AI justification for the company relevance score."
    )
    company_credibility_explanation = fields.Text(
        string="Company Credibility Explanation",
        help="AI justification for the company credibility score."
    )
    
    # Calculated Time Confidence (0, 1, 3, 6, 10 based on months)
    time_confidence_score = fields.Integer(
        string="Time Confidence", 
        compute="_compute_time_confidence",
        store=True,
        readonly=False 
    )

    # --- Column 3: Weights ---
    weight_experience = fields.Float(string="Weight Exp", default=1.0)
    weight_project = fields.Float(string="Weight Proj", default=1.0)
    weight_company = fields.Float(string="Weight Comp", default=1.0)
    weight_credibility = fields.Float(string="Weight Cred", default=1.0)

    # --- Column 4: Company Info & Summary ---
    comp_website = fields.Char(string="Website")
    comp_linkedin = fields.Char(string="LinkedIn")
    comp_industry = fields.Char(string="Industry")
    comp_domain = fields.Char(string="Domain")
    comp_geo = fields.Char(string="Geo/Team")
    comp_team_size = fields.Char(string="Team Size")
    comp_type = fields.Char(string="Type")
    comp_clients = fields.Text(string="Main Clients")

    comp_positive_signals = fields.Text(string="Positive Signals")
    comp_areas_to_verify = fields.Text(string="Areas to Verify")
    comp_summary = fields.Text(string="Company Summary")

    # --- Final Line Calculation ---
    total_line_score = fields.Float(
        string="Line Score",
        compute="_compute_total_line_score",
        store=True,
        readonly=False, # Allow manual override if really needed, though compute will overwrite on change
        help="Calculated score for this specific experience entry."
    )

    @api.depends('duration_months')
    def _compute_time_confidence(self):
        for record in self:
            m = record.duration_months
            if m < 3:
                score = 0
            elif m <= 6:
                score = 1
            elif m <= 12:
                score = 3
            elif m <= 24:
                score = 6
            else:
                score = 10
            record.time_confidence_score = score

    @api.depends(
        'experience_relevance', 'project_relevance', 
        'company_relevance', 'company_credibility',
        'weight_experience', 'weight_project', 
        'weight_company', 'weight_credibility',
        'time_confidence_score'
    )
    @api.onchange(
        'experience_relevance', 'project_relevance', 
        'company_relevance', 'company_credibility',
        'weight_experience', 'weight_project', 
        'weight_company', 'weight_credibility',
        'time_confidence_score'
    )
    def _compute_total_line_score(self):
        """
        Computes the total score for this line.
        Triggered by DB changes (depends) and UI edits (onchange).
        """
        for record in self:
            s1 = record.experience_relevance * record.weight_experience
            s2 = record.project_relevance * record.weight_project
            s3 = record.company_relevance * record.weight_company
            s4 = record.company_credibility * record.weight_credibility
            
            base_sum = s1 * s2 * s3 * s4
            
            if base_sum:
                 record.total_line_score = base_sum * record.time_confidence_score / 10000000.0
            else:
                 record.total_line_score = 0.0