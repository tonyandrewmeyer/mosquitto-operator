# Back up and restore

The charm can take a copy of the broker's own state — the persistence database,
the password file, the ACL file, the rendered configuration fragments and the TLS
material — as one tarball on the unit.

This is a snapshot of the *workload*, not a whole-application backup. The
passwords themselves live in Juju secrets and the record of who should exist
lives in the peer relation, so neither is in the tarball, and the charm rewrites
the password and ACL files from those at the next reconciliation. Rebuilding from
nothing means deploying the charm with the same configuration and restoring the
tarball into it; see [What is not in the backup](#what-is-not-in-the-backup).

## Take a backup

```shell
juju run mosquitto/0 create-backup
```

```
path: /var/lib/mosquitto/backups/mosquitto-20260915T110402Z.tar.gz
size: "18423"
```

To write it somewhere else — another filesystem, a mounted share — pass a path to
a directory that already exists. The backup is written as root, so the charm
treats the path as it treats a tarball being restored: it must not already exist,
it must be absolute, the charm will not create directories outside its own backup
directory, and it will not write into the places the system reads files from
(`/etc`, `/usr`, `/bin`, `/sbin`, `/lib`, `/boot`, `/root`, `/run`, `/dev`,
`/proc`, `/sys`, `/var/lib/juju`). Between them those stop an operator who can run
actions but not `juju ssh` from using the action to overwrite a file, or to leave a
root-owned one somewhere that matters.

```shell
juju run mosquitto/0 create-backup path=/mnt/backups/mosquitto-nightly.tar.gz
```

The backup directory lives under the charm's `data` storage, so on a cloud where
that storage is separate from the root disk the default location survives the
machine.

### What "point in time" means here

Mosquitto writes its persistence database on autosave, not on every message, so
the copy reflects the broker's state as of somewhere within the last
`autosave-interval` seconds (300 by default). The action says so in its log. For
a genuinely consistent copy, pause the broker first — which disconnects every
client:

```shell
juju run mosquitto/0 pause
juju run mosquitto/0 create-backup
juju run mosquitto/0 resume
```

### Copy it off the unit

A backup on the unit does not protect you from losing the unit:

```shell
juju scp mosquitto/0:/var/lib/mosquitto/backups/mosquitto-20260915T110402Z.tar.gz .
```

The tarball is mode `0600` and contains the password file and the private key, so
treat it as a secret.

### Schedule it

The charm has no scheduler. Run the action from whatever you already use —
`cron`, a systemd timer, your CI — against the controller:

```shell
juju run mosquitto/0 create-backup --format json > /var/log/mosquitto-backup.json
```

## Restore a backup

```shell
juju run mosquitto/0 restore-backup path=/var/lib/mosquitto/backups/mosquitto-20260915T110402Z.tar.gz
```

This stops the broker, extracts the tarball, and starts it again. **Every client
is disconnected**, and the action says so before it begins. It must run on the
leader, because it changes state the whole application shares.

The action always tries to start the broker again, whether or not the restore
itself worked, and fails if it could not: a restore that left the broker down is
reported as a failure rather than as `restored`, so it cannot look like a
recovery while every client is still disconnected.

A restored password file is the one from the backup, so users created since then
no longer exist, and passwords changed since then are back to their older values.
The charm's own record of users is unchanged, so the next reconciliation —
a config change, `force-reconfigure`, or the next `update-status` — writes the
current users back over the restored file. If your intent was to roll the users
back, remove the unwanted ones with `remove-user` as well.

To restore onto a fresh unit, copy the tarball up first:

```shell
juju scp mosquitto-20260915T110402Z.tar.gz mosquitto/0:/tmp/
juju run mosquitto/0 restore-backup path=/tmp/mosquitto-20260915T110402Z.tar.gz
```

The charm refuses any tarball containing a link, an absolute path outside the
broker's own directories, or a `..` that escapes them, so a restore cannot be
used to write arbitrary files as root. A tarball that was not produced by
`create-backup` will usually be refused for one of those reasons; the action
fails with the reason rather than putting the unit into an error state.

## What is not in the backup

- Juju secrets, which is where passwords actually live. The password file in the
  backup holds only hashes.
- The systemd drop-ins and the exporter service, which the charm rewrites.
- Anything you put on the unit by hand.

Rebuilding a broker from nothing is therefore: deploy the charm with the same
config, restore the backup, and let the charm reconcile.

## Related

- [Actions reference](../reference/actions.md)
- [File layout on the unit](../reference/file-layout.md)
