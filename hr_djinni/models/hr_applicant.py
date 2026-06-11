# Copyright © 2024 Garazd Creation (<https://garazd.biz>)
# @author: Yurii Razumovskyi (<support@garazd.biz>)
# @author: Iryna Razumovska (<support@garazd.biz>)
# License OPL-1 (https://www.odoo.com/documentation/15.0/legal/licenses.html).

from odoo import _, fields, models


class HrApplicant(models.Model):
    _inherit = "hr.applicant"

    djinni_ref = fields.Char(string='Djinni ID', readonly=True)
    djinni_date = fields.Datetime(readonly=True)
    djinni_candidate_url = fields.Char()
    djinni_candidate_cv_url = fields.Char()
    # Djinni profile data (cover letter, experience, skills, …) lives here,
    # read-only and owned by the sync. Previously it was written into the native
    # `description` on every sync, which silently clobbered recruiters' notes.
    djinni_profile_html = fields.Html(string='Djinni Profile', readonly=True, copy=False, sanitize=False)
    # True once the sync has back-filled a real name/email for a candidate that
    # was imported anonymously (Djinni only reveals contacts once the candidate
    # opens them). Lets recruiters filter "contacts now revealed" vs still anon.
    djinni_contacts_revealed = fields.Boolean(
        string='Djinni Contacts Revealed', readonly=True, copy=False)

    # Contact fields the sync may *back-fill* once Djinni reveals them. Each is
    # written ONLY while still empty on our side, so a recruiter edit always wins.
    # `name`, `stage_id`, `description`, notes, … are deliberately NOT in this set.
    _DJINNI_ENRICH_FIELDS = (
        'partner_name', 'email_from', 'partner_phone', 'linkedin_profile',
        'djinni_candidate_url', 'djinni_candidate_cv_url', 'djinni_date',
    )

    def _djinni_enrich_from_sync(self, applicant_vals, applicant):
        """Back-fill real contact data once a Djinni candidate opens their contacts.

        The 30-min sync is non-destructive — it never re-writes a known
        candidate — so a candidate imported anonymously ("Djinni #<ref> — <job>")
        would stay anonymous forever even after revealing their name/email on
        Djinni. This closes that gap *safely*: an incoming Djinni value is written
        ONLY into a field that is still empty on our side, so a recruiter's manual
        edit is never clobbered and the candidate's ``stage_id`` is never touched.

        The placeholder ``name`` is treated as "empty": it is swapped for the real
        name only while it is still the untouched placeholder, detected by the
        stable ``Djinni #<ref>`` prefix so that a recruiter rename (or a later job
        rename) keeps its value.

        :param applicant_vals: the mapped ``hr.applicant`` vals for this candidate
            (``partner_name`` is set only when Djinni actually revealed a name).
        :param applicant: the raw Djinni payload (for the photo/CV URLs).
        :return: True if anything was back-filled (caller counts it as updated).
        """
        self.ensure_one()
        vals = {}
        for fname in self._DJINNI_ENRICH_FIELDS:
            incoming = applicant_vals.get(fname)
            if incoming and not self[fname]:
                vals[fname] = incoming
        # The real name lives in `partner_name` only when Djinni revealed it.
        # Replace the anonymous subject with it, but only while it is still the
        # untouched placeholder (a recruiter rename must survive).
        real_name = applicant_vals.get('partner_name')
        placeholder = 'Djinni #%s' % (self.djinni_ref or '')
        if real_name and self.name and self.name.startswith(placeholder):
            vals['name'] = real_name
        # Human-readable labels of what we are filling, for the chatter note: the
        # back-filled fields are not Odoo-tracked, so without this nothing would
        # record *which* data the sync added. `name` is the placeholder swap, a
        # mirror of `partner_name`, so it is labelled only when `partner_name`
        # itself is not also being filled (avoids a duplicate "Applicant's Name").
        filled = []
        for fname in vals:
            if fname == 'name':
                if 'partner_name' not in vals:
                    filled.append(self._fields['partner_name'].string)
            else:
                filled.append(self._fields[fname].string)
        if vals:
            # Contacts count as revealed once we learn a real name or email.
            if vals.get('partner_name') or vals.get('email_from'):
                vals['djinni_contacts_revealed'] = True
            self.write(vals)
        # Photo / CV that may have become available together with the contacts;
        # fetched only when still missing (the CV helper also dedupes by URL).
        if applicant.get('picture_url') and not self.image_1920:
            self.download_and_set_photo(applicant.get('picture_url'))
            filled.append(_('Photo'))
        if applicant.get('cv_url') and not self.env['ir.attachment'].search_count([
            ('url', '=', applicant['cv_url']),
            ('res_model', '=', 'hr.applicant'), ('res_id', '=', self.id),
        ]):
            self.download_and_link_attachment(applicant.get('cv_url'))
            filled.append(_('CV'))
        if filled:
            self.message_post(body=_(
                'Djinni sync back-filled from the candidate’s revealed '
                'profile: %s', ', '.join(filled)))
        return bool(filled)

    def action_open_on_djinni(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': self.djinni_candidate_url,
            'target': 'new',
        }

    def action_djinni_send_acknowledgement(self):
        """Send the current stage's acknowledgement email to the candidate(s).

        Imported candidates can have their stage email suppressed on import
        (per-vacancy ``hr.job.djinni_suppress_new_email``). This button lets the
        recruiter send it on demand afterwards. It posts the stage's
        ``template_id`` exactly the way Odoo's automatic stage email does
        (see ``hr.applicant._track_template``), so the message looks identical.
        Works on a single candidate or on a multi-selection.
        """
        sent = 0
        mt_note = self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note')
        for applicant in self:
            template = applicant.stage_id.template_id
            if not template:
                continue
            applicant.message_post_with_source(
                template,
                subtype_id=mt_note,
                message_type='auto_comment',
                email_layout_xmlid='hr_recruitment.mail_notification_light_without_background',
            )
            sent += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if sent else 'warning',
                'title': _('Acknowledgement email'),
                'message': (
                    _('Acknowledgement email sent to %(sent)s candidate(s).', sent=sent)
                    if sent else
                    _('No email sent: the current stage has no email template.')
                ),
                'sticky': False,
            },
        }
