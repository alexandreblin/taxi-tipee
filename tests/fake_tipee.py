"""
A tipee API that answers what the backend sends it, and records the
proposals, for the tests.
"""
import json
from unittest import mock

from taxi_tipee.backend import TipeeBackend

USER_ID = '507535755260723553'


def make_backend(url_options=None, token='tipee-0123abcd-0123abcd-0123abcd-0123abcd', username=None):
    return TipeeBackend(
        username=username,
        password=token,
        hostname='tipee.example',
        port=None,
        path='/api/',
        options={'resource': USER_ID, **(url_options or {})},
        context={'settings': {'regroup_entries': False}},
    )


def response(status, body=None, headers=None):
    r = mock.Mock(status_code=status, headers=headers or {})
    r.content = b'' if body is None else json.dumps(body).encode()
    r.text = r.content.decode()
    if body is None:
        r.json.side_effect = ValueError('no body')
    else:
        r.json.return_value = body
    return r


class FakeTipee:
    def __init__(self, propose=None):
        # Answers to `timechecks.propose`, in order; then 201s.
        self.propose_answers = list(propose or [])
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers))

        if url.endswith('/timeclock/timechecks.propose'):
            if self.propose_answers:
                return self.propose_answers.pop(0)
            return response(201, {'id': str(len(self.calls))})

        return response(404, {'message': 'Not found'})

    @property
    def proposals(self):
        return [body for url, body, _ in self.calls if url.endswith('/timeclock/timechecks.propose')]

    def patch(self):
        return mock.patch('taxi_tipee.backend.requests.post', side_effect=self.post)
