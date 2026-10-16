# Contributing to GAWorld

Thank you for helping build GAWorld. Contributions include code, tests, documentation, reproducible bug reports and research questions.

## Start from the current baseline

Create a feature branch from current `main`. Submit the feature for review against `Dev`; maintainers promote verified integrations to `main`. The production dashboard tracks `main`, while the Dev test environment uses a separate worktree. Cross-branch review and merging are not fully automated.

```bash
git clone https://github.com/wuchaozju/GAWorld.git
cd GAWorld
python -m pip install -e ".[dev]"
git switch -c feat/your-change
```

Read [AGENTS.md](AGENTS.md) for repository conventions. New Python implementation belongs under `gaworld/`; new simulation subsystems use the plugin architecture rather than adding inline logic to the main loop.

## Before review

- Explain the problem and resulting behavior.
- Add meaningful tests for new behavior; mock model calls and keep real API credentials out of tests.
- Run `python -m pytest --suite core` and relevant tests for your change.
- Check `git diff --check`; run formatting and lint on changed code.
- Keep generated runs, personal configuration, participant records and credentials out of commits.
- Call out changes to model semantics, data contracts, account isolation or resident ID mappings.

Changes to default simulation behavior may require a comparability epoch; see the rule in [AGENTS.md](AGENTS.md). Existing experiments must remain interpretable under their original versions.

## Contributors

The project homepage displays accounts from the public [GitHub contribution history](https://github.com/wuchaozju/GAWorld/graphs/contributors). It does not assign individual research or management roles from commit counts.

Report a reproducible issue at [GitHub Issues](https://github.com/wuchaozju/GAWorld/issues), with version, environment, steps and the expected result. Remove credentials and personal records from any attached logs.
