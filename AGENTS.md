# Project Instructions

## Project overview
This is a Python savings-funds application built with Flet. It manages savings funds and account balances and supports synchronization with Nextcloud.

## Technology choices
- Keep Python as the primary language and Flet as the UI framework.
- Use `uv` for Python dependencies and commands.
- Preserve the existing Flet version and dependencies unless a change is necessary and justified.
- Do not migrate frameworks or rewrite the application without explicit approval.
- Avoid adding dependencies unless they provide clear value.

## Architecture
Inspect the actual repository before making changes. Preserve the existing separation of responsibilities, including:
- `app.py`: application initialization and high-level app behavior.
- `ui_components.py`: reusable UI components, dialogs, and presentation.
- `data.py`: local persistence and data-loading logic.
- `nextcloud.py`: Utilities related to Nextcloud data synchronization.
- `colors.py`: shared styling.

Treat these as initial guidance; the implementation in the repository is authoritative.

## Implementation
- Make focused, minimal changes.
- Reuse existing components and conventions.
- Preserve dark mode, responsive layouts, and existing behavior.
- Keep blocking network operations off the UI event loop.
- Handle errors clearly and avoid duplicate synchronization operations.
- Never hard-code credentials or expose secrets in logs.
- Never overwrite real user data during tests.
- Do not discard unrelated user changes.

## Verification
- Inspect existing tests and project configuration before choosing a test strategy.
- Use `uv run` for Python commands.
- Run relevant tests and checks after implementation.
- Do not claim a test passed unless you actually ran it.
- Review the final diff for accidental changes, regressions, and exposed secrets.

## Workflow
1. Understand the requested behavior.
2. Inspect the relevant code and identify affected files.
3. Explain significant design choices before broad refactoring.
4. Implement the smallest complete solution.
5. Run appropriate tests and checks.
6. Review the diff.
7. Report changed files, behavior, test results, and remaining risks.

Ask before destructive operations, major architectural changes, or changes that could overwrite important data.
