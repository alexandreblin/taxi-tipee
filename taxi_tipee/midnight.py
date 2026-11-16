"""
Let the last entry of a day end at or past midnight: ``22:15-24:00``,
``22:15-00:00`` or ``22:15-01:15``.

Taxi refuses an entry whose end is not after its start ("The entry cannot go
back in time") and cannot parse ``24:00``, which leaves no way to write the
end of a late evening: its answer is to split the entry over two days, at
23:59. tipee has no such limit: a timecheck may close the next day, and tipee
counts each day's share of it.

Taxi already counts such an entry's hours right (``Entry.hours`` reads
``timedelta.seconds``, which wraps past midnight), and the backend pushes the
end as start + duration, which lands on the next day. Only the parser and
that one check stand in the way, so this module relaxes both:

* ``24:00`` is read as ``00:00``, and stays written as ``24:00``: Taxi only
  rewrites the parts of a line it changes;
* an entry that ends at or before its start ends the next day, provided it
  is the last entry of its day (an entry after it would be pushed on the
  wrong date) and lasts less than 12 hours (so that a typo like
  ``13:00-12:00`` is still refused rather than pushed as 23 hours, and
  ``22:15-22:15`` as 24).

Taxi loads its backends before it reads a timesheet, so installing this from
the backend's constructor is early enough for every command.
"""
import datetime
import logging

from taxi import __version__ as taxi_version
from taxi.timesheet import parser as taxi_parser
from taxi.timesheet.entry import EntriesCollection, EntriesCollectionValidationError, Entry
from taxi.timesheet.lines import DateLine

logger = logging.getLogger(__name__)

MAX_HOURS_PAST_MIDNIGHT = 12

_create_time_from_text = taxi_parser.create_time_from_text
_installed = False


def create_time_from_text(text):
    if text.replace(':', '') == '2400':
        return datetime.time(0, 0)

    return _create_time_from_text(text)


def ends_next_day(entry):
    """
    Return whether the entry ends at or before its start, so the next day.
    """
    if not isinstance(entry.duration, tuple) or entry.duration[1] is None:
        return False

    start = entry.get_start_time()

    return start is not None and entry.duration[1] <= start


def init_from_str(self, entries):
    """
    Taxi's ``EntriesCollection.init_from_str`` (6.3), with the check that an
    entry ends after it starts replaced by the rules in this module's
    docstring.
    """
    self.lines = self.parser.parse_text(entries)

    for lineno, line in enumerate(self.lines, 1):
        if isinstance(line, DateLine):
            current_date = line.date
            self[current_date] = self.default_factory(self, line.date)
        elif isinstance(line, Entry):
            previous_entry = self[current_date][-1] if len(self[current_date]) > 0 else None
            if previous_entry is not None:
                line.previous_entry = previous_entry
                previous_entry.next_entry = line

            message = None
            if previous_entry is not None and ends_next_day(previous_entry):
                message = (
                    "The previous entry ends past midnight, so it must be the last one of its day. "
                    "Put this entry under the next day."
                )
            elif ends_next_day(line) and not 0 < line.hours < MAX_HOURS_PAST_MIDNIGHT:
                message = (
                    "The entry cannot go back in time. An entry may end past midnight, but only "
                    f"if it lasts less than {MAX_HOURS_PAST_MIDNIGHT} hours."
                )

            if message is not None:
                raise EntriesCollectionValidationError(
                    line=" ".join(line._text).strip(),
                    line_number=lineno,
                    message=message,
                )

            self[current_date].append(line)


def install():
    """
    Patch Taxi so that it accepts entries ending past midnight. Only for the
    Taxi major version this was written against: another one may have changed
    the method replaced here, and then keeps refusing such entries.
    """
    global _installed

    if _installed:
        return

    if taxi_version.split('.')[0] != '6':
        logger.warning(
            "taxi-tipee: entries past midnight are only supported on Taxi 6, not %s", taxi_version
        )
        return

    taxi_parser.create_time_from_text = create_time_from_text
    EntriesCollection.init_from_str = init_from_str
    _installed = True
