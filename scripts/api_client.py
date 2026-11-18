"""Small HTTP client for the reproducible local demo checks (standard library only)."""
from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.request


class API:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    def request(self, method: str, path: str, body=None, *, session_token=None, bearer=None, expect=None):
        headers = {'Accept': 'application/json'}
        if session_token:
            headers['X-Session-Token'] = session_token
        if bearer:
            headers['Authorization'] = f'Bearer {bearer}'
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode()
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as response:
            status, raw = response.code, response.read()
        result = json.loads(raw) if raw else None
        accepted = [expect] if isinstance(expect, int) else expect
        if accepted is not None:
            if status not in accepted:
                raise AssertionError(f'{method} {path}: expected {accepted}, got {status}: {result}')
        elif not 200 <= status < 300:
            raise AssertionError(f'{method} {path}: {status}: {result}')
        return result

    def login(self, username='staff') -> str:
        return self.request('POST', '/auth/login', {'username': username, 'password': os.environ.get('DEMO_PASSWORD', 'local-demo-change-me')})['access_token']

    def ready(self, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                return self.request('GET', '/health')
            except (OSError, AssertionError):
                time.sleep(0.25)
        raise RuntimeError('API did not become ready within the timeout')
