# Roadmap

AutoCore is public as `v0.1.0-alpha`. The next work is about usefulness, clarity, and credibility.

## Priority 1: Beginner-Readable Workflow

The UI needs a clearer path for people who use AI coding tools but do not live inside software engineering terminology.

Current alpha:

- `Start Here` opens with a Beginner Mode verdict
- results translate into `Safe to share`, `Needs work`, or `Do not publish yet`
- the UI explains what the verdict means, why AutoCore thinks it, and the next action
- `Fix with Codex` creates a copyable repair prompt for agent users
- Lab, Policy, Connect, and raw Evidence now sit behind Advanced navigation

Planned changes:

- ask three plain questions: what repo, what are you trying to prove, what risk worries you
- show one primary action at a time across the whole flow
- add shorter evidence summaries for people who do not read logs
- keep reducing jargon in tabs and panels

## Priority 2: Real Personal Use

AutoCore should help someone check their own AI-built repo in under five minutes.

Planned changes:

- project picker improvements
- clearer Codex Companion mode
- copyable follow-up prompts for fixing findings
- better evidence report summaries
- easier local install path for Windows users
- less jargon in tabs and panels

## Priority 3: Stronger Evidence

The product should become more valuable as it collects stronger proof.

Planned changes:

- deeper dependency and package checks
- optional static analysis integrations
- richer browser smoke artifacts
- test coverage discovery
- repeat-run comparison
- evidence export suitable for GitHub issues or PRs

## Priority 4: Safer Execution

AutoCore should keep reducing the trust required to run checks.

Planned changes:

- broader contained execution support
- clearer policy explanations
- better blocked-command remediation
- safer defaults for project scripts
- release-gate expansion for public launches

## Priority 5: Community And Commercial Signals

Commercial hosting should wait until self-hosted users prove the workflow matters.

Signals to watch:

- people successfully run it on their own repos
- users ask for saved team reports
- users ask for hosted collaboration
- repeated requests for integrations
- repeated confusion around the same UI step

Until then, AutoCore should stay open-source, self-hosted, BYOK, and evidence-first.
