import datetime
import unittest
from unittest import mock

from taxi.exceptions import ParseError
from taxi.timesheet.entry import EntriesCollection, EntriesCollectionValidationError
from taxi.timesheet.parser import TimesheetParser

from taxi_tipee.backend import TipeeBackend


def make_backend():
    return TipeeBackend(
        username='app',
        password='key',
        hostname='tipee.example',
        port=None,
        path='/api',
        options={'person': '1'},
        context={'settings': {'regroup_entries': False}},
    )


class EntriesPastMidnightTest(unittest.TestCase):
    def setUp(self):
        # Installs the patch, as Taxi does by loading the backend before it
        # reads the timesheet.
        make_backend()

    def parse(self, body):
        return EntriesCollection(TimesheetParser(), "14/11/2026\n" + body)

    def push(self, body):
        """
        Push the entries of `body` and return the (in, out) times sent to tipee.
        """
        backend = make_backend()
        entries = self.parse(body)
        for date, date_entries in entries.items():
            for entry in date_entries:
                backend.push_entry(date, entry)

        response = mock.Mock(status_code=200)
        response.json.return_value = [{'success': True}, {'success': True}]
        with mock.patch('taxi_tipee.backend.requests.post', return_value=response) as post:
            backend.post_push_entries()

        return [
            tuple(timecheck['time'] for timecheck in call.kwargs['json'])
            for call in post.call_args_list
        ]

    def hours(self, body):
        return [entry.hours for entry in self.parse(body)[datetime.date(2026, 11, 14)]]

    def test_an_entry_can_end_at_midnight(self):
        for end in ('00:00', '24:00', '2400'):
            with self.subTest(end=end):
                body = f"tipee 22:15-{end} late"
                self.assertEqual(self.hours(body), [1.75])
                self.assertEqual(self.push(body), [('2026-11-14 22:15:00', '2026-11-15 00:00:00')])

    def test_an_entry_can_end_past_midnight(self):
        body = "tipee 22:15-01:15 late"
        self.assertEqual(self.hours(body), [3.0])
        self.assertEqual(self.push(body), [('2026-11-14 22:15:00', '2026-11-15 01:15:00')])

    def test_an_entry_past_midnight_can_continue_the_previous_one(self):
        body = "tipee 20:00-22:15 evening\ntipee -01:15 late"
        self.assertEqual(self.hours(body), [2.25, 3.0])
        self.assertEqual(self.push(body), [('2026-11-14 20:00:00', '2026-11-15 01:15:00')])

    def test_the_end_stays_written_as_24_00(self):
        entries = self.parse("tipee 22:15-24:00 late")
        entries[datetime.date(2026, 11, 14)][0].pushed = True
        self.assertEqual(entries.to_lines(), ["14/11/2026", "= tipee 22:15-24:00 late"])

    def test_the_day_goes_on_past_midnight(self):
        body = "tipee 20:00-22:15 evening\ntipee -00:15 late\ntipee 00:30-01:00 later\ntipee -01:30 last"
        self.assertEqual(self.hours(body), [2.25, 2.0, 0.5, 0.5])
        self.assertEqual(self.push(body), [('2026-11-14 20:00:00', '2026-11-15 00:15:00'),
                                           ('2026-11-15 00:30:00', '2026-11-15 01:30:00')])

    def test_entries_after_midnight_merge_with_the_one_ending_at_midnight(self):
        body = "tipee 22:15-24:00 late\ntipee 00:00-01:00 later"
        self.assertEqual(self.push(body), [('2026-11-14 22:15:00', '2026-11-15 01:00:00')])

    def test_entries_after_midnight_are_pushed_in_order(self):
        # The day's entries are sorted before pushing: by time of day alone,
        # 00:30 would come first.
        body = "tipee 21:00-22:00 b\ntipee 20:00-20:30 a\ntipee 22:30-00:15 c\ntipee 00:30-01:00 d"
        self.assertEqual(self.push(body), [('2026-11-14 20:00:00', '2026-11-14 20:30:00'),
                                           ('2026-11-14 21:00:00', '2026-11-14 22:00:00'),
                                           ('2026-11-14 22:30:00', '2026-11-15 00:15:00'),
                                           ('2026-11-15 00:30:00', '2026-11-15 01:00:00')])

    def test_a_day_goes_past_midnight_only_once(self):
        for body in ("tipee 22:15-01:15 late\ntipee 01:30-01:00 again",
                     "tipee 22:15-24:00 late\ntipee 00:00-01:00 later\ntipee 23:00-00:30 again"):
            with self.subTest(body=body):
                with self.assertRaisesRegex(EntriesCollectionValidationError, "only once"):
                    self.parse(body)

    def test_entries_after_midnight_lie_between_its_end_and_noon(self):
        for body in ("tipee 22:00-00:15 late\ntipee 23:00-23:30 earlier",
                     "tipee 22:00-00:15 late\ntipee 00:00-00:30 overlapping",
                     "tipee 22:00-00:15 late\ntipee 20:00-21:00 evening, written below",
                     "tipee 22:00-00:15 late\ntipee 11:00-12:30 past noon"):
            with self.subTest(body=body):
                with self.assertRaisesRegex(EntriesCollectionValidationError, "between 00:15 and 12:00"):
                    self.parse(body)
        self.assertEqual(self.hours("tipee 22:00-00:15 late\ntipee 11:00-12:00 noon"), [2.25, 1.0])

    def test_an_entry_past_midnight_lasts_less_than_12_hours(self):
        self.assertEqual(self.hours("tipee 20:00-07:59 night"), [11.983333333333333])
        for body in ("tipee 09:00-12:00 morning\ntipee 13:00-12:00 typo",
                     "tipee 20:00-08:00 night",
                     "tipee 22:15-22:15 nothing"):
            with self.subTest(body=body):
                with self.assertRaisesRegex(EntriesCollectionValidationError, "back in time"):
                    self.parse(body)

    def test_other_times_past_24_00_are_still_refused(self):
        for end in ('24:15', '25:00'):
            with self.subTest(end=end):
                with self.assertRaises(ParseError):
                    self.parse(f"tipee 22:15-{end} late")

    def test_entries_within_a_day_are_unchanged(self):
        body = "tipee 08:00-09:00 a\ntipee -10:30 b\ntipee 13:00-14:00 c"
        self.assertEqual(self.hours(body), [1.0, 1.5, 1.0])
        self.assertEqual(self.push(body), [("2026-11-14 08:00:00", "2026-11-14 10:30:00"),
                                           ("2026-11-14 13:00:00", "2026-11-14 14:00:00")])


if __name__ == '__main__':
    unittest.main()
