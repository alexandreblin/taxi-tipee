tipee backend for Taxi
======================

This is the [Taxi](https://github.com/sephii/taxi) backend for [tipee](https://tipee.ch). It
exposes the `tipee` protocol to push entries as timecheck proposals, through
[tipee's API](https://api.tipee.ch/guides-and-resources/first-steps).

Installation
------------

```shell
taxi plugin install tipee
```

Configuration
-------------

### Create an API token

The backend authenticates with a personal API token, which carries your own permissions. There is no
screen for it in tipee yet: log into your instance, open the browser's developer tools, and run this in
the console:

```js
fetch('/api/security/tokens.create', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'taxi' }),
}).then(r => r.json()).then(console.log)
```

It answers `{ id, token }`; the token looks like `tipee-0123abcd-…`. It expires after 90 days without
use (each push counts as one). Keep the `id`: `/api/security/tokens.revoke` with `{ "id": … }` revokes
the token the same way, and `/api/security/tokens.list` with `{ "resource": … }` (your user id) lists
yours.

### Set up the backend

Run `taxi config` and use the `tipee` protocol for your backend:

```ini
[backends]
my_tipee_backend = tipee://[token]@[instance].tipee.net/api/

[taxi]
regroup_entries = false
```

* `[token]` is the API token created above
* `[instance]` is tipee's instance name

Options, as query string arguments:

* `remark=description` sends each entry's description as the proposal's remark (cut at 255 characters),
  so that it shows in tipee. Off by default: tipee gets the times and nothing else.
* `scheme=http` can be useful when developing (using `localhost:port` as the hostname).

The backend finds out who you are from the token, so the `?person=` of earlier versions is gone. Your
account needs the right to suggest timechecks, or to validate your own.

> Upgrading from 1.x: the `[app_name]:[app_private_key]` URL with `?person=` went to tipee's legacy
> timeclock API, which needed a key from tipee's server configuration and created timechecks you
> could not edit. Create a token and replace the URL as above.

Usage
-----

You can now add timesheet entries like :

```
19/05/2020 # Tuesday
tipee    08:00-09:00    Monitoring server
tipee         -10:30    Fixing bug
tipee         -?        Work in progress...
```

Things you should know
----------------------

### Entries become proposals

Each entry is pushed as its own timecheck proposal, which you can still edit or delete in tipee as long
as it is not validated. Depending on your rights, someone may have to validate it.

tipee refuses a proposal that overlaps an existing timecheck, so pushing the same hours twice fails
rather than counting them twice. It also refuses one that ends in the future: push an entry once it is
over.

### Duration as hours is not supported

As stated in [Taxi's documentation](https://taxi-timesheets.readthedocs.io/en/master/userguide.html#timesheet-syntax) :

> duration can either be a time range or a duration in hours. If it’s a time range, it should be in the format start-end, where start can be left blank if the previous entry also used a time range and had a time defined, and end can be ? if the end time is not known yet, leading to the entry being ignored. Each part of the range should have the format HH:mm, or HHmm. If duration is a duration, it should just be a number, eg. 2 for 2 hours, or 1.75 for 1 hour and 45 minutes.

However, tipee requires timechecks to have a specific start and end time, so a proper error will be thrown if you do not provide a time range.

### Regrouping entries is not supported

By default, [Taxi](https://taxi-timesheets.readthedocs.io/en/master/userguide.html#regroup-entries) regroups entries to commit them. So if you have 3 different entries on a day with the same alias and description, it will push only one entry with the cumulated times. In tipee, this leads to timesheets overlapping each others, which are explicitly prohibited. So you need to set the option to `false` :

```
[taxi]
regroup_entries = false
```

### Entries can end past midnight

Taxi itself refuses an entry that does not end after it starts, and cannot read `24:00`. With this
backend installed, an entry may end at or past midnight, and the day may go on after it: a work day
ends when you stop working, not at midnight.

```
14/11/2026 # Saturday
tipee    20:00-22:15    Release
tipee         -00:15    Checking the release
tipee    00:30-01:00    Hotfix
```

`22:15-24:00` and `22:15-00:00` both end at midnight. The entry is pushed as a timecheck ending on the
next day, the entries after it are pushed on the next day, and tipee counts each day's share. A few
rules catch mistakes:

* the entry going past midnight must last less than 12 hours, so that a typo like `13:00-12:00` is
  still refused;
* a day goes past midnight only once;
* the entries after it must lie between its end and noon, so that an evening entry written below it by
  mistake is refused rather than pushed a day late.

This works by adjusting how Taxi reads timesheets, which is written for Taxi 6: on another major version,
Taxi keeps refusing these entries.

Testing
-------

```shell
nix develop --command python -m unittest discover -s tests
```

Releasing
---------

Publish a [GitHub release](https://github.com/alexandreblin/taxi-tipee/releases/new) with a new tag
named after the version (like `1.0.11`), from the web interface or with:

```shell
gh release create 1.0.11 --generate-notes
```

The `release` GitHub Actions workflow builds the package (the version comes from the tag, through
[setuptools-scm](https://setuptools-scm.readthedocs.io)), publishes it to PyPI as a
[trusted publisher](https://docs.pypi.org/trusted-publishers/), so no API token is needed, and attaches
the files to the release.

To build locally, `nix develop` (or direnv) provides Python and the tools: `python -m build --no-isolation`.
