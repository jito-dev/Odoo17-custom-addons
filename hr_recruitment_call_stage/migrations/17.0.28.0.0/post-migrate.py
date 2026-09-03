# -*- coding: utf-8 -*-
"""v17.0.28.0.0 — preserve the stages whose Interviewer was actually narrowing.

The "Interviewer" field is gone: the appointment type's own staff is now the
only answer to who runs a call. For most stages that changes nothing — they had
nobody pinned, or pinned exactly the type's whole staff. But a stage that pinned
a *subset* would silently widen, and a candidate would start being able to book
somebody the recruiter had deliberately excluded. Widening who talks to a
candidate is not something a module upgrade may do quietly.

So this pass gives every such stage an appointment type of its own, carrying
exactly the people that were pinned.

The rule is deliberately narrow: **preserve what happens today, not what was
once intended.** A pin naming somebody who is no longer on the type — or only
archived users — already resolves to "anyone free" at booking time (the subset
is intersected with the type's staff, and an empty intersection means no filter
at all), so there is nothing to preserve and nothing is created. Restoring an
intent the system stopped honouring months ago would be a behaviour change of
its own, dressed up as a migration.

The old many2many table is read with raw SQL: by the time post-migrate runs the
field is off the model, while the table is still there.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

REL_TABLE = 'hr_job_stage_config_call_staff_user_rel'

# Columns `website_appointment` bolts onto `appointment.type`. This module does
# not depend on it, so during post-migrate the registry may not carry the fields
# yet — see `_backfill_website_columns`.
WEBSITE_COLUMNS = ('cover_properties', 'is_published', 'website_id')


def _pins(cr):
    """Return {config_id: set(user_id)} from the retired Interviewer table."""
    cr.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
        (REL_TABLE,))
    if not cr.fetchone():
        return {}
    cr.execute("SELECT config_id, user_id FROM %s" % REL_TABLE)
    pins = {}
    for config_id, user_id in cr.fetchall():
        pins.setdefault(config_id, set()).add(user_id)
    return pins


def _backfill_website_columns(cr, source_id, new_id):
    """Copy the website columns onto the new type, in SQL.

    Modules are loaded in dependency order and a model grows as they load. This
    module does not depend on ``website_appointment``, so when its post-migrate
    runs, ``appointment.type`` may not yet carry the fields that module adds —
    and a record created here then misses them entirely. ``cover_properties``
    silently ends up NULL, and the first person to open the type's website page
    gets a 500: ``website.record_cover`` does ``json.loads(cover_properties)``
    and cannot parse ``False``.

    SQL sidesteps the registry: the columns exist on the table whether or not
    the fields are loaded into the model yet. When the registry IS complete the
    ORM copy already carried them, and this rewrites identical values.

    :return: the columns actually copied, for the log.
    """
    cr.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'appointment_type' AND column_name IN %s",
        (WEBSITE_COLUMNS,))
    columns = [row[0] for row in cr.fetchall()]
    if not columns:
        return []
    # Column names come from the whitelist above, never from data.
    assignments = ', '.join('%s = src.%s' % (name, name) for name in columns)
    cr.execute(
        "UPDATE appointment_type dst SET " + assignments +
        " FROM appointment_type src WHERE dst.id = %s AND src.id = %s",
        (new_id, source_id))
    return columns


def _repoint_invites(env, config, old_type, new_type):
    """Move this stage's live booking invites onto the dedicated type.

    ``hr.applicant._get_current_invite`` looks an invite up by the CURRENT
    stage's appointment type. Leave the invites behind and every candidate
    holding a link reads as "no link" in the cockpit — the chip falls back to
    `no_link` and a recruiter sends a second one. The candidate sees nothing:
    ``book_url`` resolves through the invite's short code, not through the type.

    The invite's own ``staff_user_ids`` is left alone; it stays valid, since the
    new type carries exactly those people.

    :return: the number of invites moved.
    """
    stages = config.stage_id | config.call_booked_stage_id
    applicants = env['hr.applicant'].with_context(active_test=False).search([
        ('job_id', '=', config.job_id.id),
        ('stage_id', 'in', stages.ids),
    ])
    if not applicants:
        return 0
    invites = env['appointment.invite'].sudo().search([
        ('applicant_id', 'in', applicants.ids),
        ('appointment_type_ids', 'in', old_type.ids),
    ])
    if not invites:
        return 0
    invites.write({'appointment_type_ids': [(6, 0, new_type.ids)]})
    return len(invites)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    pins = _pins(cr)
    if not pins:
        _logger.info(
            "hr_recruitment_call_stage: no stage had an Interviewer pinned; "
            "nothing to preserve.")
        return

    Config = env['hr.job.stage.config'].sudo()
    Users = env['res.users'].with_context(active_test=False).sudo()
    split = kept = ignored = 0

    for config_id, user_ids in pins.items():
        config = Config.browse(config_id).exists()
        if not config or not config.is_call_stage:
            continue
        appt = config.booking_appointment_type_id.sudo()
        if not appt or appt.schedule_based_on != 'users':
            continue

        # Archived users are already invisible to the booking page, so they
        # cannot be part of what is happening today.
        pinned = Users.browse(sorted(user_ids)).exists().filtered('active')
        staff = appt.staff_user_ids
        if not pinned or not (pinned <= staff):
            # No effective narrowing today — see the module docstring.
            ignored += 1
            _logger.info(
                "Call Stage %s (%s / %s): pinned interviewers %s are not a "
                "live subset of appointment type '%s' (%s); the stage already "
                "books its whole staff, so nothing was changed.",
                config.id, config.job_id.display_name,
                config.stage_id.display_name,
                pinned.mapped('login') or list(user_ids), appt.name,
                staff.mapped('login'))
            continue
        if pinned == staff:
            kept += 1
            continue

        name = '%s — %s' % (config.job_id.display_name or 'Call',
                            config.stage_id.display_name or 'Interview')
        new_type = appt.copy()
        # The name is written after the copy, not through its default:
        # `appointment.type.copy()` overwrites `default['name']` with
        # "<name> (copy)" unconditionally (appointment_type.py:345). And a copy
        # of an archived type must not arrive archived — the stage needs a type
        # it can actually book through.
        new_type.write({
            'name': name,
            'active': True,
            'staff_user_ids': [(6, 0, pinned.ids)],
        })
        config.booking_appointment_type_id = new_type.id
        new_type.flush_recordset()
        website_columns = _backfill_website_columns(cr, appt.id, new_type.id)
        new_type.invalidate_recordset()
        moved = _repoint_invites(env, config, appt, new_type)
        split += 1
        _logger.info(
            "Call Stage %s (%s / %s): kept its narrowed interviewers %s by "
            "splitting appointment type '%s' (staff %s) into a dedicated "
            "'%s' (id=%s); %s live invite(s) moved with it; website columns "
            "carried over: %s.",
            config.id, config.job_id.display_name,
            config.stage_id.display_name, pinned.mapped('login'), appt.name,
            staff.mapped('login'), name, new_type.id, moved,
            ', '.join(website_columns) or 'none present')

    _logger.info(
        "hr_recruitment_call_stage: Interviewer retired — %s stage(s) given a "
        "dedicated appointment type, %s already matched their type's staff, "
        "%s had no effective narrowing left.", split, kept, ignored)
