# -*- coding: utf-8 -*-
"""Shared booking-button detection helpers (v17.0.22.0.0).

Single source of truth for the two questions the Call Stage feature keeps
asking about the call-invite email:

* **Static** — does a template's ``body_html`` *expect* to render a
  "Book a call" button (i.e. it references the candidate-specific
  ``object.booking_url``)?  Used by the config-time constraint and the
  readiness panel.
* **Rendered** — after QWeb-rendering the template against a real
  applicant, did a *real* booking link actually come out (a non-empty
  ``<a href>`` pointing at the Appointments ``/book/`` route)?  Used by
  the send-time guard that permanently prevents a button-less invite
  from reaching a candidate.

Kept as plain module-level functions (not a Model) so both
``hr.applicant`` and ``hr.job.stage.config`` can reuse them without a
cross-model dependency.
"""
import re

# A template renders the button when its body reads the per-candidate URL.
# The shipped template uses ``ctx.get('booking_url') or object.booking_url``;
# recruiter-duplicated role variants keep the same expression. Accept either
# form, tolerant of surrounding whitespace.
_VALID_TOKEN_RES = (
    re.compile(r"object\s*\.\s*booking_url"),
    re.compile(r"ctx\s*\.\s*get\(\s*['\"]booking_url['\"]"),
)

# Common near-misses a recruiter might paste by hand. Ordered most- to
# least-specific; the first match wins so the hint is actionable.
_NEAR_MISS_RES = (
    (re.compile(r"obj\s*\.\s*booking_url"),
     "Did you mean `object.booking_url` (not `obj.`)?"),
    (re.compile(r"object\s*\.\s*booking_url", re.IGNORECASE),
     "Found `booking_url` with unexpected casing — use exactly "
     "`object.booking_url`."),
    (re.compile(r"(?<![\w.])booking_url"),
     "Found a bare `booking_url` — wrap it as `object.booking_url`."),
    (re.compile(r"booking_url", re.IGNORECASE),
     "Found `booking_url` with unexpected casing — use exactly "
     "`object.booking_url`."),
)

# Any rendered anchor whose href targets the Appointments booking route.
# appointment.invite.book_url is always ``<base>/book/<code>`` (see
# appointment/models/appointment_invite.py), so ``/book/`` is the stable
# signature of a real, resolved booking link regardless of the base domain.
_HREF_RE = re.compile(r"href\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)


def template_has_booking_token(body_html):
    """True if ``body_html`` references the per-candidate booking URL."""
    body = body_html or ""
    return any(rx.search(body) for rx in _VALID_TOKEN_RES)


def detect_near_miss(body_html):
    """Return a human hint when the body *looks like* it meant to use the
    booking token but got it wrong; ``None`` when the token is valid or
    genuinely absent.
    """
    body = body_html or ""
    if template_has_booking_token(body):
        return None
    for rx, hint in _NEAR_MISS_RES:
        if rx.search(body):
            return hint
    return None


def rendered_has_booking_link(rendered_html, expected_url=None):
    """True if the *rendered* HTML contains a real booking link.

    ``expected_url`` — when known (the freshly-minted ``book_url``) — is the
    most precise check: its literal presence proves the button rendered with
    the candidate's link. Falls back to scanning for any ``<a href>`` on the
    ``/book/`` route with a real ``http(s)`` URL (never empty, never ``#``).
    """
    html = rendered_html or ""
    if expected_url and expected_url in html:
        return True
    for href in _HREF_RE.findall(html):
        href = href.strip()
        if not href or href == "#":
            continue
        if "/book/" in href and href.lower().startswith(("http://", "https://")):
            return True
    return False
