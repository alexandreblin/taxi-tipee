from collections import defaultdict

from taxi.backends import BaseBackend, PushEntryFailed, PushEntriesFailed
from taxi.projects import Activity, Project

from taxi import __version__ as taxi_version
from . import __version__ as taxi_tipee_version

import requests
import time
import hashlib
import datetime

class TipeeBackend(BaseBackend):
    def __init__(self, **kwargs):
        super(TipeeBackend, self).__init__(**kwargs)

        self.name = 'tipee'
        self.path = self.path.lstrip('/')
        self.settings = self.context['settings']

        if self.settings['regroup_entries']:
            raise ValueError(
                f"[{self.name}] cannot work alongside taxi's `regroup_entries` option. Please set it to `false`."
            )

        self.app_name = kwargs['username']
        self.app_private_key = kwargs['password']
        self.hostname = kwargs['hostname']
        self.scheme = kwargs['options'].get('scheme', 'https')
        self.port = int(kwargs.get('port') or (443 if self.scheme == 'https' else 80))
        self.person_id = int(kwargs['options']['person'])

        self.entries = defaultdict(list)

    def api_token(self):
        timestamp = int(time.time())
        app = hashlib.sha1(self.app_name.encode()).hexdigest()
        hash = hashlib.sha1((self.app_private_key + str(timestamp)).encode()).hexdigest()

        return f"FORUM-TOKEN timestamp={timestamp} app={app} hash={hash}"

    def push_entry(self, date, entry):
        if not isinstance(entry.duration, tuple):
            raise PushEntryFailed(
                f"[{self.name}] does not support durations as hours. Please use a time range instead."
            )

        self.entries[date].append(entry)

    def post_push_entries(self):
        failed_entries=defaultdict(list)

        for date, entries in self.entries.items():
            entries_to_skip=[]

            for index, entry in enumerate(entries):
                if entry in entries_to_skip:
                    continue

                entries_to_push = [entry]

                next_index = index + 1
                entry_duration = int(entry.hours * 3600)
                entry_start_time = datetime.datetime.combine(date, entry.get_start_time())

                while True:
                    entry_end_time = entry_start_time + datetime.timedelta(seconds=entry_duration)

                    try:
                        next_entry = entries[next_index]
                        next_entry_duration = int(next_entry.hours * 3600)
                        next_entry_start_time = datetime.datetime.combine(date, next_entry.get_start_time())
                        delta = (next_entry_start_time - entry_end_time).seconds

                        if delta > 0:
                            break

                        entries_to_skip.append(next_entry)
                        entries_to_push.append(next_entry)

                        next_index += 1
                        entry_duration += next_entry_duration
                    except IndexError:
                        break

                try:
                    self._push_entry(entry_start_time, entry_duration)
                except PushEntryFailed as e:
                    for failed_entry in entries_to_push:
                        failed_entries[failed_entry] = str(e)

        if len(failed_entries) > 0:
            raise PushEntriesFailed(entries=failed_entries)

    def _push_entry(self, start, duration):
        end = start + datetime.timedelta(seconds=duration)

        r = requests.post(
            f"{self.scheme}://{self.hostname}:{self.port}/{self.path}/timeclock/timechecks/bulk",
            json=[
                {
                    'person': self.person_id,
                    'timeclock': f"taxi {taxi_version}, taxi-tipee {taxi_tipee_version}",
                    'time': start.strftime('%Y-%m-%d %H:%M:%S'),
                    'external_id': '',
                    'in': True
                },
                {
                    'person': self.person_id,
                    'timeclock': f"taxi {taxi_version}, taxi-tipee {taxi_tipee_version}",
                    'time': end.strftime('%Y-%m-%d %H:%M:%S'),
                    'external_id': ''
                }
            ],
            headers={'Authorization': self.api_token()}
        )

        if r.status_code == 500:
            raise PushEntryFailed(f"[{self.name}] {r.json()['detail']}")

        if r.status_code != 200:
            raise PushEntryFailed(f"[{self.name}] {r.json()['message']}")

        if not all(e['success'] for e in r.json()):
            raise PushEntryFailed(f"[{self.name}] {' // '.join(set(e['error'] for e in r.json() if 'error' in e))}")

    def get_projects(self):
        p = Project(self.name, self.name, Project.STATUS_ACTIVE, description=self.name)

        a = Activity(0, "No activity")
        p.add_activity(a)
        p.aliases[self.name] = a.id

        return [p]
