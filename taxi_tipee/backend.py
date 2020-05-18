from collections import defaultdict

from taxi.backends import BaseBackend, PushEntryFailed
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
        self.path = self.path.lstrip('/')
        self.settings = self.context['settings']
        
        if (self.settings['regroup_entries']):
            raise ValueError('This backend does not support the "regroup_entries" being true. Please set it to false.')

        self.app_name = kwargs['username']
        self.app_private_key = kwargs['password']
        self.hostname = kwargs['hostname']
        self.scheme = kwargs['options'].get('scheme', 'https')
        self.port = int(kwargs.get('port') or (443 if self.scheme == 'https' else 80))
        self.person_id = int(kwargs['options']['person'])

    def api_token(self):
        timestamp = time.time()
        application_hash = self.app_private_key + str(int(timestamp))

        return 'FORUM-TOKEN timestamp={} app={} hash={}'.format(
            int(timestamp),
            hashlib.sha1(self.app_name.encode()).hexdigest(),
            hashlib.sha1(application_hash.encode()).hexdigest()
        )

    def push_entry(self, date, entry):
        if not isinstance(entry.duration, tuple):
            raise PushEntryFailed('This backend does not support durations as hours. Please use a time range.')

        seconds = int(entry.hours * 3600)
        start_time = datetime.datetime.combine(date, entry.get_start_time())
        end_time = start_time + datetime.timedelta(seconds=seconds)

        r = requests.post(f'{self.scheme}://{self.hostname}:{self.port}/{self.path}/timeclock/timechecks/bulk', json=[
            {
                'person': self.person_id,
                'timeclock': f'taxi {taxi_version}, taxi-tipee {taxi_tipee_version}',
                'time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                'external_id': '',
                'in': True
            },
            {
                'person': self.person_id,
                'timeclock': f'taxi {taxi_version}, taxi-tipee {taxi_tipee_version}',
                'time': end_time.strftime('%Y-%m-%d %H:%M:%S'),
                'external_id': ''
            }
        ], headers={
            'Authorization': self.api_token()
        })

        if r.status_code == 500:
            raise PushEntryFailed(r.json()['detail'])

        if r.status_code != 200:
            raise PushEntryFailed(r.json()['message'])
        
        if not all(e['success'] for e in r.json()):
            raise PushEntryFailed(' // '.join(set(e['error'] for e in r.json() if 'error' in e)))

    def get_project_hash(self, project_name):
        result = 0
        for i, c in enumerate(project_name):
            result += ord(c) * pow(10, i * 3)

        return result

    def get_projects(self):
        projects_list = []

        for project_name, count in self.settings.config.items('jira_projects'):
            project_name = project_name.upper()
            p = Project(self.get_project_hash(project_name), project_name, Project.STATUS_ACTIVE)
            for i in range(1, int(count) + 1):
                name = f'{project_name}-{i}'
                a = Activity(i, name, 0)
                p.add_activity(a)
                p.aliases[name] = a.id

            projects_list.append(p)

        return projects_list
