Gammadia's tipee backend for Taxi
=================================

This is the [Taxi](https://github.com/sephii/taxi) backend for Gammadia's [tipee](https://tipee.ch). It
exposes the `tipee` protocol to push entries as timechecks.

Installation
------------

```shell
taxi plugin install tipee
```

Usage
-----

In your `.taxirc` file, use the `tipee` protocol for your backend.

```ini
[backends]
my_tipee_backend = tipee://app_name:app_private_key@instance.tipee.net/api/?person=person_id
```

There is an extra `scheme=http` argument that can be useful when using a local instance (and you can use `localhost:port` too).

To auto-generate taxi aliases, you can specify your JIRA projects as follow:

```ini
[tempo_projects]
infra = 10000
ops = 1000
dev = 100
```

The numbers represent the range of JIRA tickets being aliased (DEV-1, DEV-2, DEV-3, ..., DEV-100).
