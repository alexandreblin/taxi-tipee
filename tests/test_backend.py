import datetime
import unittest
from unittest import mock

import requests
from taxi.backends import PushEntriesFailed, PushEntryFailed
from taxi.timesheet.entry import EntriesCollection
from taxi.timesheet.parser import TimesheetParser

from fake_tipee import USER_ID, FakeTipee, make_backend, response


class PushTest(unittest.TestCase):
    def setUp(self):
        # No retry waits for real.
        patcher = mock.patch('taxi_tipee.backend.time.sleep')
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def push(self, body, tipee=None, backend=None, day="14/11/2026"):
        """
        Push the entries of `body`; return the fake tipee, and the failures
        by entry description.
        """
        backend = backend or make_backend()
        tipee = tipee or FakeTipee()
        for date, entries in EntriesCollection(TimesheetParser(), f"{day}\n{body}").items():
            for entry in entries:
                backend.push_entry(date, entry)

        failures = {}
        with tipee.patch():
            try:
                backend.post_push_entries()
            except PushEntriesFailed as e:
                failures = {entry.description: message for entry, message in e.entries.items()}

        return tipee, failures

    def test_back_to_back_entries_are_proposed_as_one_for_the_tokens_owner(self):
        tipee, failures = self.push("tipee 08:00-09:00 a\ntipee -10:30 b\ntipee 13:00-14:00 c")

        self.assertEqual(failures, {})
        self.assertEqual(tipee.proposals, [
            {'resource_id': USER_ID, 'in': '2026-11-14T08:00:00', 'out': '2026-11-14T10:30:00'},
            {'resource_id': USER_ID, 'in': '2026-11-14T13:00:00', 'out': '2026-11-14T14:00:00'},
        ])

    def test_each_entry_is_proposed_on_its_own_when_asked(self):
        tipee, failures = self.push("tipee 08:00-09:00 a\ntipee -10:30 b", backend=make_backend({'merge': 'false'}))

        self.assertEqual(failures, {})
        self.assertEqual(tipee.proposals, [
            {'resource_id': USER_ID, 'in': '2026-11-14T08:00:00', 'out': '2026-11-14T09:00:00'},
            {'resource_id': USER_ID, 'in': '2026-11-14T09:00:00', 'out': '2026-11-14T10:30:00'},
        ])

    def test_a_failed_merged_proposal_fails_each_of_its_entries(self):
        tipee = FakeTipee(propose=[response(409, {'message': 'Un timbrage ne peut pas en chevaucher un autre.'})])
        _, failures = self.push("tipee 08:00-09:00 a\ntipee -10:30 b", tipee=tipee)

        self.assertEqual(failures, {'a': '[tipee] Un timbrage ne peut pas en chevaucher un autre.',
                                    'b': '[tipee] Un timbrage ne peut pas en chevaucher un autre.'})

    def test_requests_carry_the_token_and_the_api_version(self):
        tipee, _ = self.push("tipee 08:00-09:00 a")

        urls = [url for url, _, _ in tipee.calls]
        self.assertEqual(urls, ['https://tipee.example:443/api/timeclock/timechecks.propose'])
        for _, _, headers in tipee.calls:
            self.assertEqual(headers['Authorization'], 'Bearer tipee-0123abcd-0123abcd-0123abcd-0123abcd')
            self.assertEqual(headers['Tipee-Version'], '26.06.25')
            self.assertEqual(headers['Accept'], 'application/json')

    def test_the_token_can_also_stand_in_the_username(self):
        backend = make_backend(token=None, username='tipee-ffff0000-ffff0000-ffff0000-ffff0000')
        tipee, _ = self.push("tipee 08:00-09:00 a", backend=backend)

        self.assertEqual(tipee.calls[0][2]['Authorization'], 'Bearer tipee-ffff0000-ffff0000-ffff0000-ffff0000')

    def test_http_and_a_port_for_development(self):
        backend = make_backend({'scheme': 'http'})
        backend.port = 8080
        tipee, _ = self.push("tipee 08:00-09:00 a", backend=backend)

        self.assertEqual(tipee.calls[0][0], 'http://tipee.example:8080/api/timeclock/timechecks.propose')

    def test_the_description_is_sent_only_when_asked(self):
        tipee, _ = self.push("tipee 08:00-09:00 Fixing bug")
        self.assertNotIn('remark', tipee.proposals[0])

        tipee, _ = self.push("tipee 08:00-09:00 Fixing bug\ntipee 11:00-12:00 " + "x" * 300,
                             backend=make_backend({'remark': 'description'}))
        self.assertEqual(tipee.proposals[0]['remark'], 'Fixing bug')
        self.assertEqual(tipee.proposals[1]['remark'], 'x' * 255)

    def test_merged_entries_join_their_descriptions(self):
        tipee, _ = self.push("tipee 08:00-09:00 Review\ntipee -10:00 Fixing bug\ntipee -11:00 Review",
                             backend=make_backend({'remark': 'description'}))
        self.assertEqual(tipee.proposals[0]['remark'], 'Review / Fixing bug')

    def test_failures_are_reported_against_their_entry(self):
        tipee = FakeTipee(propose=[
            response(201, {'id': '1'}),
            response(409, {'message': 'Un timbrage ne peut pas en chevaucher un autre.'}),
            response(422, {'title': 'Validation Failed',
                           'detail': 'out: Timecheck end time (out) must be after start time (in).',
                           'violations': []}),
            response(201, {'id': '4'}),
        ])
        _, failures = self.push("tipee 08:00-09:00 ok\ntipee -10:00 overlap\ntipee -11:00 invalid\ntipee -12:00 fine",
                                tipee=tipee, backend=make_backend({'merge': 'false'}))

        self.assertEqual(failures, {
            'overlap': '[tipee] Un timbrage ne peut pas en chevaucher un autre.',
            'invalid': '[tipee] out: Timecheck end time (out) must be after start time (in).',
        })

    def test_an_entry_ending_in_the_future_is_not_sent(self):
        with mock.patch('taxi_tipee.backend.now', return_value=datetime.datetime(2026, 11, 14, 9, 30)):
            tipee, failures = self.push("tipee 08:00-09:00 done\ntipee 09:15-10:00 not yet")

        self.assertEqual(len(tipee.proposals), 1)
        self.assertEqual(failures, {'not yet': '[tipee] ends in the future: tipee only takes an entry once it is over.'})

    def test_a_refused_token_says_so(self):
        tipee = FakeTipee()
        tipee.post = lambda url, **kwargs: response(401, {'message': 'You must be logged in to access this resource.'})
        _, failures = self.push("tipee 08:00-09:00 a", tipee=tipee)

        self.assertIn('refused the API token', failures['a'])

    def test_what_tipee_says_to_retry_is_retried(self):
        tipee = FakeTipee(propose=[
            response(429, {'message': 'Too many requests'}, headers={'Retry-After': '3'}),
            response(500, {'detail': 'Internal error'}),
            response(201, {'id': '1'}),
        ])
        tipee, failures = self.push("tipee 08:00-09:00 a", tipee=tipee)

        self.assertEqual(failures, {})
        self.assertEqual(len(tipee.proposals), 3)
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [3.0, 2])

    def test_retries_give_up_in_the_end(self):
        tipee = FakeTipee(propose=[response(504, None)] * 4)
        tipee, failures = self.push("tipee 08:00-09:00 a", tipee=tipee)

        self.assertEqual(len(tipee.proposals), 4)
        self.assertEqual(failures, {'a': '[tipee] HTTP 504: '})

    def test_maintenance_is_not_retried(self):
        tipee = FakeTipee(propose=[response(503, None)])
        tipee, failures = self.push("tipee 08:00-09:00 a", tipee=tipee)

        self.assertEqual(len(tipee.proposals), 1)
        self.assertIn('under maintenance', failures['a'])

    def test_an_unreachable_tipee_fails_the_entries(self):
        tipee = FakeTipee()
        tipee.post = mock.Mock(side_effect=requests.ConnectionError('Name or service not known'))
        _, failures = self.push("tipee 08:00-09:00 a", tipee=tipee)

        self.assertIn('could not reach tipee.example', failures['a'])

    def test_durations_in_hours_are_refused(self):
        backend = make_backend()
        entries = EntriesCollection(TimesheetParser(), "14/11/2026\ntipee 2 a")
        with self.assertRaisesRegex(PushEntryFailed, 'durations as hours'):
            backend.push_entry(datetime.date(2026, 11, 14), entries[datetime.date(2026, 11, 14)][0])


class ConfigurationTest(unittest.TestCase):
    def test_the_old_url_format_is_explained(self):
        with self.assertRaisesRegex(ValueError, 'old format'):
            make_backend({'person': '169'}, token='key', username='timbreuse')

    def test_the_person_is_whose_timechecks_are_proposed(self):
        self.assertEqual(make_backend({'person': '42'}).resource_id, '42')

    def test_the_person_is_required(self):
        for options in ({'person': ''}, {'person': 'me'}):
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, r'\?person=<your user id>'):
                    make_backend(options)

    def test_a_token_is_required(self):
        with self.assertRaisesRegex(ValueError, 'no API token'):
            make_backend(token=None)

    def test_remark_takes_known_values_only(self):
        with self.assertRaisesRegex(ValueError, '`remark`'):
            make_backend({'remark': 'yes'})

    def test_merge_takes_known_values_only(self):
        with self.assertRaisesRegex(ValueError, '`merge`'):
            make_backend({'merge': 'no'})


if __name__ == '__main__':
    unittest.main()
