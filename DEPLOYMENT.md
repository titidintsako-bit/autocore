# AutoCore Deployment

AutoCore is open-source, self-hosted, and BYOK. The recommended public release is a read-only demo. Private live auditing is for local or trusted-network use.

## Public Read-Only Deployment

Use this for a public demo, portfolio link, or first open-source release:

```bash
npm ci
npm run verify:release
npm run build
npm run start:public
```

Public mode:

- serves the built UI from `dist/`
- exposes sanitized demo APIs
- blocks live POST mutations with `403`
- hides local project paths
- disables approvals and command execution

Docker:

```bash
docker build -t autocore .
docker run --rm -p 8787:8787 autocore
```

Docker Compose:

```bash
docker compose up --build
```

Open:

```text
http://127.0.0.1:8787
```

## Static Preview Deployment

Use this for static hosts such as Vercel:

```bash
npm ci
npm run export:demo
npm run build:public
```

The included `vercel.json` runs `npm run build:public` and serves `dist/`. This preview is read-only by design. It is for public sharing, product walkthroughs, and recorded videos; it does not run personal projects or provider calls.

## Release Integrity Gate

Run this before publishing a public build or release tag:

```bash
npm run verify:release
```

The gate must pass:

- backend unit and API tests
- private frontend build
- public static build
- repository secret scan
- public artifact scan for local paths, env references, and secret-like tokens
- Build Auditor no-mocked-data and claim-readiness check
- live guided-audit smoke test
- public read-only smoke test that proves mutations are blocked

If this command fails, the project is not release-ready. Fix the finding, rerun the gate, and only claim what the evidence supports.

## Private Live Mode

Use this when auditing your own local repos:

```bash
npm run start:local
```

Target a repo:

```bash
npm run start:local -- --project /path/to/repo
```

PowerShell:

```powershell
npm run start:local -- --project "C:\path\to\repo"
```

Open:

```text
http://127.0.0.1:5173/?section=setup
```

If those ports are busy, `start:local` resolves free ports and prints the actual Setup URL. The frontend also checks backend capabilities and tells you to restart AutoCore when it is connected to an older runtime.

Advanced split-terminal mode remains available with `npm run start:live` and `npm run dev`.

## Use With Codex

Run AutoCore beside the repo Codex is editing:

```bash
npm run start:local -- --project "C:\path\to\repo"
```

Open `Companion` after Codex changes code. The Companion surface lists changed files, risk markers, missing test evidence, a copyable follow-up prompt, and a one-click `Audit latest Codex changes` action.

Use `Check this project` from Setup or Companion when you want AutoCore to create the complete first workflow: Prompt Lab evaluation, Build Auditor scan, approval-gated run, and the next action to take.

Use `Choose repo folder` from Companion or `Choose folder` from Setup to switch workspaces without typing a path. If the native picker is unavailable, paste the path in Connect.

## Optional Contained Static Checks

Enable Docker-contained execution for eligible safe Python static checks:

```bash
npm run start:contained
```

Requirements:

- Docker installed
- Docker daemon running
- `AUTOCORE_ENABLE_DOCKER_CONTAINMENT=1`

AutoCore reports these states separately:

- disabled
- Docker executable missing
- Docker daemon unavailable
- Docker available

Contained execution is only claimed when a run actually records Docker-contained evidence. If Docker Desktop is installed but not running, AutoCore falls back to guarded policy and blocks the contained-execution claim.

## Trusted Project Scripts

Project scripts such as `npm run build`, `npm test`, and `pytest` run repository code. AutoCore blocks them by default.

Enable only for repos you trust:

```bash
AUTOCORE_TRUST_PROJECT_SCRIPTS=1 npm run start:live
```

PowerShell:

```powershell
$env:AUTOCORE_TRUST_PROJECT_SCRIPTS="1"
npm run start:live
```

## Networked Live Mode

Do not expose live mode directly to the internet. If you bind live mode to a network host, set a server-side API token and put AutoCore behind real authentication/TLS or a trusted private network.

```bash
AUTOCORE_MODE=live
AUTOCORE_HOST=0.0.0.0
AUTOCORE_API_TOKEN=replace-with-a-long-random-token
python -m autocore.server
```

Never put `AUTOCORE_API_TOKEN` in a Vite or browser environment variable.

## BYOK Providers

AutoCore runs offline by default. Optional providers are configured with local environment variables:

```bash
AUTOCORE_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.1

AUTOCORE_PROVIDER=groq
GROQ_API_KEY=...
GROQ_MODEL=llama-3.3-70b-versatile

AUTOCORE_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1-mini
```

Provider output is never authority. AutoCore still policy-checks proposed commands, requires approval, captures output, and writes evidence.
