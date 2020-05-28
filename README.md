Gammadia's tipee backend for Taxi
=================================

This is the [Taxi](https://github.com/sephii/taxi) backend for Gammadia's [tipee](https://tipee.ch). It
exposes the `tipee` protocol to push entries as timechecks.

Installation
------------

```shell
taxi plugin install tipee
```

Configuration
-------------

Run `taxi config` and use the `tipee` protocol for your backend :

```ini
[backends]
my_tipee_backend = tipee://[app_name]:[app_private_key]@[instance].tipee.net/api/?person=[person_id]

[taxi]
regroup_entries = false
```

* `[app_name]` and `[app_private_key]` can be found in tipee's PHP configuration files, like
`$_CONFIG['PrivateKey']['timbreuse'] = 'fK19psLpm17u660fCiJ5s569bfeij2s800y';` for example, so here you would use 
`timbreuse:fK19psLpm17u660fCiJ5s569bfeij2s800y`
* `[instance]` is tipee's instance name
* `[person_id]` is the ID of your
user, which can be found in the URL when editing your profile, like `https://gammadia.tipee.net/person/#/169`

> There is an extra `scheme=http` query string argument that can be useful when developing (using `localhost:port` as the hostname).

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

### Duration as hours is not supported

As stated in [taxi's documentation](https://taxi-timesheets.readthedocs.io/en/master/userguide.html#timesheet-syntax) :

> duration can either be a time range or a duration in hours. If it’s a time range, it should be in the format start-end, where start can be left blank if the previous entry also used a time range and had a time defined, and end can be ? if the end time is not known yet, leading to the entry being ignored. Each part of the range should have the format HH:mm, or HHmm. If duration is a duration, it should just be a number, eg. 2 for 2 hours, or 1.75 for 1 hour and 45 minutes.

However, tipee requires timechecks to have specific time start and end, so a proper error will be thrown if you do not provide a time range.

### Regrouping entries is not supported

By default, [taxi](https://taxi-timesheets.readthedocs.io/en/master/userguide.html#regroup-entries) regroups entries to commit them. So if you have 3 different entries on a day with the same alias and description, it will push only one entry with the cumulated times. In tipee, this leads to timesheets overlapping each others, which are explicitly prohibited. So you need to set the option to `false` :

```
[taxi]
regroup_entries = false
```
