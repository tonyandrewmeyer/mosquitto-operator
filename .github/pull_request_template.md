## What does this change?

<!-- A short description of the change. -->

## Why?

<!-- The problem being solved. Link the issue: "Fixes #123" / "Part of #123". -->

Fixes #

## How was it tested?

<!--
Which tox environments did you run, and on what? For anything touching charm
behaviour, say which cloud and Juju version you tested against, for example
"tox -e unit; integration on LXD, Juju 3.6.10, ubuntu@24.04".
-->

## Checklist

- [ ] The commit messages follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).
- [ ] `tox` passes locally (`format`, `lint`, `static`, `unit`).
- [ ] I have added or updated unit tests covering this change.
- [ ] I have added or updated functional or integration tests, or explained why they are not needed.
- [ ] I have added or updated any relevant documentation (README, `charmcraft.yaml` descriptions, config option docs).
- [ ] I have added a `CHANGELOG.md` entry under `## [Unreleased]`, or this change is not user-visible.
- [ ] I have cleaned up any remaining cloud resources from my test runs.
- [ ] `charmcraft pack` still succeeds.

## Breaking changes

<!--
Does this change config option names, action names, relation interfaces, or
stored state in a way that will break existing deployments on upgrade? If so,
describe the upgrade path. If not, write "None".
-->

None

## Anything else reviewers should know?

<!-- Trade-offs you made, things you are unsure about, follow-up work. -->
