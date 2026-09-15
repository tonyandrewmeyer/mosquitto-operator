# Security policy

## Supported versions

Security fixes are released for the most recent revision published to the
`latest/stable` channel of the
[Mosquitto charm on Charmhub](https://charmhub.io/mosquitto), and for the
`main` branch of this repository. Older revisions are not supported; please
refresh to the latest revision before reporting.

## Mosquitto itself, and what `install-source: archive` gives you

This is important enough to state plainly.

The charm's default, `install-source: archive`, installs Mosquitto **2.0.18**
from the Ubuntu 24.04 `universe` pocket. Packages in `universe` carry **no
standard Ubuntu security support**: no Ubuntu Security Notices are issued for
them, and no patched builds reach the ordinary archive. The charm cannot change
that; it is a property of the package it installs.

If you need patched Mosquitto builds, you have two options:

- **Ubuntu Pro.** The ESM Apps stream does carry a patched build
  (`2.0.18-1ubuntu0.1~esm1`). Attach Ubuntu Pro to the machines the charm runs
  on, with the `esm-apps` service enabled, and keep `install-source: archive`.
  See [Ubuntu Pro](https://ubuntu.com/pro) and
  [ESM](https://ubuntu.com/security/esm).
- **`install-source: ppa`.** This installs from
  `ppa:mosquitto-dev/mosquitto-ppa`, which tracks upstream 2.1.x. You are then
  trusting the upstream Eclipse Mosquitto maintainers for security updates
  rather than Ubuntu, and you should watch
  [upstream releases](https://github.com/eclipse-mosquitto/mosquitto/releases)
  yourself.

Neither option is the default, because switching defaults would either require
a Pro subscription or move users off the Ubuntu archive without asking. Choose
deliberately for any deployment that is exposed beyond a trusted network.

## What qualifies as a security issue

Issues in *this charm* that could lead to unprivileged or unauthorised access
to the Mosquitto broker, to its configuration or TLS material, or to the
machine it runs on. For example:

- leakage of credentials, certificates or private keys through logs, Juju
  application data, relation data, or the charm's own state;
- default configuration that exposes the broker without authentication;
- command or template injection reachable from charm configuration, actions or
  relation data;
- dependencies vendored into the charm with known vulnerabilities.

Vulnerabilities in the Mosquitto broker itself belong with
[Eclipse Mosquitto](https://github.com/eclipse-mosquitto/mosquitto/security/policy),
and vulnerabilities in Juju, `ops` or Charmhub with
[security@ubuntu.com](mailto:security@ubuntu.com) (see the
[Ubuntu Security disclosure and embargo policy](https://ubuntu.com/security/disclosure-policy)).

## Reporting a vulnerability

Please **do not open a public GitHub issue** for a security problem.

Report it privately through
[GitHub's private vulnerability reporting](https://github.com/tonyandrewmeyer/mosquitto-operator/security/advisories/new).
See
[Privately reporting a security vulnerability](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
for what that looks like from your side.

Please include:

- a description of the issue and its impact;
- the charm revision and channel, and the Juju version and cloud;
- the steps you took to reproduce it;
- any known mitigations or workarounds.

## What to expect

This is a personal, volunteer-maintained project, so there is no commercial
SLA, but I aim to:

- acknowledge your report within 5 working days;
- agree an assessment and a fix plan with you within 14 days;
- release a fix, and request a CVE where one is warranted, within 90 days.

I will work with you on disclosure timing — if you have a deadline for public
disclosure, please say so in your report. I am happy to credit you in the
resulting advisory unless you would rather not be named.
