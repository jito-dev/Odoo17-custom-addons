# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from dateutil import parser
from datetime import date

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
    experience_relevance = fields.Float(
        string="Experience Relevance (%)", 
        default=0.0,
        digits=(16, 2),
        help="Relevance of the role's responsibilities to job requirements (0-100%)."
    )
    project_relevance = fields.Float(
        string="Project Relevance (%)", 
        default=0.0,
        digits=(16, 2),
        help="Relevance of the project work to job requirements (0-100%)."
    )
    company_relevance = fields.Float(
        string="Company Relevance (%)", 
        default=0.0,
        digits=(16, 2),
        help="Relevance of the company's industry to job requirements (0-100%)."
    )
    company_credibility = fields.Float(
        string="Company Credibility (%)", 
        default=0.0,
        digits=(16, 2),
        help="Reputation and stability of the company (0-100%)."
    )

    # Explanations
    experience_relevance_explanation = fields.Text(
        string="Experience Relevance Explanation",
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
    
    # Calculated Time Confidence (0 to 10 scale)
    time_confidence_score = fields.Float(
        string="Time Confidence (0-10)", 
        compute="_compute_time_confidence",
        store=True,
        readonly=False, # Allows manual override
        help="Score based on duration: 0.5 (<3m) to 10.0 (24m+)."
    )

    # Recency Scoring
    years_ago = fields.Float(
        string="Years Ago",
        compute="_compute_recency_score",
        store=True,
        digits=(16, 1),
        help="How many years have passed since this job ended."
    )
    
    recency_score = fields.Float(
        string="Recency Score (%)",
        compute="_compute_recency_score",
        store=True,
        digits=(16, 2),
        help="Score calculated based on how recent the experience is. (100% for current, decreasing for older)."
    )

    # --- Column 3: Weights (Readonly from Job Configuration) ---
    weight_experience = fields.Float(
        string="Exp Relevance Weight", 
        default=1.0,
        readonly=True,
        help="Weight from Job Position. Change in Job Position -> Experience Weights tab."
    )
    weight_project = fields.Float(
        string="Project Relevance Weight", 
        default=1.0,
        readonly=True,
        help="Weight from Job Position. Change in Job Position -> Experience Weights tab."
    )
    weight_company = fields.Float(
        string="Company Relevance Weight", 
        default=1.0,
        readonly=True,
        help="Weight from Job Position. Change in Job Position -> Experience Weights tab."
    )
    weight_credibility = fields.Float(
        string="Company Credibility Weight", 
        default=1.0,
        readonly=True,
        help="Weight from Job Position. Change in Job Position -> Experience Weights tab."
    )

    # --- Column 4: Company Info & Summary ---
    comp_website = fields.Char(string="Website")
    comp_linkedin = fields.Char(string="LinkedIn")
    comp_industry = fields.Char(string="Business Industry")
    comp_domain = fields.Char(string="Business Domain")
    comp_geo = fields.Char(string="Geo/Team Location")
    comp_team_size = fields.Char(string="Team Size")
    comp_type = fields.Char(string="Type (Product/Outsource)")
    comp_clients = fields.Text(string="Main Clients")

    comp_positive_signals = fields.Text(string="Positive Signals")
    comp_areas_to_verify = fields.Text(string="Areas to Verify")
    comp_summary = fields.Text(string="Company Summary")

    # --- Final Line Calculation ---
    total_line_score = fields.Float(
        string="Experience Line Score",
        compute="_compute_total_line_score",
        store=True,
        digits=(16, 2),
        readonly=False,
        help="Final points: (Score1*W1 * ... * TimeFactor * RecencyFactor)."
    )

    # --- Onchange Validations ---

    @api.onchange('duration_months')
    def _onchange_duration_months(self):
        """Immediately revert invalid duration values."""
        # 0 is allowed as "empty"
        if self.duration_months == 0:
            return
        
        # Check range (covers negatives too since < 3 includes negative numbers)
        if self.duration_months < 3 or self.duration_months > 900:
             # Revert to the stored value (or 0 if new/not saved)
             old_value = self._origin.duration_months if self._origin else 0
             self.duration_months = old_value
             
             return {
                'warning': {
                    'title': _("Invalid Duration"),
                    'message': _("Duration must be between 3 and 900 months. The value has been reverted to its previous state.")
                }
            }

    @api.onchange('time_confidence_score')
    def _onchange_time_confidence_score(self):
        """Immediately revert invalid time confidence scores."""
        if self.time_confidence_score < 0.0 or self.time_confidence_score > 10.0:
            # Revert to the stored value (or 0.0 if new/not saved)
            old_value = self._origin.time_confidence_score if self._origin else 0.0
            self.time_confidence_score = old_value
            return {
                'warning': {
                    'title': _("Invalid Score"),
                    'message': _("Time Confidence Score must be between 0 and 10. The value has been reverted.")
                }
            }

    @api.onchange('experience_relevance', 'project_relevance', 
                  'company_relevance', 'company_credibility', 'recency_score')
    def _onchange_scores(self):
        """Immediately revert invalid percentage scores."""
        for field in ['experience_relevance', 'project_relevance', 
                      'company_relevance', 'company_credibility', 'recency_score']:
            val = getattr(self, field)
            if val < 0.0 or val > 100.0:
                # Revert to the stored value (or 0.0 if new/not saved)
                old_val = getattr(self._origin, field) if self._origin else 0.0
                setattr(self, field, old_val)
                return {
                    'warning': {
                        'title': _("Invalid Score"),
                        'message': _("Score must be between 0 and 100. The value has been reverted.")
                    }
                }

    # --- Backend Constraints ---

    @api.constrains('duration_months')
    def _check_duration_months(self):
        """Validate duration in months."""
        for record in self:
            if record.duration_months < 0:
                raise ValidationError(_("Duration in months cannot be negative."))
            if record.duration_months != 0 and (record.duration_months < 3 or record.duration_months > 900):
                raise ValidationError(_("Duration in months must be between 3 and 900."))

    @api.constrains('experience_relevance', 'project_relevance', 
                    'company_relevance', 'company_credibility', 'recency_score')
    def _check_percentage_scores(self):
        """Validate percentage scores."""
        for record in self:
            scores = [
                record.experience_relevance,
                record.project_relevance,
                record.company_relevance,
                record.company_credibility,
                record.recency_score
            ]
            if any(score < 0.0 or score > 100.0 for score in scores):
                raise ValidationError(_("Relevance, Credibility and Recency scores must be between 0 and 100%."))

    @api.constrains('time_confidence_score')
    def _check_time_confidence_score(self):
        """Validate time confidence score."""
        for record in self:
            if record.time_confidence_score < 0.0 or record.time_confidence_score > 10.0:
                raise ValidationError(_("Time Confidence Score must be between 0 and 10."))

    # --- Actions ---

    def action_open_score_wizard(self):
        """
        Opens a popup wizard to edit the score for the field specified in context.
        """
        self.ensure_one()
        field_name = self.env.context.get('field_name')
        label = self.env.context.get('label')
        
        # Mapping explanation fields
        explanation_field_map = {
            'experience_relevance': 'experience_relevance_explanation',
            'project_relevance': 'project_relevance_explanation',
            'company_relevance': 'company_relevance_explanation',
            'company_credibility': 'company_credibility_explanation',
        }
        explanation_field = explanation_field_map.get(field_name)
        
        return {
            'name': f'Update {label}',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.recruitment.experience.score.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_experience_id': self.id,
                'default_field_to_edit': field_name,
                'default_score': getattr(self, field_name),
                'default_explanation': getattr(self, explanation_field) if explanation_field else '',
                'default_explanation_field': explanation_field,
            }
        }

    def action_delete_experience(self):
        """
        Deletes the experience record.
        """
        for record in self:
            record.unlink()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    # --- Compute Methods ---

    @api.depends('duration_months')
    def _compute_time_confidence(self):
        """
        Calculates a time confidence score (0-10) based on the duration in months.
        This provides a weight factor for longer-term experience.
        """
        for record in self:
            m = record.duration_months
            if m < 3:
                # Less than 3 months - very low confidence
                score = 0.5
            elif m <= 6:
                # 3-6 months - basic contribution
                score = 1.0
            elif m <= 12:
                # 7-12 months - basic project cycle completion
                score = 3.0
            elif m <= 24:
                # 13-24 months (1-2 years) - solid contribution
                score = 6.0
            else:
                # > 24 months (2+ years) - strong commitment/stability
                score = 10.0
            record.time_confidence_score = score

    @api.depends('end_date_str', 'end_date')
    def _compute_recency_score(self):
        """
        Parses the end date to determine how long ago this experience occurred.
        Applies a decay factor:
        - Present / < 1 year: 100%
        - 1-3 years: 90%
        - 3-5 years: 80%
        - 5-10 years: 60%
        - > 10 years: 40%
        """
        # Get today's date
        today = date.today()

        for record in self:
            years_ago = 0.0
            end_dt = record.end_date

            # Parse end date string if end_date is not set
            if not end_dt and record.end_date_str:
                txt = record.end_date_str.lower().strip()

                # Check for 'present', 'now' or 'current'
                if 'present' in txt or 'now' in txt or 'current' in txt:
                    years_ago = 0.0
                else:
                    try:
                        # Attempt to parse the date
                        parsed_dt = parser.parse(txt, fuzzy=True).date()
                        delta = today - parsed_dt
                        years_ago = max(delta.days / 365.25, 0.0)
                    except Exception:
                        years_ago = 1.0 
            
            # Calculate years_ago if end_date is set
            elif end_dt:
                 delta = today - end_dt
                 years_ago = max(delta.days / 365.25, 0.0)

            # Set the years_ago field
            record.years_ago = years_ago

            # Determine recency score based on years_ago
            if years_ago <= 1.0:
                score = 100.0 # Current or within last year
            elif years_ago <= 3.0:
                score = 90.0 # 1-3 years ago
            elif years_ago <= 5.0:
                score = 80.0 # 3-5 years ago
            elif years_ago <= 10.0:
                score = 60.0 # 5-10 years ago
            else:
                score = 40.0 # More than 10 years ago
            
            record.recency_score = score

    @api.depends(
        'experience_relevance', 'project_relevance', 
        'company_relevance', 'company_credibility',
        'recency_score',
        'applicant_id.job_id.weight_experience',
        'applicant_id.job_id.weight_project',
        'applicant_id.job_id.weight_company',
        'applicant_id.job_id.weight_credibility',
        'time_confidence_score'
    )
    def _compute_total_line_score(self):
        """
        Computes the total score for this line using the multiplicative formula.
        S1*W1 * S2*W2 * S3*W3 * S4*W4 * TimeConfidenceFactor * RecencyFactor
        """
        for record in self:
            # Get job weights
            job = record.applicant_id.job_id
            w1 = job.weight_experience if job else 1.0
            w2 = job.weight_project if job else 1.0
            w3 = job.weight_company if job else 1.0
            w4 = job.weight_credibility if job else 1.0
            
            # Store weights in record for reference
            record.weight_experience = w1
            record.weight_project = w2
            record.weight_company = w3
            record.weight_credibility = w4
            
            # Normalize factors
            time_confidence_factor = record.time_confidence_score / 10.0 # Normalize 0-10 to 0-1
            recency_factor = record.recency_score / 100.0 # Normalize 0-100 to 0-1

            # Compute final score               
            final_score = (
                (record.experience_relevance * w1) *
                (record.project_relevance * w2) *
                (record.company_relevance * w3) *
                (record.company_credibility * w4) *
                time_confidence_factor *
                recency_factor
            )
            
            if final_score > 0:
                record.total_line_score = final_score ** (1/4)
            else:
                record.total_line_score = 0.0