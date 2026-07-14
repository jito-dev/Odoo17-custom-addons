# -*- coding: utf-8 -*-
import logging
import requests

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

FIREFLIES_API_URL = 'https://api.fireflies.ai/graphql'

# Single transcript query. Kept intentionally small to stay well under the
# shared 50 requests/day Fireflies quota and to avoid asking for fields that
# may not exist on every plan. speaker_name is used for diarization labels.
_TRANSCRIPT_QUERY = """
query Transcript($id: String!) {
    transcript(id: $id) {
        id
        title
        sentences {
            speaker_name
            text
        }
    }
}
"""


class FirefliesClient(models.AbstractModel):
    """Thin, reusable wrapper around the Fireflies.ai GraphQL API.

    Centralised here so any feature (candidate interview summary, job-context
    extraction, future webhook/cron ingest) shares one fetch implementation and
    one place to enforce the per-day request quota.
    """
    _name = 'fireflies.client'
    _description = 'Fireflies API Client'

    @api.model
    def _parse_meeting_id(self, meeting_link):
        """Extract the Fireflies transcript/meeting id from a link or raw id.

        Fireflies view links look like ``https://app.fireflies.ai/view/Title::ID``;
        the id is the part after ``::``. A bare id is returned as-is.
        """
        if not meeting_link:
            return ''
        meeting_id = meeting_link.strip()
        if '::' in meeting_id:
            meeting_id = meeting_id.split('::')[-1]
        elif '/' in meeting_id:
            # Fallback: last path segment of an unexpected URL shape.
            meeting_id = meeting_id.rstrip('/').split('/')[-1]
        return meeting_id.strip()

    @api.model
    def _get_api_key(self, company=None):
        company = company or self.env.company
        api_key = (company.fireflies_api_key or '').strip()
        if not api_key:
            raise UserError(_(
                "Fireflies API Key is not configured. Set it in "
                "Settings > Recruitment (OpenAI / Fireflies keys)."
            ))
        return api_key

    @api.model
    def fetch_transcript(self, meeting_link, company=None):
        """Fetch a transcript and return a normalised dict.

        Returns: {
            'meeting_id': str,
            'title': str,
            'sentences': [{'speaker': str, 'text': str}, ...],
            'text': str,   # speaker-labelled plain text, ready for the model
        }
        Raises UserError on any API/transport problem so callers can surface a
        clean message to the recruiter.
        """
        meeting_id = self._parse_meeting_id(meeting_link)
        if not meeting_id:
            raise UserError(_("Could not read a Fireflies meeting id from the link."))

        api_key = self._get_api_key(company=company)
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }

        try:
            response = requests.post(
                FIREFLIES_API_URL,
                json={'query': _TRANSCRIPT_QUERY, 'variables': {'id': meeting_id}},
                headers=headers,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            _logger.error("Fireflies request failed for id %s: %s", meeting_id, e)
            raise UserError(_("Could not reach Fireflies: %s", str(e)))

        if data.get('errors'):
            message = data['errors'][0].get('message', _("Unknown error"))
            raise UserError(_("Fireflies error: %s", message))

        transcript = (data.get('data') or {}).get('transcript')
        if not transcript:
            raise UserError(_("No transcript found for this Fireflies link."))

        sentences = []
        for s in transcript.get('sentences') or []:
            text = (s.get('text') or '').strip()
            if not text:
                continue
            sentences.append({
                'speaker': (s.get('speaker_name') or '').strip(),
                'text': text,
            })

        # Build speaker-labelled plain text for the model.
        lines = []
        for s in sentences:
            if s['speaker']:
                lines.append(f"{s['speaker']}: {s['text']}")
            else:
                lines.append(s['text'])
        full_text = "\n".join(lines)

        return {
            'meeting_id': transcript.get('id') or meeting_id,
            'title': (transcript.get('title') or '').strip(),
            'sentences': sentences,
            'text': full_text,
        }
