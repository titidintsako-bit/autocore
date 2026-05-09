# AutoCore

AutoCore is an open-source, self-hosted, BYOK evidence console for AI-assisted software work. It helps you check what an AI built, detect unsupported claims, run guarded local checks, and produce a report before you trust or publish a project.

AutoCore is local-first and offline by default. Provider keys stay on your machine. Model output is treated as a proposal, not authority.

Public alpha:

- Demo: https://autocore-tau.vercel.app
- Source: https://github.com/titidintsako-bit/autocore
- Release state: `v0.1.0-alpha`

## Plain-English Workflow

AutoCore answers one practical question: is this AI-assisted project ready to trust, share, or keep fixing?

1. Pick the project folder.
2. Click `Check this project`.
3. Review the verdict.
4. Approve the guarded local check only if you trust the repo.
5. Open Evidence and use the report to decide what to fix next.

If you are not a software engineer, start with `Start Here` and Companion. Treat Lab, Policy, and raw Evidence as advanced views.

## What It Is

- A local evidence console for AI-built or AI-assisted projects.
- A one-click guided audit that creates a Prompt Lab score, Build Auditor scan, and approval-gated run.
- A prompt preflight lab for estimating readiness and token demand.
- A build auditor for mocked-data checks, quality signals, security evidence, and claim readiness.
- A guarded policy layer for approving and recording local checks.
- An optional Docker-contained path for eligible safe static Python checks when Docker is enabled and the daemon is reachable.
- A public read-only demo mode for portfolio or release previews.

## What It Is Not

- Not a hosted service yet.
- Not a full security scanner.
- Not a guarantee that a project is secure.
- Not a full OS isolation system for all commands.
- Not an autonomous deploy bot.

AutoCore can support claims only when evidence exists. The UI marks unsupported claims as limited or blocked.

## Fast Start

Install dependencies:

```bash
npm install
```

Start private live mode:

```bash
npm run start:local
```

Open:

```text
http://127.0.0.1:5173/?section=setup
```

That one command starts the local API, starts the web app, opens the Setup tab, and keeps both processes tied to one terminal.

If the default ports are already in use, the launcher picks free ports and prints the exact URL. If an older AutoCore backend is still running, the UI also shows a restart warning instead of failing silently.

In `Start Here`, click `Choose folder` to pick the repo you want AutoCore to audit. If the native picker is unavailable, use `Paste path` on Connect. Then click `Check this project` to create a Prompt Lab score, Build Auditor scan, and approval-gated run from one local workflow. The Beginner Mode panel translates the result into `Safe to share`, `Needs work`, or `Do not publish yet`, explains why, and gives you a `Fix with Codex` prompt when more work is needed.

When you are using Codex, open the Companion tab after each meaningful code change. It shows changed files, high-risk markers, missing test evidence, a copyable next Codex prompt, `Check this project`, and a focused audit for the latest Codex changes.

Start public read-only mode:

```bash
npm run build
npm run start:public
```

Open:

```text
http://127.0.0.1:8787
```

Build a static public preview:

```bash
npm run export:demo
npm run build:public
```

This build loads `public/demo-snapshot.json` and opens in read-only snapshot mode without requiring the Python API.

Run the daily development checks:

```bash
npm run verify
```

Run the full release integrity gate before publishing:

```bash
npm run verify:release
```

The release gate runs backend tests, private and public frontend builds, a secret scan, a public-artifact safety scan, a no-mocked-data Build Auditor check, a guided-audit smoke test, and a public read-only mutation-blocking smoke test.

## Modes

### Codex Companion Mode

Use this while Codex is editing a repo:

```bash
npm run start:local -- --project "C:\path\to\repo"
```

Open `Companion` to review changed files. Use `Check this project` when you want the full guided path: prompt preflight, build audit, run creation, and the next approval step. Use `Audit latest Codex changes` when you only need to refresh the Build Auditor evidence for changed files. AutoCore keeps quality/security claims limited to what the checks actually support.

Use `Choose repo folder` inside Companion when you switch Codex to a different workspace.

### Public Mode

Use public mode for an internet-facing open-source demo. It serves the built frontend and sanitized read-only APIs from one Python process.

```bash
npm run build
npm run start:public
```

Public mode:

- blocks POST mutations
- hides local project paths
- disables approvals and command execution
- serves deterministic demo evidence

### Private Live Mode

Use live mode for personal auditing on your own machine.

```bash
npm run start:local
```

Target a repo:

```bash
npm run start:local -- --project /path/to/repo
```

On Windows PowerShell:

```powershell
npm run start:local -- --project "C:\path\to\repo"
```

Advanced split-terminal mode is still available with `npm run start:live` and `npm run dev`.

### Contained Static Checks

AutoCore can route eligible safe Python static checks through Docker when you explicitly enable it:

```bash
npm run start:contained
```

This only becomes active when Docker is installed and the Docker daemon is reachable. AutoCore reports Docker missing or daemon-unavailable states honestly and falls back to guarded local policy.

Contained execution currently supports:

- `python -m compileall`
- `python -m py_compile`

Project scripts such as `npm run build`, `npm test`, and `pytest` execute project code and are not treated as contained.

## BYOK Providers

AutoCore works offline:

```bash
AUTOCORE_PROVIDER=offline
```

Optional local provider configuration:

```bash
AUTOCORE_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.1

AUTOCORE_PROVIDER=groq
GROQ_API_KEY=your-local-key
GROQ_MODEL=llama-3.3-70b-versatile

AUTOCORE_PROVIDER=openai
OPENAI_API_KEY=your-local-key
OPENAI_MODEL=gpt-4.1-mini
```

Do not put provider keys in frontend environment variables. Browser bundles are public.

## Current Capabilities

- React/Vite cockpit UI.
- Python stdlib runtime API.
- SQLite local run history under `.autocore/`.
- Guided Audit API for creating the first useful run without hopping across tabs.
- Runtime version/capability handshake so stale local backends are detected.
- Prompt Lab with redacted prompt previews and token forecasts.
- Build Auditor with no-mocked-data checks, static security evidence, deployment signals, and claim readiness.
- Release integrity gate for tests, builds, secret checks, public-safety checks, and guided-audit/public-mode smoke tests.
- Guarded command policy with approval, `shell=False`, timeouts, stdout/stderr capture, and re-checks before execution.
- Optional Docker-contained execution for eligible static checks.
- Markdown and JSON evidence reports under `.autocore/evidence/`.
- Public-safe demo snapshot with sanitized paths and no live mutations.

## Guarded Policy

AutoCore checks proposed commands before planning and again before execution.

Default guarded policy:

- profile: `guarded.local`
- filesystem: workspace scoped
- network-capable programs: denied
- secret-looking paths: denied
- shell programs and shell metacharacters: denied
- command prefixes: allowlisted

This is not the same as contained execution. AutoCore only marks contained execution as supported when a run actually used the Docker-contained runner.

## Docker Deployment

```bash
docker build -t autocore .
docker run --rm -p 8787:8787 autocore
```

Or:

```bash
docker compose up --build
```

The Docker image runs public read-only mode by default.

## API Pointers

- `GET /api/health`
- `GET /api/demo`
- `GET /api/project`
- `GET /api/policy`
- `GET /api/task-packs`
- `POST /api/prompt-lab/evaluate`
- `GET /api/prompt-lab`
- `POST /api/guided-audit`
- `POST /api/build-audits`
- `GET /api/build-audits`
- `POST /api/runs`
- `GET /api/runs`

Public mode returns sanitized read-only responses and blocks mutations.

## Release Status

AutoCore is public as `v0.1.0-alpha`.

Public links:

- GitHub: https://github.com/titidintsako-bit/autocore
- Demo: https://autocore-tau.vercel.app

Release checklist:

- `npm run verify:release`
- public mode stays read-only
- no secrets in docs or build output
- no local paths in public demo responses
- Build Auditor reports no product mocked-data findings
- contained execution claims remain blocked unless Docker evidence exists

Commercial hosting should wait until real users validate the self-hosted workflow.

## Project Governance

- Security policy: [SECURITY.md](SECURITY.md)
- Contributing guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Roadmap: [ROADMAP.md](ROADMAP.md)
