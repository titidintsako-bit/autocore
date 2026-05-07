# AutoCore Portfolio Case Study

## Positioning

AutoCore is an open-source, self-hosted, BYOK evidence console for AI-assisted software work. It is built around a simple product belief: if AI helps build software, users need proof of what was inspected, what was run, what was blocked, and what can honestly be claimed.

This is not a chatbot. It is an operator console for trust, evidence, and guarded local execution.

## Problem

Most AI coding demos show a finished result. They rarely show whether the result is wired to real data, whether risky commands were blocked, whether evidence was captured, or whether the user can safely claim the project is tested, deployable, or secure.

AutoCore turns that gap into product infrastructure.

## What It Proves

- A local runtime can inspect a workspace and classify the project stack.
- Guided Audit can turn one selected project into a Prompt Lab evaluation, Build Auditor scan, and approval-gated run.
- Prompt Lab can score a task prompt before a run.
- Build Auditor can flag mocked-data patterns and unsupported claims.
- Model or heuristic proposals can be filtered by a guarded policy before execution.
- Terminal commands can require approval and run with `shell=False`, timeout, stdout/stderr capture, and policy metadata.
- Eligible static Python checks can use Docker-contained execution when Docker is enabled and reachable.
- Every run can produce a scorecard, replay trace, run history entry, and evidence bundle.
- A public demo can show the product without exposing local paths, provider keys, or live mutation controls.

## Current Demo Path

Public read-only demo:

```bash
npm run build
npm run start:public
```

Private live mode:

```bash
npm run start:live
npm run dev
```

Portfolio-safe UI:

```text
http://127.0.0.1:8787
```

## Architecture

- React/Vite evidence console.
- Python stdlib HTTP API.
- SQLite local run store.
- Guided Audit orchestration endpoint for first-run usability.
- Prompt Lab for readiness and token forecasts.
- Build Auditor for claim readiness and static security evidence.
- Built-in task packs for coding, research, data, and browser workflows.
- BYOK planner adapters with offline heuristic fallback.
- Guarded policy profile with workspace scope, network-program denial, secret-path denial, shell denial, and command allowlists.
- Optional Docker-contained runner for eligible safe static checks.
- Markdown/json evidence generation for completed runs.
- Public-safe deterministic demo snapshot.

## Moat

The moat is not a prettier dashboard. It is the evidence schema, guarded policy layer, task-pack library, run history, claim-readiness model, and public-safe proof surface. Each real workflow adds reusable eval definitions, safety checks, replay artifacts, and credibility data that a generic prompt wrapper does not have.

## Honest Claims

AutoCore can currently claim:

- local-first
- open-source
- self-hosted
- BYOK
- offline by default
- evidence-backed static checks
- public read-only demo mode
- guarded local policy
- optional Docker-contained static checks when Docker evidence exists

AutoCore should not yet claim:

- full security coverage
- complete isolation for all commands
- hosted commercial readiness
- autonomous deployment

## Next Steps

- Add richer browser replay artifacts.
- Add more task packs around coding, data, browser, and research workflows.
- Improve Docker-contained execution coverage without expanding trust claims too quickly.
- Watch real self-hosted usage before deciding whether to build a commercial hosted product.
