# How the charm decides what a configuration change requires

Every event the charm observes funnels into one idempotent reconciliation, and
that function's job is to make the broker match the charm's inputs — Juju config,
the users it knows about, the certificates it has been issued, the relations that
exist — regardless of the order events arrived in.

The interesting part is the last step: having rendered what the configuration
ought to be, what does applying it cost?

## Directives, not files

The charm renders its configuration into fragments it owns outright, then
compares the new text with what is on disk **at the level of individual
directives**, not as text. Both sides are parsed into `(directive, value)` pairs,
with comments dropped and whitespace normalised.

That matters because otherwise any change to a comment, or any reordering, would
look like a change to the broker's behaviour, and the charm would restart for a
difference nobody can observe.

Order is still preserved in the comparison, though, because `listener` blocks are
positional: the directives after a `listener` line belong to that listener. A
reordering with no changed pairs is therefore treated as needing a restart, since
it may have moved a TLS directive from one listener to another.

## The decision

The symmetric difference between the old and new directive sets gives the names
that changed. If every one of them is in the charm's reload-safe set, the change
is a reload. Otherwise it is a restart.

**Anything not positively known to be reload-safe is restarted.** The
reload-safe list differs between Mosquitto 2.0 and 2.1, and the two errors are
not symmetric: an unnecessary restart costs a reconnection, while an unnecessary
reload leaves the broker running a configuration nobody asked for while the charm
reports success. So the charm errs towards the cheaper mistake.

The same classification runs over each fragment separately — the main
configuration, the bridge, and `extra-config` — along with the password file, the
ACL file, the TLS material and the systemd drop-in, each of which reports what it
needs. The strongest requirement wins: none, then reload, then restart.

## Which pieces report what

| What changed | What it needs |
| --- | --- |
| The password file | reload |
| The ACL file | reload |
| TLS certificate or key contents, at unchanged paths | reload |
| The bridge authority certificate | reload |
| The charm's main fragment | whatever the changed directives imply |
| `extra-config` | the same, for whatever you put in it |
| The systemd drop-in, for instance `open-file-limit` | restart |
| The main `mosquitto.conf` itself | restart — it is read only at startup |

## Then it checks

`systemctl reload` is asynchronous: it succeeds even when the broker then rejects
what it was asked to re-read. `systemctl restart` can fail outright. Either way
the charm does not take the service manager's word for it.

If the broker will not come up, the charm records the reason, logs the tail of
the broker's journal — which is the only place that says what was actually wrong
with the configuration — and puts the unit into blocked status with the broker's
own complaint, rather than failing the hook with a traceback you would have to go
and find.

Mosquitto 2.1 has `mosquitto --test-config`, a genuine dry run. 2.0, which is
what the Ubuntu archive ships, has nothing of the sort, which is why the charm
validates what it can itself and health-checks afterwards.

## Why the charm owns `mosquitto.conf`

The packaged `/etc/mosquitto/mosquitto.conf` already sets `persistence`,
`persistence_location` and `log_dest`, and Mosquitto refuses to start when a
directive is set twice in any file. The charm cannot simply add a fragment
alongside it.

So it replaces the main file with nothing but an `include_dir` line, and puts
everything real in fragments it owns. The original is saved once, as
`mosquitto.conf.charm-orig`, so that removing the charm leaves you something to
go back to.

Every directive the charm cares about is written out explicitly, even where the
value matches Mosquitto's own default. Relying on a default is how a broker's
behaviour changes silently across an upgrade: `max_packet_size` alone went from
unlimited to 2000000 between 2.0 and 2.1.

## When it has drifted anyway

If something on the unit has been edited by hand, the charm's idea of what is on
disk and what is actually there can disagree in ways a diff will not resolve.

```shell
juju run mosquitto/0 force-reconfigure
```

That deletes the charm's fragments, re-renders them, and reconciles
unconditionally.

## Related

- [Reload versus restart](reload-versus-restart.md)
- [Configuration options](../reference/configuration.md)
