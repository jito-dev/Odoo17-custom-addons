import calendar
import logging

from odoo import api, fields, models

from .constants import (
    BIRTHDAY_FIELD_GROUPS,
    BIRTHDAY_UNKNOWN_YEAR,
    PARAM_FALLBACK_USERS,
)

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    """Birthday data on contacts.

    This half of the extension owns the *fields*: the birthday itself,
    the derived helpers that drive the Birthdays board, and the
    eligibility rule that decides who is tracked at all. The cron and
    the notification dispatch live in ``res_partner_reminder.py``.

    Eligibility (``birthday_eligible``) is the module's central concept:

    1. ``birthday`` is set,
    2. the record is a person, not a company (``is_company = False``),
    3. the record is **not** linked to an Odoo internal user — current
       **or past**, i.e. archived users count too,
    4. the record is active.

    Rule 3 is why ``has_internal_user`` exists as its own stored field:
    a plain read of ``partner.user_ids`` hides archived users
    (``active_test``), so "past internal user" would silently pass the
    filter. The compute searches ``res.users`` with ``active_test=False``
    under ``sudo()`` instead.
    """

    _inherit = 'res.partner'

    birthday = fields.Date(
        string='Birthday',
        groups=BIRTHDAY_FIELD_GROUPS,
        tracking=True,
        help="Date of birth of this contact. Only the day and month are "
             "ever used or disclosed by the reminder emails — the year "
             "is never shown, so the contact's age is not leaked.",
    )
    next_birthday = fields.Date(
        string='Next Birthday',
        compute='_compute_birthday_helpers',
        store=True,
        compute_sudo=True,
        groups=BIRTHDAY_FIELD_GROUPS,
        help="Next upcoming occurrence of the birthday — today or later. "
             "Feb 29 falls back to Feb 28 in non-leap years, matching "
             "the cron so calendar and reminders always agree.",
    )
    # Numeric key prefixes are intentional: Odoo sorts group-by results
    # on a Selection field by the stored key, not by declaration order.
    # Without them the kanban columns would read Later → This Week →
    # Today → Tomorrow, which inverts the urgency the board is for.
    birthday_proximity = fields.Selection(
        selection=[
            ('1_today', '🎂 Today'),
            ('2_tomorrow', '🗓️ Tomorrow'),
            ('3_this_week', '📅 Within 7 Days'),
            ('4_later', '⏳ Later'),
        ],
        string='Birthday Proximity',
        compute='_compute_birthday_helpers',
        store=True,
        compute_sudo=True,
        groups=BIRTHDAY_FIELD_GROUPS,
        help="Bucket used to group the Birthdays board. Empty for "
             "contacts without a birthday.",
    )
    has_internal_user = fields.Boolean(
        string='Is/was an internal user',
        compute='_compute_has_internal_user',
        store=True,
        compute_sudo=True,
        groups=BIRTHDAY_FIELD_GROUPS,
        help="True when this contact is linked to an Odoo internal user "
             "account, active or archived. Such contacts are colleagues, "
             "not clients — their birthdays belong to the HR birthday "
             "module, so they are excluded here.",
    )
    birthday_eligible = fields.Boolean(
        string='Tracked for birthday reminders',
        compute='_compute_birthday_eligible',
        store=True,
        compute_sudo=True,
        groups=BIRTHDAY_FIELD_GROUPS,
        help="True when this contact appears on the Birthdays board and "
             "is picked up by the reminder cron: a birthday is set, the "
             "record is a person (not a company), and it is not linked "
             "to any current or past Odoo internal user.",
    )
    birthday_year_unknown = fields.Boolean(
        string='Birth year unknown',
        groups=BIRTHDAY_FIELD_GROUPS,
        tracking=True,
        help="Tick when only the day and month are known. The stored year "
             "is then normalised to a sentinel and carries no meaning. "
             "Nothing else changes: the reminder engine has always matched "
             "on day and month only, and the year is never disclosed.",
    )
    birthday_greeter_id = fields.Many2one(
        comodel_name='res.users',
        string='Birthday Greeter',
        domain=[('share', '=', False)],
        # NEVER cascade. The Odoo default for a many2one is ondelete
        # 'set null' only because the field is not required — but spelling
        # it out matters here: a cascade from res.users to res.partner
        # would delete customer records when a user account is removed.
        ondelete='set null',
        index=True,
        groups=BIRTHDAY_FIELD_GROUPS,
        tracking=True,
        help="Who greets this contact, when that is not the Salesperson. "
             "Set this instead of editing Salesperson: that field drives "
             "sales reporting, lead assignment and record rules, and "
             "changing it to steer birthday emails corrupts CRM data. "
             "Leave empty to use the Salesperson, then the Default "
             "Greeter from Settings.",
    )
    birthday_manager_ids = fields.Many2many(
        comodel_name='res.users',
        relation='res_partner_birthday_manager_rel',
        column1='partner_id',
        column2='user_id',
        string='Birthday Reminder Recipients',
        compute='_compute_birthday_manager',
        store=True,
        compute_sudo=True,
        groups=BIRTHDAY_FIELD_GROUPS,
        help="Who actually receives this contact's birthday reminders, "
             "resolved as: Birthday Greeter, then Salesperson (which Odoo "
             "itself inherits from the parent company when left empty), "
             "then the Default Greeters from Settings. Only the last step "
             "can yield more than one person. Candidates that are "
             "archived or are portal users are skipped. Empty means "
             "nobody is reminded.",
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('birthday')
    def _compute_birthday_helpers(self):
        """Recompute next_birthday + birthday_proximity.

        Both depend on "today", which the ORM cannot track — the daily
        cron calls ``_refresh_partner_birthday_helpers()`` so the board
        stays correct after midnight.
        """
        today = fields.Date.context_today(self.env.user)
        for partner in self:
            birthday = partner.sudo().birthday
            if not birthday:
                partner.next_birthday = False
                partner.birthday_proximity = False
                continue
            occurrence = partner._birthday_next_occurrence(today)
            partner.next_birthday = occurrence
            if not occurrence:
                partner.birthday_proximity = False
                continue
            days = (occurrence - today).days
            if days == 0:
                partner.birthday_proximity = '1_today'
            elif days == 1:
                partner.birthday_proximity = '2_tomorrow'
            elif days <= 7:
                partner.birthday_proximity = '3_this_week'
            else:
                partner.birthday_proximity = '4_later'

    @api.depends('user_ids', 'user_ids.share', 'user_ids.active')
    def _compute_has_internal_user(self):
        """Flag contacts that are (or ever were) Odoo internal users.

        ``user_ids`` is filtered by ``active_test`` on a normal read, so
        archived users would not be seen — hence the explicit
        ``with_context(active_test=False)`` search. ``sudo()`` because
        ``res.users`` is not readable by every internal user.

        The ``user_ids.active`` dependency covers the archive/unarchive
        transition; the daily cron additionally re-runs this compute for
        every partner, so any dependency edge case the ORM misses
        self-heals within 24 hours instead of silently leaking a
        colleague onto the client birthday board.
        """
        real = self.filtered(lambda p: isinstance(p.id, int))
        for partner in self - real:
            partner.has_internal_user = False
        if not real:
            return
        internal_users = self.env['res.users'].sudo().with_context(
            active_test=False,
        ).search([
            ('partner_id', 'in', real.ids),
            ('share', '=', False),
        ])
        internal_partner_ids = set(internal_users.mapped('partner_id').ids)
        for partner in real:
            partner.has_internal_user = partner.id in internal_partner_ids

    @api.depends('birthday', 'is_company', 'active', 'has_internal_user')
    def _compute_birthday_eligible(self):
        for partner in self:
            partner_su = partner.sudo()
            partner.birthday_eligible = bool(
                partner_su.birthday
                and not partner.is_company
                and partner.active
                and not partner_su.has_internal_user
            )

    @api.model
    def _birthday_valid_recipient(self, user):
        """``user`` if they can actually receive reminders, else empty.

        A recipient must be an active, non-portal user. Checked on every
        read rather than at write time so that archiving someone, or
        converting them to a portal account, stops their reminders
        immediately — without anyone having to remember to go and clear
        the field that names them.
        """
        if user and user.active and not user.share:
            return user
        return self.env['res.users'].browse()

    @api.model
    def _birthday_fallback_config(self):
        """The configured Default Greeters, as a (possibly empty) recordset.

        Plural on purpose: several people can cover the whole contact base
        without any of them being written onto individual contacts.
        """
        Users = self.env['res.users'].sudo()
        raw = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_FALLBACK_USERS,
        ) or ''
        ids = []
        for chunk in str(raw).split(','):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                ids.append(int(chunk))
            except (TypeError, ValueError):
                continue
        if not ids:
            return Users.browse()
        candidates = Users.browse(ids).exists()
        return candidates.filtered(
            lambda u: u.active and not u.share
        )

    @api.depends('birthday_greeter_id', 'user_id')
    def _compute_birthday_manager(self):
        """Resolve the reminder recipient through the chain.

        ``birthday_greeter_id`` → ``user_id`` → Default Greeter → nobody.

        Stored (not a plain helper) because the engine searches on it and
        the board groups by it.

        There is deliberately no "inherit from the parent company" step:
        Odoo core already copies the parent company's salesperson onto a
        person contact with no ``user_id`` of its own (``_compute_user_id``
        in ``base``), so by the time we read ``user_id`` that has already
        happened. Adding our own would duplicate core and fight its
        stored, user-overridable compute.

        Every candidate goes through ``_birthday_valid_recipient``, so an
        archived greeter falls through to the next step instead of
        silently sending nothing — the failure mode nobody would notice.

        The Default Greeter comes from ``ir.config_parameter``, which the
        ORM cannot list as a dependency — the same limitation
        ``next_birthday`` has with "today", handled the same established
        way: ``_refresh_partner_birthday_helpers()`` recomputes nightly,
        and ``res.config.settings.set_values()`` recomputes immediately so
        the board does not lie until the next cron tick.
        """
        default_greeters = self._birthday_fallback_config()
        for partner in self:
            recipients = (
                self._birthday_valid_recipient(partner.birthday_greeter_id)
                or self._birthday_valid_recipient(partner.user_id)
                or default_greeters
            )
            partner.birthday_manager_ids = [(6, 0, recipients.ids)]

    # ------------------------------------------------------------------
    # Unknown birth year
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._birthday_apply_unknown_year()
        return partners

    def write(self, vals):
        res = super().write(vals)
        if 'birthday' in vals or 'birthday_year_unknown' in vals:
            self._birthday_apply_unknown_year()
        return res

    def _birthday_apply_unknown_year(self):
        """Normalise the stored year on 'year unknown' contacts.

        ``BIRTHDAY_UNKNOWN_YEAR`` is a leap year, so ``replace(year=...)``
        is safe for every valid day/month including Feb 29 — no fallback
        branch is needed here (unlike ``_birthday_next_occurrence``, which
        targets arbitrary real years).

        The nested ``write`` terminates after one extra pass: the second
        time round the year already equals the sentinel, so nothing is
        written and the recursion stops.
        """
        for partner in self:
            partner_su = partner.sudo()
            birthday = partner_su.birthday
            if not (partner_su.birthday_year_unknown and birthday):
                continue
            if birthday.year == BIRTHDAY_UNKNOWN_YEAR:
                continue
            partner_su.write({
                'birthday': birthday.replace(year=BIRTHDAY_UNKNOWN_YEAR),
            })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _birthday_next_occurrence(self, today):
        """Next occurrence of ``self.birthday`` on/after ``today``.

        Feb 29 in a non-leap target year falls back to Feb 28 — the same
        policy the matching code uses, so a contact born on Feb 29 is
        never skipped three years out of four.
        """
        self.ensure_one()
        birthday = self.sudo().birthday
        if not birthday:
            return False

        def _safe(year):
            try:
                return birthday.replace(year=year)
            except ValueError:
                return birthday.replace(year=year, day=28)

        occurrence = _safe(today.year)
        if occurrence < today:
            occurrence = _safe(today.year + 1)
        return occurrence

    @api.model
    def _refresh_partner_birthday_helpers(self):
        """Recompute the stored birthday helpers against the current day.

        Called at the start of every cron tick. Two things are healed
        here that ``@api.depends`` alone cannot guarantee:

        * ``next_birthday`` / ``birthday_proximity`` depend on "today",
          which no field write announces;
        * ``has_internal_user`` (and therefore ``birthday_eligible``)
          depends on the state of linked user accounts, including
          archiving — a write on another model that may reach us through
          paths the dependency graph does not cover;
        * ``birthday_manager_ids`` depends on two ``ir.config_parameter``
          values and on whether the fallback user is still an active
          internal user — none of which the dependency graph can see.
        """
        partners = self.sudo().with_context(active_test=False).search([
            ('birthday', '!=', False),
        ])
        if not partners:
            return
        fields_to_refresh = [
            'next_birthday', 'birthday_proximity',
            'has_internal_user', 'birthday_eligible',
            'birthday_manager_ids',
        ]
        partners.invalidate_recordset(fields_to_refresh)
        partners._compute_birthday_helpers()
        partners._compute_has_internal_user()
        partners._compute_birthday_eligible()
        partners._compute_birthday_manager()
        partners.flush_recordset(fields_to_refresh)

    @api.model
    def _refresh_partner_birthday_managers(self):
        """Recompute only the recipient chain, right after a settings save.

        Cheaper than the full nightly refresh and, more importantly,
        immediate: without it the Birthdays board would keep showing the
        previous recipient until the next cron tick, which reads as a bug.
        """
        partners = self.sudo().with_context(active_test=False).search([
            ('birthday', '!=', False),
        ])
        if not partners:
            return
        partners.invalidate_recordset(['birthday_manager_ids'])
        partners._compute_birthday_manager()
        partners.flush_recordset(['birthday_manager_ids'])

    @api.model
    def _partners_with_birthday_on(self, target_date):
        """Eligible contacts whose birthday matches ``target_date``.

        Matching is on (day, month) only, in Python over the pre-filtered
        eligible set — the same approach as the HR module, which keeps
        the Feb-29 rule in a single readable place instead of spreading
        it across SQL date arithmetic.

        Feb 29 fallback: in a non-leap year, a Feb 28 target also
        matches contacts born on Feb 29.
        """
        feb29_fallback = (
            not calendar.isleap(target_date.year)
            and target_date.month == 2
            and target_date.day == 28
        )
        candidates = self.sudo().search([('birthday_eligible', '=', True)])

        def matches(partner):
            birthday = partner.birthday
            if birthday.month == target_date.month and birthday.day == target_date.day:
                return True
            return feb29_fallback and birthday.month == 2 and birthday.day == 29

        return candidates.filtered(matches)
