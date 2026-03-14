---
name: commit
description: Automated git commit flow — status check, test, add, commit, push
allowed-tools: Bash, Read, Grep
---

# Git Commit Flow

Execute the following steps to complete a code commit:

## 1. Check Git Status
- Run `git status` to see changed files
- Run `git diff --stat` to see change summary
- Run `git log --oneline -3` to match recent commit style

## 2. Run Tests
Run tests before committing to ensure code quality:
- This project uses `uv` for dependency management. Always run via: `uv run python -m pytest backend/tests/ -v --tb=short`
- **Never** use bare `python` or `python3` — system Python lacks project deps
- If tests fail, stop the commit and report errors

## 3. Stage Files
Use `git add` to stage relevant files, excluding:
- `outputs/`, `__pycache__/`, `.env`, `*.log`, `node_modules/`
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

## Arguments
If the user provides `$ARGUMENTS`, use them as reference for the commit message description.

Examples:
- `/commit` — auto-analyze changes and generate message
- `/commit add user authentication` — use the provided description
