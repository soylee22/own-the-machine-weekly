# Own the Machine Weekly

Live site: https://soylee22.github.io/own-the-machine-weekly/
Repository: https://github.com/soylee22/own-the-machine-weekly

Delivered on 21 September 2026. The first issue covers the week ending 20 September.

## What runs

The Sunday workflow fetches public market history and news feeds, selects operational headlines, preserves the edition, builds the magazine and deploys GitHub Pages.
The schedule is Sunday at 19:37 Europe/London. GitHub may start it later.
The application requires no external API keys and makes no AI calls.
GitHub supplies its own token for archive commits and deployment.

The initial coverage contains seventeen verified instruments. The configuration holds instrument identifiers only.
Edit `config/holdings.yaml` when the portfolio changes. The application does not synchronise the brokerage account automatically.

## Reading

The site includes a weekly edition, READ and DATA views, seventeen distinct machine dossiers, a rotating machine feature, thesis challenges, an archive and source receipts.
The six return periods are 1D, 1W, 1M, YTD, 1Y and 5Y.
The data view also exposes relative strength, portfolio momentum, Stage 2 conditions, K-ratio and distance from the annual high.
Light and dark themes support phone, tablet and desktop reading.

## Verification

- `python3 -m pytest tests -q`: 27 tests passed.
- `python3 -m compileall -q app run.py`: passed.
- `cd site && npm ci && npm run build`: the remote clean installation and build passed.
- Astro generated 23 HTML pages and an archived JSON snapshot.
- Local browser checks passed at 390, 1000 and 1440 pixels across light and dark themes.
- Theme persistence, dossier navigation, the seventeen-row data table and the random dossier button passed.
- The deployed site passed phone and desktop checks with 23 internal links and no browser errors.
- The first remote run returned all seventeen current price series, 25 successful source requests and seven selected clippings.

Remote evidence: https://github.com/soylee22/own-the-machine-weekly/actions/runs/35646957015

Date tests cover the London daylight-saving boundary and delayed Monday execution.
Archive tests cover consecutive Sundays, same-date failure and retention of the previous good edition.
The normal quality gate requires at least 80% current price coverage and a successful news discovery feed.

## Boundaries

The news layer selects attributed headlines from public feeds. It does not independently verify every underlying article.
Each story links to the publisher or its discovery redirect. It does not claim that the story caused the price movement.
The permanent dossiers were written for launch. They are not rewritten automatically each week.
The technical cover photograph remains the same until the media configuration changes.
X enrichment and a verified forward event calendar are not enabled.
Public providers can change or restrict access. The source record exposes failures and insufficient coverage blocks publication.
VALL has limited trading history. The application does not fabricate its missing longer returns.
The next real Sunday trigger has not yet occurred. The same workflow completed through manual dispatch, and its schedule is active.

## Operate

Run a fresh collection locally:

```sh
python3 run.py --json
```

Run the workflow manually:

```sh
gh workflow run weekly.yml --repo soylee22/own-the-machine-weekly
```

Inspect its result:

```sh
gh run list --repo soylee22/own-the-machine-weekly --limit 5
```

The weekly workflow includes deployment directly. Archive commits do not depend on starting another workflow.
The original Momentum Power Scanner remains separate and unchanged.
