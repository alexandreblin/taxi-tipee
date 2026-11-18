import datetime
import unittest

from taxi.exceptions import ParseError
from taxi.timesheet.entry import EntriesCollection, EntriesCollectionValidationError
from taxi.timesheet.parser import TimesheetParser

from fake_tipee import FakeTipee, make_backend


class EntriesPastMidnightTest(unittest.TestCase):
    def setUp(self):
        # Installs the patch, as Taxi does by loading the backend before it
        # reads the timesheet.
        make_backend()

    def parse(self, body):
        return EntriesCollection(TimesheetParser(), "14/11/2026\n" + body)

    def push(self, body):
        """
        Push the entries of `body` and return the (in, out) times proposed to
        tipee.
        """
        backend = make_backend()
        entries = self.parse(body)
        for date, date_entries in entries.items():
            for entry in date_entries:
                backend.push_entry(date, entry)

        tipee = FakeTipee()
        with tipee.patch():
            backend.post_push_entries()

        return [(proposal['in'], proposal['out']) for proposal in tipee.proposals]

    def hours(self, body):
        return [entry.hours for entry in self.parse(body)[datetime.date(2026, 11, 14)]]

    def test_an_entry_can_end_at_midnight(self):
        for end in ('00:00', '24:00', '2400'):
            with self.subTest(end=end):
                body = f"tipee 22:15-{end} late"
                self.assertEqual(self.hours(body), [1.75])
                self.assertEqual(self.push(body), [('2026-11-14T22:15:00', '2026-11-15T00:00:00')])

    def test_an_entry_can_end_past_midnight(self):
        body = "tipee 22:15-01:15 late"
        self.assertEqual(self.hours(body), [3.0])
        self.assertEqual(self.push(body), [('2026-11-14T22:15:00', '2026-11-15T01:15:00')])

    def test_an_entry_past_midnight_can_continue_the_previous_one(self):
        body = "tipee 20:00-22:15 evening\ntipee -01:15 late"
        self.assertEqual(self.hours(body), [2.25, 3.0])
        self.assertEqual(self.push(body), [('2026-11-14T20:00:00', '2026-11-15T01:15:00')])

    def test_the_end_stays_written_as_24_00(self):
        entries = self.parse("tipee 22:15-24:00 late")
        entries[datetime.date(2026, 11, 14)][0].pushed = True
        self.assertEqual(entries.to_lines(), ["14/11/2026", "= tipee 22:15-24:00 late"])

    def test_the_day_goes_on_past_midnight(self):
        body = "tipee 20:00-22:15 evening\ntipee -00:15 late\ntipee 00:30-01:00 later\ntipee -01:30 last"
        self.assertEqual(self.hours(body), [2.25, 2.0, 0.5, 0.5])
        self.assertEqual(self.push(body), [('2026-11-14T20:00:00', '2026-11-15T00:15:00'),
                                           ('2026-11-15T00:30:00', '2026-11-15T01:30:00')])

    def test_entries_after_midnight_merge_with_the_one_ending_at_midnight(self):
        body = "tipee 22:15-24:00 late\ntipee 00:00-01:00 later"
        self.assertEqual(self.push(body), [('2026-11-14T22:15:00', '2026-11-15T01:00:00')])

    def test_entries_after_midnight_are_pushed_in_order(self):
        # The day's entries are sorted before pushing: by time of day alone,
        # 00:30 would come first.
        body = "tipee 21:00-22:00 b\ntipee 20:00-20:30 a\ntipee 22:30-00:15 c\ntipee 00:30-01:00 d"
        self.assertEqual(self.push(body), [('2026-11-14T20:00:00', '2026-11-14T20:30:00'),
                                           ('2026-11-14T21:00:00', '2026-11-14T22:00:00'),
                                           ('2026-11-14T22:30:00', '2026-11-15T00:15:00'),
                                           ('2026-11-15T00:30:00', '2026-11-15T01:00:00')])

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

    def test_a_line_starting_before_the_one_above_ends_starts_the_night(self):
        body = "tipee 09:30-17:35 day\ntipee 01:10-01:40 night"
        self.assertEqual(self.hours(body), [8.083333333333334, 0.5])
        self.assertEqual(self.push(body), [('2026-11-14T09:30:00', '2026-11-14T17:35:00'),
                                           ('2026-11-15T01:10:00', '2026-11-15T01:40:00')])

    def test_the_night_goes_on_after_the_line_that_starts_it(self):
        body = "tipee 19:30-20:30 evening\ntipee 00:15-00:50 night\ntipee -01:30 later\ntipee 02:00-02:30 last"
        self.assertEqual(self.push(body), [('2026-11-14T19:30:00', '2026-11-14T20:30:00'),
                                           ('2026-11-15T00:15:00', '2026-11-15T01:30:00'),
                                           ('2026-11-15T02:00:00', '2026-11-15T02:30:00')])

    def test_a_line_written_out_of_order_during_the_day_stays_on_its_day(self):
        for body in ("tipee 13:00-18:00 afternoon\ntipee 09:00-09:15 Daily",
                     "tipee 07:00-08:00 morning\ntipee 06:00-06:30 earlier"):
            with self.subTest(body=body):
                self.assertEqual([start[:10] for start, _ in self.push(body)],
                                 ['2026-11-14', '2026-11-14'])

    def test_the_night_ends_before_the_day_started_and_by_noon(self):
        for body, bound in (("tipee 04:00-09:00 early\ntipee 03:00-04:30 night", "04:00"),
                            ("tipee 13:00-18:00 day\ntipee 05:00-12:30 morning", "12:00"),
                            ("tipee 09:00-18:00 day\ntipee 01:00-02:00 night\ntipee 08:00-10:00 next morning", "09:00")):
            with self.subTest(body=body):
                with self.assertRaisesRegex(EntriesCollectionValidationError, f"and {bound}"):
                    self.parse(body)

    def test_the_lines_after_the_one_starting_the_night_keep_their_order(self):
        with self.assertRaisesRegex(EntriesCollectionValidationError, "between 01:00 and"):
            self.parse("tipee 09:00-18:00 day\ntipee 01:00-02:00 night\ntipee 00:30-00:45 earlier")

    def test_a_night_started_by_a_line_goes_past_midnight_only_once(self):
        with self.assertRaisesRegex(EntriesCollectionValidationError, "only once"):
            self.parse("tipee 09:00-18:00 day\ntipee 01:00-02:00 night\ntipee 05:00-04:00 again")

    def test_entries_within_a_day_are_unchanged(self):
        body = "tipee 08:00-09:00 a\ntipee -10:30 b\ntipee 13:00-14:00 c"
        self.assertEqual(self.hours(body), [1.0, 1.5, 1.0])
        self.assertEqual(self.push(body), [("2026-11-14T08:00:00", "2026-11-14T10:30:00"),
                                           ("2026-11-14T13:00:00", "2026-11-14T14:00:00")])


if __name__ == '__main__':
    unittest.main()
