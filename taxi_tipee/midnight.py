"""
Let an entry end at or past midnight: ``22:15-24:00``, ``22:15-00:00`` or
``22:15-01:15``, and the day's work go on after it: a work day ends when its
last entry does, not at midnight.

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
  lasts less than 12 hours (so that a typo like ``13:00-12:00`` is still
  refused rather than pushed as 23 hours, and ``22:15-22:15`` as 24);
* the entries after it on the same day are on the next day too
  (:func:`after_midnight`, which the backend adds a day for). They must lie
  between its end and noon, so that an evening entry written below it by
  mistake is refused rather than pushed a day late, and none of them may go
  past midnight again. (The entry going past midnight lasts less than 12
  hours, so it started after noon: the day spans less than 24 hours.)
* without such an entry, a line that starts before 06:00 and before the
  line above it ends starts the night (:func:`opens_night`): work that
  stopped before midnight and went on after it. It and the entries after it
  are on the next day, and must end by noon and by the start of the day's
  first entry, so that the day still spans less than 24 hours. A line
  written out of order during the day (``21:00-22:00`` then ``20:00-20:30``)
  starts after 06:00, and stays on its day.

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
LATEST_END_AFTER_MIDNIGHT = datetime.time(MAX_HOURS_PAST_MIDNIGHT, 0)
# A line starting before this, and before the line above it ends, starts the
# night when no entry of its day goes past midnight.
LATEST_NIGHT_START = datetime.time(6, 0)

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


def crossing_entry(entry):
    """
    Return the entry before `entry` on its day that ends past midnight, or
    None.
    """
    previous_entry = entry.previous_entry
    while previous_entry is not None:
        if ends_next_day(previous_entry):
            return previous_entry
        previous_entry = previous_entry.previous_entry

    return None


def explicit_start(entry):
    """
    Return the start written on the entry's line, or None (a duration, or a
    line like ``-10:00`` that starts when the previous one ends).
    """
    if not isinstance(entry.duration, tuple):
        return None

    return entry.duration[0]


def opens_night(entry):
    """
    Return whether the entry starts the night without an entry going past
    midnight: it starts before 06:00 and before the line above it ends, with
    no entry of its day past midnight before it.
    """
    start = explicit_start(entry)
    previous_entry = entry.previous_entry
    if start is None or start >= LATEST_NIGHT_START or previous_entry is None:
        return False
    if not isinstance(previous_entry.duration, tuple) or previous_entry.duration[1] is None:
        return False
    if crossing_entry(entry) is not None or night_opener(previous_entry) is not None:
        return False

    return start < previous_entry.duration[1]


def night_opener(entry):
    """
    Return the entry that started the night (see :func:`opens_night`) among
    `entry` and the ones before it on its day, or None.
    """
    while entry is not None:
        if opens_night(entry):
            return entry
        entry = entry.previous_entry

    return None


def first_entry(entry):
    """
    Return the first entry of `entry`'s day.
    """
    while entry.previous_entry is not None:
        entry = entry.previous_entry

    return entry


def after_midnight(entry):
    """
    Return whether the entry is on the next day: it comes after one ending
    past midnight on its day, or it or an entry before it started the night.
    """
    return crossing_entry(entry) is not None or night_opener(entry) is not None


def check(entry):
    """
    Return why the entry cannot be read, given the entries before it on its
    day, or None.
    """
    crossing = crossing_entry(entry)
    start = entry.get_start_time() if isinstance(entry.duration, tuple) else None
    end = entry.duration[1] if isinstance(entry.duration, tuple) else None

    if crossing is not None:
        crossing_end = crossing.duration[1]
        latest_end = LATEST_END_AFTER_MIDNIGHT
        if ends_next_day(entry):
            return (
                "An earlier entry of this day already goes past midnight, and a day can go past "
                "it only once. Put this entry under the next day."
            )
        if (start is not None and start < crossing_end) or (end is not None and end > latest_end):
            return (
                "An earlier entry of this day goes past midnight, so this one is the next day: it "
                f"must lie between {crossing_end:%H:%M} and {latest_end:%H:%M}."
            )
    elif night_opener(entry) is not None:
        opener = night_opener(entry)
        night_start = opener.duration[0]
        day_start = first_entry(entry).get_start_time()
        latest_end = min(LATEST_END_AFTER_MIDNIGHT, day_start) if day_start else LATEST_END_AFTER_MIDNIGHT
        if ends_next_day(entry):
            return (
                "An earlier line of this day starts the night, and a day can go past midnight "
                "only once. Put this entry under the next day."
            )
        if (start is not None and start < night_start) or (end is not None and end > latest_end):
            return (
                f"This line starts the night, or follows one that does ({night_start:%H:%M}, before "
                f"the line above it ends): it is the next day, and must lie between "
                f"{night_start:%H:%M} and {latest_end:%H:%M}."
            )
    elif ends_next_day(entry) and not 0 < entry.hours < MAX_HOURS_PAST_MIDNIGHT:
        return (
            "The entry cannot go back in time. An entry may end past midnight, but only "
            f"if it lasts less than {MAX_HOURS_PAST_MIDNIGHT} hours."
        )

    return None


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

            message = check(line)
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
