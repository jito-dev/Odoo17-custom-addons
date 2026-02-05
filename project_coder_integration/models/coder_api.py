# -*- coding: utf-8 -*-
import logging
import requests
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CoderAPI:
    """
    Helper class to interact with Coder.com REST API.
    Handles authentication, workspace management, and error handling.
    """

    def __init__(self, base_url, api_token):
        """
        Initialize Coder API client.

        Args:
            base_url (str): Base URL of Coder deployment (e.g., https://coder.jito.dev)
            api_token (str): Coder session token for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.api_token = api_token
        self.headers = {
            'Coder-Session-Token': api_token,
            'Content-Type': 'application/json',
        }
        self.timeout = 10  # seconds

    def _make_request(self, method, endpoint, **kwargs):
        """
        Make HTTP request to Coder API with error handling.

        Args:
            method (str): HTTP method (GET, POST, PUT, etc.)
            endpoint (str): API endpoint path (e.g., /api/v2/users/me)
            **kwargs: Additional arguments passed to requests

        Returns:
            dict: JSON response from API

        Raises:
            UserError: If request fails
        """
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault('headers', self.headers)
        kwargs.setdefault('timeout', self.timeout)

        try:
            _logger.info(f"Coder API {method} request to: {url}")
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.exceptions.Timeout:
            _logger.error(f"Coder API timeout: {url}")
            raise UserError("Connection to Coder timed out. Please check your network connection.")
        except requests.exceptions.ConnectionError:
            _logger.error(f"Coder API connection error: {url}")
            raise UserError(f"Cannot connect to Coder at {self.base_url}. Please check the URL and your network.")
        except requests.exceptions.HTTPError as e:
            _logger.error(f"Coder API HTTP error: {e.response.status_code} - {e.response.text}")
            if e.response.status_code == 401:
                raise UserError("Authentication failed. Please check your Coder API token.")
            elif e.response.status_code == 403:
                raise UserError("Access forbidden. Your API token may not have sufficient permissions.")
            elif e.response.status_code == 404:
                raise UserError("Resource not found. Please check your Coder configuration.")
            else:
                raise UserError(f"Coder API error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            _logger.exception(f"Unexpected error calling Coder API: {str(e)}")
            raise UserError(f"Unexpected error: {str(e)}")

    def test_connection(self):
        """
        Test connection and authentication to Coder API.

        Returns:
            tuple: (success: bool, message: str, user_info: dict)
        """
        try:
            user_info = self._make_request('GET', '/api/v2/users/me')
            username = user_info.get('username', 'Unknown')
            message = f"Successfully connected to Coder as: {username}"
            _logger.info(message)
            return (True, message, user_info)
        except UserError as e:
            return (False, str(e), {})

    def get_workspaces(self):
        """
        Get list of workspaces owned by the authenticated user.

        Returns:
            list: List of workspace dictionaries with id, name, and owner_name
        """
        try:
            response = self._make_request('GET', '/api/v2/workspaces', params={'q': 'owner:me'})
            workspaces = response.get('workspaces', [])

            # Extract only needed fields
            workspace_list = [
                {
                    'id': ws.get('id'),
                    'name': ws.get('name'),
                    'owner_name': ws.get('owner_name', ''),
                }
                for ws in workspaces
            ]

            _logger.info(f"Retrieved {len(workspace_list)} workspaces from Coder")
            return workspace_list
        except UserError:
            raise
        except Exception as e:
            _logger.exception(f"Error fetching workspaces: {str(e)}")
            raise UserError(f"Failed to fetch workspaces: {str(e)}")

    def get_workspace_status_sse(self, workspace_id):
        """
        Get current workspace status via SSE (single event).

        Args:
            workspace_id (str): ID of the workspace

        Returns:
            str: Current workspace build status
        """
        url = f"{self.base_url}/api/v2/workspaces/{workspace_id}/watch"
        headers = {
            'Coder-Session-Token': self.api_token,
            'Accept': 'text/event-stream'
        }

        try:
            _logger.info(f"Fetching workspace status via SSE: {url}")
            response = requests.get(url, headers=headers, stream=True, timeout=10)
            response.raise_for_status()

            # Read first SSE event
            for line in response.iter_lines(decode_unicode=True):
                if line.startswith('data: '):
                    data_str = line[6:]  # Remove 'data: ' prefix
                    try:
                        import json
                        data = json.loads(data_str)
                        status = data.get('latest_build', {}).get('status', 'unknown')
                        _logger.info(f"Workspace {workspace_id} status: {status}")
                        response.close()  # Close connection after first event
                        return status.lower()
                    except json.JSONDecodeError as e:
                        _logger.warning(f"Failed to parse SSE data: {e}")
                        continue

            # If no data received
            return 'unknown'

        except requests.exceptions.Timeout:
            _logger.error(f"SSE timeout for workspace {workspace_id}")
            return 'timeout'
        except requests.exceptions.RequestException as e:
            _logger.error(f"SSE request error: {str(e)}")
            return 'error'
        except Exception as e:
            _logger.exception(f"Unexpected error in SSE: {str(e)}")
            return 'error'
