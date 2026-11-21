# Product Actions

Scheduled product reports (emails and Telegram posts for the product team), run as GitHub Actions
workflows in this public, sealed repository. See `CONTEXT.md` for vocabulary and `docs/adr/` for
decisions (ADR 0015 explains why these moved out of `Lascade-Co/actions`).

## Sealed output

This repo is public and its CI output is sealed. Rules, enforced by `.github/workflows/seal-policy.yml`:

- Every job starts with `Lascade-Co/actions/actions/seal@seal-v1` and ends with `Lascade-Co/actions/actions/seal-upload@seal-v1` (`if: always()`). Neither takes `with:`.
- Never use plain `shell: bash`; the default shell is `seal-bash {0}` or `seal-bash-e {0}`.
- Never expand private values into `run:` text, `env:` or a third-party `with:`; the public step header shows them.
- Pack artifacts with `seal-pack` and read them with `seal-unpack` (`REPO_AGE_KEY` from secrets); keep retention at 7 days or less.
- Mask private values with `::add-mask::` in an earlier sealed step; never mask public metadata.
- No secrets in `pull_request` workflows; no `pull_request_target`.
- Jobs with a `permissions:` block need `contents: read`.
- Full rules: https://github.com/Lascade-Co/actions/blob/main/docs/sealed-output.md
- Open runs at https://ci.lascade.com/?repo=<repo>

## Production environment

Every job that references `secrets.<NAME>` (other than `secrets.GITHUB_TOKEN`) declares
`environment: production`, or a name listed one per line in `.github/seal/environments`. The
`production` environment allows deployment from `main` only, so branch runs never see a secret.
A job that calls a local reusable workflow carries no `environment:`; the called jobs do.
Cross-repo reusable calls that pass secrets are listed in `.github/seal/env-exempt` as
`<workflow file>:<job id>  # reason`.

## Layout and imports

- Python code lives in `scripts/<report>/`, shared code in `scripts/common/`. Imports are flat
  (`import dates`, not a package path).
- `pytest.ini` sets `pythonpath` to `scripts/common`, `scripts/ai` and every `scripts/<report>`
  directory. Workflows set `PYTHONPATH` to the same directories they use.
- Module and test-file basenames are unique across the repo. On a collision, rename with the report's
  prefix (`ic_`, `cs_`).
- `scripts/ai/` is not committed. It is fetched from `Lascade-Co/actions` `main` by the
  `.github/actions/fetch-ai` composite in CI and by `scripts/fetch-ai.sh` locally. It supplies the
  shared Claude client (`claude_api.py`) and its `requirements.txt`; do not copy it here.
- Every dependency in `requirements.txt` is pinned with `==`.
- `test.yml` has one job, `test`, with no `paths:` filter and no secrets; `policy / policy` and `test`
  are the required checks on `main`.

## How the product team changes a report

1. Branch from `main` and change the report.
2. Open a pull request. A `@Lascade-Co/backend` code owner must approve (re-approval after any push).
3. Merge once `policy / policy` and `test` pass.
4. Run the report's workflow with `workflow_dispatch` and `dry_run=true`, then open the preview at
   https://ci.lascade.com/?repo=product-actions.
