# -*- coding: utf-8 -*-
import base64
import json
import odoo
import openai
from unittest.mock import patch, MagicMock

from odoo import _
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError

# Import the prompt constant
from odoo.addons.hr_recruitment_extract_openai.models.hr_applicant import OPENAI_CV_EXTRACTION_PROMPT

# Mock JSON responses
MOCK_RESPONSE_JANE = {
    "name": "Jane Smith",
    "email": "jane.smith@example.com",
    "phone": "111-222-3333",
    "linkedin": "https://linkedin.com/in/janesmith",
    "degree": "Master's in Marketing",
    "skills": [
        {"type": "Marketing", "skill": "SEO", "level": "Advanced (80%)"}
    ]
}

MOCK_RESPONSE_MIKE = {
    "name": "Mike Johnson",
    "email": "mike.johnson@example.com",
    "phone": "444-555-6666",
    "linkedin": "https.linkedin.com/in/mikejohnson",
    "degree": "PhD in Data Science",
    "skills": [
        {"type": "Programming Languages", "skill": "R", "level": "Expert (100%)"}
    ]
}

class TestHrJobBulkOpenAI(TransactionCase):
    """
    Test suite for the `hr.job` bulk CV processing functionality.
    Mocks the queue_job and OpenAI calls.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Mock the check for hr_recruitment_skills being installed
        mock_module = MagicMock()
        mock_module.state = 'installed'
        
        cls.mock_get_patcher = patch.object(
            type(cls.env['ir.module.module']), 
            '_get', 
            MagicMock(return_value=mock_module)
        )
        cls.mock_get_patcher.start()

        cls.job = cls.env['hr.job'].create({
            'name': 'Test Bulk Import Job',
        })

        cls.attachment_1 = cls.env['ir.attachment'].create({
            'name': 'jane_cv.pdf',
            'datas': base64.b64encode(b'Jane Smith PDF content'),
            'mimetype': 'application/pdf',
        })
        cls.attachment_2 = cls.env['ir.attachment'].create({
            'name': 'mike_cv.pdf',
            'datas': base64.b64encode(b'Mike Johnson PDF content'),
            'mimetype': 'application/pdf',
        })
        
        cls.job.cv_attachment_ids = [(6, 0, [cls.attachment_1.id, cls.attachment_2.id])]

        cls.env.company.write({
            'openai_cv_extract_mode': 'manual_send',
            'openai_api_key': 'fake_api_key',
            'openai_model': 'fake-model-name',
        })
        
        # Pre-create skill-related data
        cls.env['hr.skill.level'].create({
            'name': 'Beginner',
            'level_progress': 15,
        })
        cls.env['hr.recruitment.degree'].create({'name': "Master's in Marketing"})
        cls.env['hr.recruitment.degree'].create({'name': 'PhD in Data Science'})

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.mock_get_patcher.stop()

    def setUp(self):
        super().setUp()

        # 1. Patch commits/rollbacks
        self.commit_patcher = patch('odoo.sql_db.Cursor.commit', lambda *args, **kwargs: None)
        self.commit_patcher.start()
        self.rollback_patcher = patch('odoo.sql_db.Cursor.rollback', lambda *args, **kwargs: None)
        self.rollback_patcher.start()

        # 2. Patch `with_delay()` to run the job synchronously
        def mock_with_delay(self_recordset, *args, **kwargs):
            mock_delay_obj = MagicMock()
            
            # This explicitly mocks the method we expect to be called.
            def run_job_sync(*job_args, **job_kwargs):
                # self_recordset is the job record
                real_method = getattr(self_recordset, '_process_cvs_thread')
                # Run the real method with the captured arguments
                return real_method(*job_args, **job_kwargs)

            mock_delay_obj._process_cvs_thread = MagicMock(side_effect=run_job_sync)
            return mock_delay_obj

        self.delay_patcher = patch.object(
            type(self.env['hr.job']), 
            'with_delay',
            new=mock_with_delay,
        )
        self.delay_patcher.start()
 
        # 3. Patch the bus notification
        self.bus_patcher = patch.object(
            type(self.env['bus.bus']), 
            '_sendone', 
            MagicMock(return_value=True)
        )
        self.mock_bus_sendone = self.bus_patcher.start()

        # 4. Patch the `_openai_call_for_cv` to return different responses
        # We will set this up inside each test
        self.mock_openai_call_patcher = patch.object(
            type(self.env['hr.applicant']),
            '_openai_call_for_cv'
        )
        self.mock_openai_call = self.mock_openai_call_patcher.start()

        # 5. Patch `hr.applicant.create` to avoid complex dependencies
        # We need to test *what* is sent to create, not the create itself
        self.mock_applicant_create_patcher = patch.object(
            type(self.env['hr.applicant']),
            'create',
        )
        self.mock_applicant_create = self.mock_applicant_create_patcher.start()
        
        # Mock the `_process_extracted_cv_data` method to simplify testing
        self.mock_process_data_patcher = patch.object(
            type(self.env['hr.applicant']),
            '_process_extracted_cv_data',
            return_value="Mocked processing status."
        )
        self.mock_process_data = self.mock_process_data_patcher.start()

    def tearDown(self):
        self.mock_process_data_patcher.stop()
        self.mock_applicant_create_patcher.stop()
        self.mock_openai_call_patcher.stop()
        self.bus_patcher.stop()
        self.delay_patcher.stop()
        self.commit_patcher.stop()
        self.rollback_patcher.stop()
        super().tearDown()

    def test_01_successful_bulk_process(self):
        """Test a bulk process where all CVs are processed successfully."""
        
        # 1. Setup mocks
        # Return Jane's data for the first call, Mike's for the second
        self.mock_openai_call.side_effect = [
            json.dumps(MOCK_RESPONSE_JANE),
            json.dumps(MOCK_RESPONSE_MIKE)
        ]
        
        # Mock the return of the create method
        mock_applicant_jane = self.env['hr.applicant'].browse([1])
        mock_applicant_mike = self.env['hr.applicant'].browse([2])
        self.mock_applicant_create.side_effect = [
            mock_applicant_jane,
            mock_applicant_mike
        ]

        # 2. Run the action
        self.job.action_process_cvs()

        # Use invalidate_recordset to get DB updates
        self.job.invalidate_recordset()

        # 3. Check job state
        self.assertEqual(self.job.processing_in_progress, False)
        self.assertEqual(self.job.processing_complete, True)

        # 4. Check API calls
        self.assertEqual(self.mock_openai_call.call_count, 2)
        self.mock_openai_call.assert_any_call(self.attachment_1)
        self.mock_openai_call.assert_any_call(self.attachment_2)

        # 5. Check applicant creation calls
        self.assertEqual(self.mock_applicant_create.call_count, 2)
        
        self.mock_applicant_create.assert_any_call({
            'name': "Jane Smith's Application",
            'partner_name': 'Jane Smith',
            'email_from': 'jane.smith@example.com',
            'partner_phone': '111-222-3333',
            'job_id': self.job.id,
            'openai_extract_state': 'done',
            'openai_extract_status': _('Created from bulk import. Processing data...'),
        })
        self.mock_applicant_create.assert_any_call({
            'name': "Mike Johnson's Application",
            'partner_name': 'Mike Johnson',
            'email_from': 'mike.johnson@example.com',
            'partner_phone': '444-555-6666',
            'job_id': self.job.id,
            'openai_extract_state': 'done',
            'openai_extract_status': _('Created from bulk import. Processing data...'),
        })
        
        # 6. Check data processing calls
        self.mock_process_data.assert_any_call(MOCK_RESPONSE_JANE)
        self.mock_process_data.assert_any_call(MOCK_RESPONSE_MIKE)
        
        # 7. Check final notification
        self.mock_bus_sendone.assert_called_once()
        call_args = self.mock_bus_sendone.call_args[0]
        self.assertEqual(call_args[1], 'simple_notification')
        self.assertEqual(call_args[2]['type'], 'success')
        self.assertIn("2 applicants created", call_args[2]['message'])
        self.assertIn("0 failed", call_args[2]['message'])

    def test_02_partial_failure_bulk_process(self):
        """Test a bulk process where one CV fails."""

        # 1. Setup mocks
        # First call succeeds, second call raises an API error
        self.mock_openai_call.side_effect = [
            json.dumps(MOCK_RESPONSE_JANE),
            UserError("Test API Error on second CV")
        ]
        
        mock_applicant_jane = self.env['hr.applicant'].browse([1])
        self.mock_applicant_create.return_value = mock_applicant_jane

        # 2. Run the action
        self.job.action_process_cvs()
        
        # Use invalidate_recordset to get DB updates
        self.job.invalidate_recordset()

        # 3. Check job state
        self.assertEqual(self.job.processing_in_progress, False)
        self.assertEqual(self.job.processing_complete, True)

        # 4. Check API calls (should be 2)
        self.assertEqual(self.mock_openai_call.call_count, 2)

        # 5. Check applicant creation (should be 1)
        self.assertEqual(self.mock_applicant_create.call_count, 1)
        
        self.mock_applicant_create.assert_called_with({
            'name': "Jane Smith's Application",
            'partner_name': 'Jane Smith',
            'email_from': 'jane.smith@example.com',
            'partner_phone': '111-222-3333',
            'job_id': self.job.id,
            'openai_extract_state': 'done',
            'openai_extract_status': _('Created from bulk import. Processing data...'),
        })

        # 6. Check data processing (should be 1)
        self.mock_process_data.assert_called_once_with(MOCK_RESPONSE_JANE)

        # 7. Check final notification
        self.mock_bus_sendone.assert_called_once()
        call_args = self.mock_bus_sendone.call_args[0]
        self.assertEqual(call_args[1], 'simple_notification')
        self.assertEqual(call_args[2]['type'], 'warning')
        self.assertIn("1 applicants created", call_args[2]['message'])
        self.assertIn("1 failed", call_args[2]['message'])
        self.assertIn("Test API Error on second CV", call_args[2]['message'])

    def test_03_action_guards(self):
        """Test the safety guards on the action_process_cvs button."""
        
        # 1. Test no attachments
        self.job.cv_attachment_ids = False
        with self.assertRaises(UserError, msg="Should fail if no CVs are attached"):
            self.job.action_process_cvs()

        self.job.cv_attachment_ids = [(4, self.attachment_1.id)]

        # 2. Test processing_in_progress
        self.job.processing_in_progress = True
        with self.assertRaises(UserError, msg="Should fail if processing is in progress"):
            self.job.action_process_cvs()
            
        self.job.processing_in_progress = False

        # 3. Test processing_complete
        self.job.processing_complete = True
        with self.assertRaises(UserError, msg="Should fail if processing is already complete"):
            self.job.action_process_cvs()

    def test_04_delete_attachments_action(self):
        """Test the delete attachments action."""
        
        # Ensure attachments exist
        self.assertTrue(self.job.cv_attachment_ids)
        self.assertTrue(self.env['ir.attachment'].browse(self.attachment_1.id).exists())
        
        self.job.processing_complete = True
        
        res = self.job.action_delete_cv_attachments()

        # Check state
        self.assertFalse(self.job.cv_attachment_ids)
        self.assertFalse(self.job.processing_complete)
        self.assertFalse(self.job.processing_in_progress)
        
        # Check that attachments are unlinked
        self.assertFalse(self.env['ir.attachment'].browse(self.attachment_1.id).exists())

        # Check notification
        self.assertEqual(res['tag'], 'display_notification')
        self.assertEqual(res['params']['type'], 'success')
        self.assertIn("2 attached CVs", res['params']['message'])