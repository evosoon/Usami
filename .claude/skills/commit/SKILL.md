---
name: commit
description: Automated git commit flow — status check, test, add, commit, push (project)
allowed-tools: Bash, Read, Grep
---

# Git Commit Flow

Execute the following steps to complete a code commit:

## 1. Check Git Status
- Run `git status` to see changed files
- Run `git diff --stat` to see change summary
- Run `git log --oneline -3` to match recent commit style

## 2. Run Tests
Run tests before committing to ensure code quality. Determine which tests to run based on changed files:

### Backend (if `backend/` files changed)
- Run: `cd backend && uv run python -m pytest tests/ -v --tb=short`
- **Never** use bare `python` or `python3` — system Python lacks project deps
- If tests fail, stop the commit and report errors

### Frontend (if `frontend/` files changed)
- Run: `cd frontend && pnpm test`
- This executes Vitest unit tests (stores, hooks, utilities)
- If tests fail, stop the commit and report errors

### Both
- If changes span both `backend/` and `frontend/`, run both test suites
- Run backend and frontend tests in parallel when possible

### Lint
- Backend: `cd backend && uv run ruff check .`
- Frontend: `cd frontend && pnpm lint`

> **Note**: E2E tests (`pnpm test:e2e`) are not part of the commit flow — they require a running dev server and are run separately.

## 3. Stage Files
Use `git add` to stage relevant files, excluding:
- `outputs/`, `__pycache__/`, `.env`, `*.log`, `node_modules/`
- `playwright-report/`, `test-results/`, `.next/`
- Never commit sensitive data (API keys, credentials, etc.)

## 4. Generate Commit Message
Generate a conventional commit message based on the changes:
- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation update
- `refactor:` code refactoring
- `test:` test changes
- `chore:` maintenance

Commit message format:
```
<type>: <short description>

<detailed explanation (if multiple changes)>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

## 5. Commit and Push
- Run `git commit -m "<message>"`
- Run `git push origin <current-branch>`

## 6. Output
- Show commit hash
- Show push status
- Show test results summary (passed/failed counts)

## Arguments
If the user provides `$ARGUMENTS`, use them as reference for the commit message description.

Examples:
- `/commit` — auto-analyze changes and generate message
- `/commit add user authentication` — use the provided description
