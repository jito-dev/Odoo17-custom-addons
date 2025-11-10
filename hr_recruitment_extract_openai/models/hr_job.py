# -*- coding: utf-8 -*-
import base64
import json
import logging
import odoo
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrJob(models.Model):
    _inherit = 'hr.job'

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
        help="CVs that have been successfully processed and had an applicant created."
    )
    
    processed_cv_count = fields.Integer(
        string="Processed Count", 
        readonly=True, 
        copy=False, 
        default=0,
        help="Number of CVs successfully processed in the last run."
    )
    failed_cv_count = fields.Integer(
        string="Failed Count", 
        readonly=True, 
        copy=False, 
        default=0,
        help="Number of CVs that failed processing in the last run."
    )
    total_cv_count = fields.Integer(
        string="Total to Process", 
        readonly=True, 
        copy=False, 
        default=0,
        help="Total CVs in the last processing run."
    )

    # Robust "In Progress" state (with sudo())
    queue_job_uuid = fields.Char(string="Queue Job UUID", copy=False, readonly=True)
    job_state = fields.Selection(
        [('pending', 'Pending'), ('enqueued', 'Enqueued'), ('started', 'Started'), ('done', 'Done'), ('failed', 'Failed')],
        string='Job State',
        compute='_compute_job_state',
        store=False,
        readonly=True
    )
    processing_in_progress = fields.Boolean(
        string="Processing CVs",
        compute="_compute_processing_in_progress",
        help="Indicates that CVs are currently being processed in the background."
    )

    processing_complete = fields.Boolean(
        string="Processing Complete",
        default=False,
        copy=False,
        help="Indicates that a bulk processing has been completed."
    )
    processing_failed = fields.Boolean(
        string="Processing Failed",
        default=False,
        copy=False,
        help="Indicates that one or more CVs failed during the last processing run."
    )

    processing_progress = fields.Integer(
        string="Progress",
        compute='_compute_processing_progress',
        help="Percentage of CVs processed."
    )

    @api.depends('processed_cv_count', 'failed_cv_count', 'total_cv_count')
    def _compute_processing_progress(self):
        """
        Computes the progress percentage based on the reliable counters.
        This will update as each job commits.
        """
        for job in self:
            if job.total_cv_count > 0:
                total_finished = job.processed_cv_count + job.failed_cv_count
                job.processing_progress = (total_finished * 100) / job.total_cv_count
            else:
                job.processing_progress = 0

    # Compute methods for queue.job state (with sudo())
    @api.depends('queue_job_uuid')
    def _compute_job_state(self):
        """Find the queue.job record from the stored UUID and get its state."""
        for job in self:
            if job.queue_job_uuid:
                # Use sudo() to bypass access rules for reading queue.job
                job_record = self.env['queue.job'].sudo().search(
                    [('uuid', '=', job.queue_job_uuid)], limit=1
                )
                job.job_state = job_record.state if job_record else False
            else:
                job.job_state = False

    @api.depends('job_state')
    def _compute_processing_in_progress(self):
        """
        Processing is in progress if there is an active queue job
        in a running state. If state is 'failed', this becomes False.
        """
        for job in self:
            if job.job_state in ('pending', 'enqueued', 'started'):
                job.processing_in_progress = True
            else:
                job.processing_in_progress = False

    # --- Button Actions ---

    def action_process_cvs(self):
        """
        Triggered by the 'Add Candidates' button.
        Launches one background job to manage the processing.
        """
        self.ensure_one()

        try:
            # Database lock to prevent double-clicks
            self.env.cr.execute('SELECT * FROM hr_job WHERE id = %s FOR UPDATE', (self.id,))
            
            # Re-browse to get the freshest data
            job = self.browse(self.id)

            # Perform checks on the FRESH record
            if job.processing_in_progress:
                raise UserError(_("Processing is already in progress. Please wait until it is complete."))
            
            if not job.cv_attachment_ids:
                raise UserError(_("Please attach CV files before processing."))

            # Calculate which attachments to process
            attachments_to_process = job.cv_attachment_ids - job.processed_cv_attachment_ids

            if not attachments_to_process:
                raise UserError(_("All attached CVs have already been processed successfully. Please delete the attached files to start a new batch."))

            _logger.info(
                "--- Button 'action_process_cvs' TRIGGERED by user %s for %s CVs ---",
                self.env.user.name, len(attachments_to_process)
            )

            # Pass the user ID and attachment IDs to the job
            job_record = job.with_delay()._process_cvs_thread(self.env.user.id, attachments_to_process.ids)

            # Write flags, counters, and job UUID.
            job.write({
                'processed_cv_attachment_ids': [(5, 0, 0)],
                'processed_cv_count': 0,
                'failed_cv_count': 0,
                'total_cv_count': len(attachments_to_process),
                'processing_complete': False,
                'processing_failed': False,
                'queue_job_uuid': job_record.uuid, # Store the UUID
            })

            # Return a toast notification to the user
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Processing Started'),
                    'message': _(
                        'Processing has started for %s CV(s). You will be notified upon completion.',
                        len(attachments_to_process)
                    ),
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        except Exception:
            # The transaction will roll back, releasing the lock.
            raise


    def action_delete_cv_attachments(self):
        """
        Triggered by the 'Delete Attached Files' button.
        Removes the attachments from the job and resets all flags.
        """
        self.ensure_one()
        attachment_count = len(self.cv_attachment_ids)
        
        # Unlink the attachments themselves
        if self.cv_attachment_ids:
            self.cv_attachment_ids.unlink()
        
        # Clear the m2m relation and reset flags
        self.write({
            'cv_attachment_ids': [(5, 0, 0)],
            'processed_cv_attachment_ids': [(5, 0, 0)],
            'processing_complete': False,
            'processing_failed': False,
            'queue_job_uuid': False,
            'processed_cv_count': 0,
            'failed_cv_count': 0,
            'total_cv_count': 0,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Files Deleted'),
                'message': _('%s attached CVs for this job have been deleted.', attachment_count),
                'type': 'success',
                'sticky': False,
            }
        }

    def _notify_user(self, user_id, params):
        """Helper to send a notification to a specific user."""
        try:
            # Use a new cursor to ensure notification is sent
            with odoo.registry(self.env.cr.dbname).cursor() as notify_cr:
                notify_env = api.Environment(notify_cr, self.env.uid, self.env.context)
                user = notify_env['res.users'].browse(user_id)
                if user.partner_id:
                    notify_env['bus.bus']._sendone(user.partner_id, 'simple_notification', params)
                notify_cr.commit()
        except Exception as e:
            _logger.error("Failed to send notification to user %s: %s", user_id, str(e))

    # --- Background Processing ---

    def _process_cvs_thread(self, user_id, attachment_ids_to_process):
        """
        This method runs in the background via the Odoo job queue.
        It processes CVs one by one, creating a new transaction for each,
        so that applicants and progress appear immediately.
        """
        self.ensure_one()
        
        attachments = self.env['ir.attachment'].browse(attachment_ids_to_process)
        
        total_success = 0
        total_fail = 0
        errors = []
        
        for att in attachments:
            try:
                # --- NEW TRANSACTION BLOCK ---
                # This block runs in its own, independent transaction.
                # It will commit on success or rollback on failure.
                with odoo.registry(self.env.cr.dbname).cursor() as new_cr:
                    # Create a new env with the new cursor
                    new_env = api.Environment(new_cr, self.env.uid, self.env.context)
                    
                    # Lock the job row to prevent race conditions
                    new_env.cr.execute('SELECT * FROM hr_job WHERE id = %s FOR UPDATE', (self.id,))
                    
                    job_in_new_tx = new_env['hr.job'].browse(self.id)
                    att_in_new_tx = new_env['ir.attachment'].browse(att.id)
                    
                    try:
                        # --- Main Work (in new transaction) ---
                        _logger.info(f"Processing CV: {att_in_new_tx.name} for job {job_in_new_tx.name}")
                        
                        if not att_in_new_tx.datas:
                            raise UserError(_("Skipping CV {att.name}: Attachment data is empty."))

                        ApplicantEnv_in_new_tx = new_env['hr.applicant']
                        AttachmentEnv_in_new_tx = new_env['ir.attachment']

                        response_text = ApplicantEnv_in_new_tx._openai_call_for_cv(att_in_new_tx)
                        
                        log_id = f"job_{job_in_new_tx.id}_att_{att_in_new_tx.id}"
                        data_dict = ApplicantEnv_in_new_tx._parse_openai_response(response_text, record_id=log_id)

                        applicant_name_str = data_dict.get('name') or att_in_new_tx.name.rsplit('.', 1)[0]
                        
                        create_vals = {
                            'name': _("%s's Application") % applicant_name_str,
                            'partner_name': data_dict.get('name'),
                            'email_from': data_dict.get('email'),
                            'partner_phone': data_dict.get('phone'),
                            'job_id': job_in_new_tx.id,
                            'openai_extract_state': 'done',
                            'openai_extract_status': _('Created from bulk import. Processing data...'),
                        }
                        
                        new_applicant = ApplicantEnv_in_new_tx.create(create_vals)
                        _logger.info(f"Created new applicant: {new_applicant.name} (ID: {new_applicant.id})")

                        status_msg = new_applicant._process_extracted_cv_data(data_dict)
                        new_applicant.write({'openai_extract_status': status_msg})

                        AttachmentEnv_in_new_tx.create({
                            'name': att_in_new_tx.name,
                            'datas': att_in_new_tx.datas,
                            'res_model': 'hr.applicant',
                            'res_id': new_applicant.id,
                        })
                        
                        # Write success progress (in the same new transaction)
                        job_in_new_tx.write({
                            'processed_cv_count': job_in_new_tx.processed_cv_count + 1,
                            'processed_cv_attachment_ids': [(4, att_in_new_tx.id)]
                        })
                        
                        total_success += 1

                    except Exception as e:
                        # The individual CV failed
                        _logger.error(f"Failed to process CV {att.name} for job {self.name}: {e}", exc_info=True)
                        total_fail += 1
                        errors.append(f"{att.name}: {str(e)}") # Collect the error message
                        
                        # Update failure count in this transaction
                        job_in_new_tx.write({
                            'failed_cv_count': job_in_new_tx.failed_cv_count + 1
                        })
                        # We do NOT re-raise, so the transaction commits the failure count
                    
                    # The `with` block finishes here and `new_cr` is automatically committed.

            except Exception as e_tx:
                # This catches a critical error *creating the new transaction*
                _logger.error(f"Failed to create new transaction for CV {att.name}: {e_tx}", exc_info=True)
                total_fail += 1
                errors.append(f"{att.name}: {str(e_tx)}")
                # We must update the count in a *new* failsafe transaction
                try:
                    with odoo.registry(self.env.cr.dbname).cursor() as fail_cr:
                        fail_env = api.Environment(fail_cr, self.env.uid, self.env.context)
                        fail_env.cr.execute('SELECT * FROM hr_job WHERE id = %s FOR UPDATE', (self.id,))
                        job_in_fail_tx = fail_env['hr.job'].browse(self.id)
                        job_in_fail_tx.write({
                            'failed_cv_count': job_in_fail_tx.failed_cv_count + 1
                        })
                        fail_cr.commit()
                except Exception as e_fail_tx:
                    _logger.critical(f"TOTAL FAILURE: Could not even record failure for job {self.id}: {e_fail_tx}")
        
        # --- End of loop ---

        # Finally, clean up the job state and send notification
        try:
            with odoo.registry(self.env.cr.dbname).cursor() as final_cr:
                final_env = api.Environment(final_cr, self.env.uid, self.env.context)
                final_env.cr.execute('SELECT * FROM hr_job WHERE id = %s FOR UPDATE', (self.id,))
                final_job = final_env['hr.job'].browse(self.id)
                
                job_failed = total_fail > 0
                final_vals = {
                    'processing_complete': True,
                    'processing_failed': job_failed,
                    'queue_job_uuid': False, # Clear the job UUID
                }
                final_job.write(final_vals)
                final_cr.commit()

                # Send final notification
                message = _("CV processing finished for job '%s'.\n%s applicants created.\n%s failed.", 
                            final_job.name, total_success, total_fail)
                if errors:
                    message += _("\n\nErrors:\n- ") + "\n- ".join(errors)

                params = {
                    'title': _('Processing Complete') if not job_failed else _('Processing Finished with Errors'),
                    'message': message,
                    'type': 'success' if not job_failed else 'warning',
                    'sticky': job_failed,
                }
                final_job._notify_user(user_id, params)

        except Exception as e_finally:
            _logger.error(f"Critical error during finally block for job {self.name}: {e_finally}", exc_info=True)
            # Failsafe notification
            params = {
                'title': _('Processing Finished with Errors'),
                'message': _("Processing finished, but a critical error occurred during finalization: %s", str(e_finally)),
                'type': 'danger',
                'sticky': True,
            }
            self._notify_user(user_id, params)