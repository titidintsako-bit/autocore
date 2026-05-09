# Security Policy

AutoCore is an open-source alpha for local-first evidence gathering around AI-assisted software work.

## Supported Scope

The current supported version is `v0.1.0-alpha`.

Security reports should focus on:

- secret exposure in public builds or demo snapshots
- unsafe command execution paths
- public-mode mutations that should be blocked
- local path leakage in public responses
- misleading security claims in docs or UI
- failures in the release integrity gate

AutoCore does not currently claim full security coverage, full isolation for all commands, or hosted-production readiness.

## Reporting

Please open a private security advisory on GitHub if available. If that is not available, open a minimal issue that describes the affected area without posting secrets, tokens, private paths, exploit payloads, or sensitive repository data.

Include:

- affected version or commit
- operating system
- exact command or UI flow
- expected behavior
- observed behavior
- whether public mode or live mode is affected

Do not include real provider keys, local `.env` contents, private repository files, or personally identifying data.

## Current Safety Boundaries

AutoCore has these boundaries today:

- public mode is read-only
- live mode is intended for local or trusted-network use
- provider keys are configured locally and should not enter browser bundles
- command execution requires guarded policy checks and operator approval
- project scripts are treated as trusted project code only when explicitly enabled
- Docker-contained execution is claimed only when Docker evidence is recorded
- release checks include backend tests, builds, secret scan, public artifact scan, guided audit smoke, and public read-only smoke

## Non-Goals In This Release

The alpha does not provide:

- a hosted multi-tenant service
- full vulnerability scanning
- malware analysis
- full OS isolation for every command
- guarantees that a project is secure
- automated deployment authority

## Maintainer Checklist

Before public releases:

```bash
npm run verify:release
```

If the gate fails, do not publish the release until the finding is fixed or the claim is reduced.
