# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools.misc import formatLang


class HrJob(models.Model):
    _inherit = 'hr.job'

    # --- Job Context fields (added to Job Context tab) ---
    job_title = fields.Char(
        string='Job Title',
        help='Title for the vacancy / job posting',
    )
    job_description_context = fields.Html(
        string='Job Description',
        sanitize_attributes=False,
        help='Detailed description of the job: requirements, expected activities, responsibilities, etc.',
    )
    experience_years_min = fields.Integer(
        string='Experience From (years)',
        help='Minimum years of experience required (optional)',
    )
    experience_years_max = fields.Integer(
        string='Experience To (years)',
        help='Maximum years of experience expected (optional)',
    )

    # --- Process details fields ---
    process_time_to_answer = fields.Char(
        string='Time to Answer',
        help='Expected response time, e.g. "2 open days"',
    )
    process_steps = fields.Text(
        string='Process Steps',
        help='Hiring process steps, one per line. e.g.:\n1 Phone Call\n1 Onsite Interview',
    )
    process_days_to_offer = fields.Char(
        string='Days to get an Offer',
        help='Time to receive an offer, e.g. "4 Days after Interview"',
    )

    # --- Feature toggle ---
    use_published_config = fields.Boolean(
        string='Use Published Job Configuration',
        default=False,
        help='Enable dynamic vacancy page built from Job Context data',
    )

    # --- Computed fields (always from Job Context) ---
    published_title = fields.Char(
        string='Published Title',
        compute='_compute_published_title',
    )
    published_short_desc = fields.Html(
        string='Published Short Description',
        compute='_compute_published_short_desc',
        sanitize_attributes=False,
    )
    published_long_desc = fields.Html(
        string='Published Long Description',
        compute='_compute_published_long_desc',
        sanitize_attributes=False,
    )
    published_salary_display = fields.Char(
        string='Salary Display',
        compute='_compute_published_salary_display',
    )
    published_experience_display = fields.Char(
        string='Experience Display',
        compute='_compute_published_experience_display',
    )

    @api.depends('job_title')
    def _compute_published_title(self):
        for job in self:
            job.published_title = job.job_title

    @api.depends('description')
    def _compute_published_short_desc(self):
        for job in self:
            job.published_short_desc = job.description

    @api.depends('job_description_context')
    def _compute_published_long_desc(self):
        for job in self:
            job.published_long_desc = job.job_description_context

    @api.depends(
        'salary_monthly_min', 'salary_monthly_max',
        'salary_fiat_currency_id', 'salary_currency_mode', 'salary_crypto_currency',
    )
    def _compute_published_salary_display(self):
        for job in self:
            sal_min = job.salary_monthly_min
            sal_max = job.salary_monthly_max
            if not sal_min and not sal_max:
                job.published_salary_display = ''
                continue

            if job.salary_currency_mode == 'crypto':
                symbol = job.salary_crypto_currency or 'USDT'
                fmt_min = '%s %s' % (format(sal_min, ',.0f'), symbol) if sal_min else ''
                fmt_max = '%s %s' % (format(sal_max, ',.0f'), symbol) if sal_max else ''
            else:
                currency = job.salary_fiat_currency_id
                if currency:
                    fmt_min = formatLang(self.env, sal_min, currency_obj=currency) if sal_min else ''
                    fmt_max = formatLang(self.env, sal_max, currency_obj=currency) if sal_max else ''
                else:
                    fmt_min = '$%s' % format(sal_min, ',.0f') if sal_min else ''
                    fmt_max = '$%s' % format(sal_max, ',.0f') if sal_max else ''

            if sal_min and sal_max:
                job.published_salary_display = '%s - %s / mo' % (fmt_min, fmt_max)
            elif sal_min:
                job.published_salary_display = 'From %s / mo' % fmt_min
            else:
                job.published_salary_display = 'Up to %s / mo' % fmt_max

    @api.depends('experience_years_min', 'experience_years_max')
    def _compute_published_experience_display(self):
        for job in self:
            exp_min = job.experience_years_min
            exp_max = job.experience_years_max
            if not exp_min and not exp_max:
                job.published_experience_display = ''
            elif exp_min and exp_max:
                if exp_min == exp_max:
                    job.published_experience_display = '%d years of experience' % exp_min
                else:
                    job.published_experience_display = '%d - %d years of experience' % (exp_min, exp_max)
            elif exp_min:
                job.published_experience_display = '%d+ years of experience' % exp_min
            else:
                job.published_experience_display = 'Up to %d years of experience' % exp_max
