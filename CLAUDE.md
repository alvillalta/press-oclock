# CLAUDE.md

Style guide for working in this repository. These are defaults: an explicit instruction from the user always wins.

## Workflow

- Read the relevant code before changing it. Follow the patterns already used in the file and its neighbours.
- Keep changes small and scoped to what was asked. Do not refactor, rename, or reformat unrelated code.
- When a request is ambiguous in a way that changes what gets built, ask before writing code.
- Fix root causes. Do not silence an error, skip a check, or special-case a symptom to make it pass.
- Prefer editing existing files over creating new ones. Do not create documentation files unless asked.

## Code style

- Use descriptive names. Avoid abbreviations that are not already common in the codebase.
- Keep functions short and focused on one job. Prefer early returns over deep nesting.
- Do not leave dead code, commented-out code, debug prints, or unused imports behind.
- Comment the why, not the what. Do not add comments that restate the code.
- Reuse existing helpers and utilities before writing new ones. Do not duplicate logic.
- Do not add abstractions, options, or configuration for needs that do not exist yet.

## Types and errors

- Type everything. Do not use `any`, `# type: ignore`, or casts to get past the type checker without a comment explaining why.
- Validate input at system boundaries (API requests, external services, files). Trust internal code.
- Handle errors explicitly. Never swallow an exception silently or catch a broader type than needed.

## Security

- Never read, print, log, or commit secrets, tokens, or the contents of `.env` files.
- Never hardcode credentials or environment-specific values. Use configuration.
- Do not weaken authentication, authorization, or validation to make something work.

## Dependencies and generated code

- Do not add, remove, or upgrade dependencies unless asked. Use the project's package managers (`uv` for Python, `bun` for JavaScript).
- Do not edit lockfiles or generated code by hand (`uv.lock`, `bun.lock`, `frontend/src/client/`, `frontend/src/routeTree.gen.ts`). Regenerate them with the tool that owns them.

## Git

- Do not commit or push unless asked. Never commit directly to `main`.
- Write small commits with a short imperative subject line that says what changed and why.
- Never use `--no-verify`, force push, `git reset --hard`, or any command that discards work without explicit approval.

## Verification

- Before reporting work as done, run the linter and type checker for the code you touched and fix what they report.
- Never claim something works without having checked it. If a check was skipped or failed, say so.

```bash
# Backend: lint, format, types
uv run --project backend ruff check backend/app
uv run --project backend ruff format --check backend/app
uv run --project backend mypy backend/app
uv run --project backend ty check backend/app

# Frontend: lint/format, then types and production build
bun run lint
bun run --filter frontend build
```
