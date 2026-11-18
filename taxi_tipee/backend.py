from collections import defaultdict

from taxi.backends import BaseBackend, PushEntryFailed, PushEntriesFailed
from taxi.projects import Activity, Project

from taxi import __version__ as taxi_version
from . import __version__ as taxi_tipee_version
from . import midnight

import requests
import time
import datetime

# The API version this backend is written against (`Tipee-Version`): tipee
# serves the most recent version released on or before it, and supports each
# one for at least six months after the next comes out. 26.06.25 brought
# `timechecks.propose`.
API_VERSION = '26.06.25'

# tipee caps a proposal's remark at 255 characters.
REMARK_MAX_LENGTH = 255

# Attempts per request when tipee asks to come back later (429) or fails on
# its side (500, 504, 508). A failed request changed nothing, so replaying it
# is safe, even for a write.
ATTEMPTS = 4
RETRIED_STATUSES = (429, 500, 504, 508)


def now():
    return datetime.datetime.now()


class TipeeBackend(BaseBackend):
    def __init__(self, **kwargs):
        super(TipeeBackend, self).__init__(**kwargs)

        # Before Taxi reads the timesheet, which it does after loading the
        # backends.
        midnight.install()

        self.name = 'tipee'
        self.path = self.path.strip('/')
        self.settings = self.context['settings']
        options = kwargs['options']

        if self.settings['regroup_entries']:
            raise ValueError(
                f"[{self.name}] cannot work alongside Taxi's `regroup_entries` option. Please set it to `false`."
            )

        if 'person' in options:
            raise ValueError(
                f"[{self.name}] the backend URL is in the old format (an app key and `?person=`), which tipee's"
                " API no longer takes. Create an API token and use `tipee://<token>@<instance>.tipee.net/api/`"
                " instead: see https://github.com/alexandreblin/taxi-tipee#configuration."
            )

        # `tipee://<token>@…`, or `tipee://:<token>@…` for those who prefer it
        # in the password's place.
        self.token = kwargs['password'] or kwargs['username']
        if not self.token:
            raise ValueError(
                f"[{self.name}] the backend URL has no API token: use `tipee://<token>@<instance>.tipee.net/api/`."
            )

        self.hostname = kwargs['hostname']
        self.scheme = options.get('scheme', 'https')
        self.port = int(kwargs.get('port') or (443 if self.scheme == 'https' else 80))

        remark = options.get('remark', 'none')
        if remark not in ('none', 'description'):
            raise ValueError(f"[{self.name}] `remark` is either `none` or `description`, not `{remark}`.")
        self.send_description = remark == 'description'

        merge = options.get('merge', 'true')
        if merge not in ('true', 'false'):
            raise ValueError(f"[{self.name}] `merge` is either `true` or `false`, not `{merge}`.")
        self.merge = merge == 'true'

        self.resource_id = None
        self.entries = defaultdict(list)

    def push_entry(self, date, entry):
        if not isinstance(entry.duration, tuple):
            raise PushEntryFailed(
                f"[{self.name}] does not support durations as hours. Please use a time range instead."
            )

        self.entries[date].append(entry)

    def post_push_entries(self):
        if not self.entries:
            return

        try:
            self.resource_id = self._resource_id()
        except PushEntryFailed as e:
            # Nothing can be pushed: say why once, against every entry.
            raise PushEntriesFailed(entries={
                entry: str(e) for entries in self.entries.values() for entry in entries
            })

        failed_entries = {}

        for start, end, entries in self._timechecks():
            try:
                self._propose(start, end, entries)
            except PushEntryFailed as e:
                for entry in entries:
                    failed_entries[entry] = str(e)

        if failed_entries:
            raise PushEntriesFailed(entries=failed_entries)

    @staticmethod
    def _start(date, entry):
        """
        When the entry starts: on its day, or the next one when an earlier
        entry of its day went past midnight.
        """
        start = datetime.datetime.combine(date, entry.get_start_time())

        return start + datetime.timedelta(days=1) if midnight.after_midnight(entry) else start

    def _resource_id(self):
        """
        Who the token belongs to, after checking they may propose their own
        timechecks: either right lets them.
        """
        user = (self._call('instance/metadata.show', {}) or {}).get('user') or {}

        if not user.get('user_id'):
            raise PushEntryFailed(f"[{self.name}] tipee did not say who the API token belongs to.")

        if user.get('perm_timecheck_suggest') is False and user.get('perm_timecheck_validateown') is False:
            raise PushEntryFailed(
                f"[{self.name}] your tipee account may not propose timechecks (it needs the right to suggest"
                " them or to validate your own): ask your tipee administrator."
            )

        return user['user_id']

    def _timechecks(self):
        """
        The timechecks to propose, as (start, end, entries): one per entry,
        or, with `merge`, one per run of back-to-back entries.

        Oldest first, so that what tipee reports reads in order. Taxi hands
        the entries over in file order, where the newest day usually comes
        first.
        """
        timechecks = []

        for date, entries in sorted(self.entries.items()):
            for entry in sorted(entries, key=lambda entry: self._start(date, entry)):
                start = self._start(date, entry)
                end = start + datetime.timedelta(seconds=round(entry.hours * 3600))

                if self.merge and timechecks and timechecks[-1][1] == start:
                    timechecks[-1][1] = end
                    timechecks[-1][2].append(entry)
                else:
                    timechecks.append([start, end, [entry]])

        return timechecks

    def _propose(self, start, end, entries):
        # tipee refuses it too, in less helpful words.
        if end > now():
            raise PushEntryFailed(f"[{self.name}] ends in the future: tipee only takes an entry once it is over.")

        proposal = {
            'resource_id': self.resource_id,
            'in': start.strftime('%Y-%m-%dT%H:%M:%S'),
            'out': end.strftime('%Y-%m-%dT%H:%M:%S'),
        }

        # The descriptions of merged entries, each once, in order.
        descriptions = list(dict.fromkeys(
            description for description in ((entry.description or '').strip() for entry in entries) if description
        ))
        if self.send_description and descriptions:
            proposal['remark'] = ' / '.join(descriptions)[:REMARK_MAX_LENGTH]

        self._call('timeclock/timechecks.propose', proposal)

    def _call(self, endpoint, body):
        """
        POST `body` to an endpoint of tipee's API and return the decoded
        answer, retrying what tipee says to retry, or raise PushEntryFailed
        with tipee's own words.
        """
        url = f"{self.scheme}://{self.hostname}:{self.port}/{self.path}/{endpoint}"
        headers = {
            'Authorization': f"Bearer {self.token}",
            'Tipee-Version': API_VERSION,
            'Accept': 'application/json',
            'User-Agent': f"taxi/{taxi_version} taxi-tipee/{taxi_tipee_version}",
        }

        for attempt in range(1, ATTEMPTS + 1):
            try:
                r = requests.post(url, json=body, headers=headers, timeout=30)
            except requests.RequestException as e:
                raise PushEntryFailed(f"[{self.name}] could not reach {self.hostname}: {e}")

            if r.status_code not in RETRIED_STATUSES or attempt == ATTEMPTS:
                break

            time.sleep(self._retry_delay(r, attempt))

        if r.status_code == 503:
            raise PushEntryFailed(f"[{self.name}] tipee is under maintenance: try again in a few minutes.")

        if r.status_code == 401:
            raise PushEntryFailed(
                f"[{self.name}] tipee refused the API token: it may have been revoked, or have expired after"
                " 90 days without use. Create a new one (see the README)."
            )

        if not 200 <= r.status_code < 300:
            raise PushEntryFailed(f"[{self.name}] {self._error(r)}")

        return r.json() if r.content else None

    @staticmethod
    def _retry_delay(response, attempt):
        """
        What tipee asks for (`Retry-After`, in seconds), or 1, 2, 4 seconds.
        """
        try:
            return min(float(response.headers.get('Retry-After', '')), 60)
        except ValueError:
            return 2 ** (attempt - 1)

    @staticmethod
    def _error(response):
        """
        tipee's message: a `message`, or a validation failure's `detail`
        (which lists each violation).
        """
        try:
            body = response.json()
        except ValueError:
            body = None

        if isinstance(body, dict):
            for key in ('message', 'detail', 'title'):
                if body.get(key):
                    return body[key]

        return f"HTTP {response.status_code}: {response.text[:200]}"

    def get_projects(self):
        p = Project(self.name, self.name, Project.STATUS_ACTIVE, description=self.name)

        a = Activity(0, "No activity")
        p.add_activity(a)
        p.aliases[self.name] = a.id

        return [p]
