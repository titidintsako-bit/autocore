# Contributing

AutoCore is early. Contributions are most useful when they make the product easier to trust, easier to run, or easier for non-specialists to understand.

## Good First Contributions

- improve first-run setup wording
- simplify confusing UI labels
- add task packs for common AI-coding workflows
- add release-gate checks
- improve public-mode sanitization
- add focused tests for trust and evidence behavior
- improve docs for self-hosted usage

## Product Principles

- Claims must match evidence.
- Public mode must stay read-only and sanitized.
- Local live mode must be clearly separated from public demo mode.
- Provider output is advisory, not authority.
- Do not add demo-only data to production surfaces unless it is clearly labeled and separated.
- Avoid vague AI marketing language.

## Development

Install dependencies:

```bash
npm install
```

Run private live mode:

```bash
npm run start:local
```

Run the backend tests:

```bash
npm run test:backend
```

Run the release gate:

```bash
npm run verify:release
```

## Pull Request Expectations

PRs should include:

- what changed
- why it changed
- how it was tested
- any claim or security boundary affected

For UI changes, include before/after screenshots when possible.

For runtime, policy, provider, or evidence changes, include tests.

## Security And Secrets

Never commit:

- `.env` files
- provider keys
- local run databases
- local evidence exports with private project paths
- generated build output

Use `.env.example` for placeholders.

## Tone

AutoCore is for evidence, not hype. Prefer plain language and direct behavior over broad claims.
