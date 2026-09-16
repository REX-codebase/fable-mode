# Contributing to Fable Mode

Issues and pull requests are welcome. This project is MIT licensed and
dependency-free at runtime; please keep it that way.

## Development setup

```bash
git clone https://github.com/REX-codebase/fable-mode.git
cd fable-mode
python -m venv .venv && source .venv/bin/activate
pip install -e . pytest
```

## Running the tests

```bash
python -m pytest -q
```

For a dependency-free smoke run, use:

```bash
python -m unittest discover -q
```

The full test suite should stay green on Linux, macOS, and Windows (see
`.github/workflows/test.yml`). A change that breaks a test is not ready, and a
new behavior without a test is not done.

## What makes a good contribution

- **Small, explained diffs.** Say what changes and why, in the PR body.
- **Evidence, not vibes.** Fable Mode is about verifiable claims; include
  test output, a receipt, or a repro for behavior changes.
- **Adversarial mindset.** If you touch the proof engine, time-lock, or
  red-team logic, describe how the change could be gamed and why it cannot.
- **No new runtime dependencies** without a discussion issue first.

## Good first issues

Look for issues labeled `good first issue`. Documentation fixes, new test
cases for the verifier modules, and MCP client setup notes for other editors
are all great first contributions.

## Reporting security issues

Please open a private security advisory (Security tab) instead of a public
issue for anything that weakens the time-lock, proof validation, or red-team
guarantees.
