from typing import Dict, List, Union
import logging

import requests
from requests.auth import AuthBase

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def make_request(
        method: str,
        url: str,
        endpoint: str = None,
        headers: Dict = None,
        auth: AuthBase = None,
        data: Dict = None,
        params: Dict = None,
        json: Dict = None,
        files: Dict = None,
        # NOTE: "csv_response" is deprecated: use the "res_type" param with the "text" value
        csv_response: bool = None,  # If True, returns a response text (str), otherwise the Dict
        res_type: str = 'json',  # available types: 'json', 'text', 'raw', 'content'
        with_logs: bool = False,
        api_name: str = 'API',
        timeout: int = 30,
        http_status_to_skip: List[int] = None,  # Return the requests.Response if a status in this list
) -> Union[Dict, str, requests.Response, None]:
    """
    Make an HTTP request to a specified URL.
    Return dict | str: The JSON response from the server | Raw text from response.
    """
    uri = url + endpoint

    if with_logs:
        _logger.debug("[%s] Request URL: %s", api_name, url)

    try:
        response = requests.request(
            method, uri, headers=headers, auth=auth, data=data, params=params, json=json, timeout=timeout, files=files,
        )

        if with_logs:
            _logger.debug(
                "[%(api_name)s] Request details | "
                "Method: %(method)s | URL: %(uri)s | Headers: %(headers)s | Auth: %(auth)s | Data: %(data)s | "
                "Params: %(params)s | JSON: %(json)s",
                {
                    'api_name': api_name, 'method': method, 'uri': uri, 'headers': headers, 'auth': auth,
                    'data': data, 'params': params, 'json': json,
                }
            )
            _logger.info("[%s] Response | Status: %s | Content: %s", api_name, response.status_code, response.text)

        response.raise_for_status()

        # Exceptions
        if response.status_code == 204:  # response don't have content to return
            return None

        # Returns
        if csv_response or res_type == 'text':
            return response.text
        if res_type == 'raw':
            return response.raw
        if res_type == 'content':
            return response.content
        return response.json()

    except requests.exceptions.HTTPError as http_error:
        status_code = http_error.response.status_code

        http_status_list = http_status_to_skip if http_status_to_skip else []

        # Processing error on our side
        if status_code in http_status_list:
            return http_error.response

        if status_code == 401:
            raise UserError("[%s] Authorization error. Please check your user token." % api_name)

        elif status_code == 404:
            raise UserError("[%s] The requested resource was not found." % api_name)

        elif status_code == 500:
            raise UserError("[%s] Internal server error. Please try again later." % api_name)

        else:
            raise UserError("[%(name)s] HTTP error during request: %(err)s" % {'name': api_name, 'err': http_error})

    except requests.exceptions.ConnectionError:
        raise UserError("[%s] Failed to connect to the server. Please check your network connection." % api_name)

    except requests.exceptions.Timeout:
        raise UserError("[%s] The request timed out. Please try again later." % api_name)

    except requests.exceptions.RequestException as error:
        raise UserError("[%s] An error occurred during the request: %s" % (api_name, error))
