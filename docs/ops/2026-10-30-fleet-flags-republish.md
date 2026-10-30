# 2026-10-30 Fleet Flags republish receipt

Status: **blocked**. Dispatch was not accepted. No production build started. The public site was not republished.

This receipt records an operations attempt only. It does not change dashboard code, workflows, data, or `main`.

## Preflight

| Check | Result |
| --- | --- |
| `origin/main` | `2c6374e636175ff65bcf4f83c7614b05c50dd1cc` |
| Required floor | `2c6374e636175ff65bcf4f83c7614b05c50dd1cc` (`Gate Fleet Flags on current funding and mark status (#267)`) |
| `main` moved | No. `main` was exactly the required commit. |
| Existing `workflow_dispatch` of `.github/workflows/deploy-pages.yml` on that SHA | None |
| In-progress `deploy-pages.yml` run | None |
| Workflow | `Deploy Market Watch Dashboard`, id `353459114`, state `active` |
| Dispatch contract | `workflow_dispatch` inputs `launch_id`, `review_id`, `packet_sha256`, each optional, default `""`. Empty `launch_id` is the manual refresh path. |

Public site before the attempt, `https://mccabeai.github.io/market-watch-public-dashboard/release.json` (`last-modified: Fri, 30 Oct 2026 13:03:02 GMT`):

- `session_date`: `2026-10-30`
- `phase`: `final`
- `trigger`: `launch`
- `launch_id`: `mwl-20261030T103305Z-bba58959`
- `review_id`: `review-001`
- `packet_sha256`: `64e6de4144a04c2553f44d13b96066401021c5f5212a9071eb72d5f50547bd24`
- `overnight_run_id`: `overnight-20261030`
- `trader_cycle.status`: `accepted`
- `source_commit`: `6e62e4d90aa245f9771435e4bc4996543c0ca902`
- `site_sha256`: `5494e27a300958a04e7c0adb27256713b4f5b3e0e4773eb1078c90e070461aa6`

Public `trader-book.js` at the same last-modified time contains `bookFlagCount` and does not contain `isFundingActive`. On `main`, `patch_v13/trader-book.js` defines `isFundingActive` and `bookFlagCount` counts a flag when `isFundingActive(row)` is true. That code is not what the public site is serving.

## Dispatch

- Time (UTC): `2026-10-30T22:50:18Z`
- Command: `gh workflow run deploy-pages.yml --ref main --json`
- Inputs JSON: `{"launch_id":"","review_id":"","packet_sha256":""}`
- Authenticated `gh` account already present: `cursor` (GitHub App installation token). No other `GH_TOKEN` or `GITHUB_TOKEN` was set. Authentication was not changed.
- Acknowledgement: **rejected**. Exit code 1.
- Response: `could not create workflow dispatch event: HTTP 403: Resource not accessible by integration (https://api.github.com/repos/McCabeAI/market-watch-public-dashboard/actions/workflows/353459114/dispatches)`
- Actions run ID: none. GitHub did not create a run.
- Publication guard: not reached.

Reading the workflow metadata succeeded with the same credential. Creating the `workflow_dispatch` event did not. The same integration also receives HTTP 403 for `GET /user` and `GET /repos/McCabeAI/market-watch-public-dashboard/actions/permissions`.

## After the rejected dispatch

- Newest `deploy-pages.yml` run remains pull_request run `41136033586` (`2026-10-30T22:07:59Z`), not a `workflow_dispatch` on `main`.
- `origin/main` remains `2c6374e636175ff65bcf4f83c7614b05c50dd1cc`.
- Public `release.json` is unchanged: `source_commit` `6e62e4d90aa245f9771435e4bc4996543c0ca902`, October 30 final, trader cycle `overnight-20261030` `accepted`.
- Public `trader-book.js` still has zero occurrences of `isFundingActive`.

## Outcome split

| Gate | Result |
| --- | --- |
| Dispatch accepted | No |
| Production build completed | No. It did not start. |
| Public site verified on merged `isFundingActive` bookFlagCount logic | No |
| Public site still the 2026-10-30 final accepted books | Yes. Unchanged from the preflight read. |

No second dispatch was sent. No workflow, code, data, book, or credential change was made. No pull request was opened.
