# GitHub Codex Automation

This repository includes optional GitHub Actions workflows that let maintainers
ask Codex to help with issues.

The automation is intentionally conservative:

- Public issues from unknown users are labeled for human review first.
- Codex triage runs automatically only for trusted maintainer triggers.
- External reports can be triaged by adding the `codex-triage` label.
- The triage workflow creates its helper labels the first time it runs.
- Code changes require a maintainer to comment `/codex fix` or run the workflow
  manually.
- Pull requests opened by Codex are drafts.

## Required Setup

Add an Actions secret named `OPENAI_API_KEY`:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

Optional repository variable:

```text
CODEX_MODEL=gpt-5.5
```

If `CODEX_MODEL` is not set, the workflows use `gpt-5.5`.

## Issue Triage

Workflow: `.github/workflows/codex-issue-triage.yml`

Triggers:

- A maintainer opens or reopens an issue.
- A maintainer adds the `codex-triage` label to an issue.

Codex runs with a read-only sandbox and posts a triage comment with:

- Summary
- Likely area
- Reproduction or missing information
- Suggested next step

For public issues opened by people without write access, the workflow adds
`needs-maintainer-triage` and does not send the issue body to Codex until a
maintainer explicitly labels it.

## Draft PRs From Issues

Workflow: `.github/workflows/codex-issue-fix.yml`

Trigger from an issue comment:

```text
/codex fix
```

Only repository maintainers can trigger this. The workflow checks out the repo,
installs the Python package with test dependencies, asks Codex to implement the
issue, runs:

```bash
python -m pytest -p no:cacheprovider
```

If files changed and tests passed, the workflow opens a draft pull request on a
branch named:

```text
codex/issue-<issue-number>
```

You can also run the workflow manually from the Actions tab and provide an issue
number plus optional maintainer instructions.

## Safety Notes

Do not remove the maintainer gates on a public repository unless you are
comfortable with untrusted issue text triggering OpenAI API usage.

The triage workflow uses `sandbox: read-only`. The implementation workflow uses
`sandbox: workspace-write`, but only after a maintainer trigger, and it creates a
draft PR for review rather than pushing directly to `main`.
