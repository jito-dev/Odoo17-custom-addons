# -*- coding: utf-8 -*-
"""Regression: a regular (non-HR-Officer) user must be able to open their own
My Profile page even though this module adds the `hpc_signature_img` field to
that form.

Root cause of the original bug: `res.users.read` only reads a user's own record
under sudo when EVERY field requested is in `SELF_READABLE_FIELDS`. Our extra
profile field was not registered there, so the read fell back to a non-sudo
read that raised AccessError on the officer-only HR fields (birthday, ssnid, …).
Registering the field as self-readable restores the sudo fast-path.
"""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProfileSelfRead(TransactionCase):
    def test_signature_fields_are_self_readable(self):
        """The module's profile fields are registered as self read/write."""
        Users = self.env['res.users']
        self.assertIn('hpc_signature_img', Users.SELF_READABLE_FIELDS)
        self.assertIn('hpc_signature_img_filename', Users.SELF_READABLE_FIELDS)
        self.assertIn('hpc_signature_img', Users.SELF_WRITEABLE_FIELDS)
        self.assertIn('hpc_signature_img_filename', Users.SELF_WRITEABLE_FIELDS)

    def test_non_officer_reads_own_profile_with_private_and_signature(self):
        """A plain employee user reads their own private HR fields + the
        signature field together (the exact mix the My Profile form fetches)
        without tripping the AccessError."""
        user = self.env['res.users'].create({
            'name': 'Contractor Self Read',
            'login': 'contractor_self_read@example.com',
            'email': 'contractor_self_read@example.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        # Sanity: this user is NOT an HR Officer (the bug only hit non-officers).
        self.assertNotIn(
            self.env.ref('hr.group_hr_user'), user.groups_id,
            "precondition: the test user must not be an HR Officer")

        own = self.env['res.users'].with_user(user).browse(user.id)
        # Officer-only HR fields + our signature field, read as the user itself.
        try:
            own.read(['name', 'birthday', 'ssnid', 'hpc_signature_img',
                      'hpc_signature_img_filename'])
        except AccessError as e:
            self.fail("non-officer self-read of own profile must not raise "
                      "AccessError, got: %s" % e)
