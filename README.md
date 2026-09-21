# Own the Machine Weekly

Own the Machine Weekly is a zero-key weekly magazine for a provisional list of
companies, machines, financial systems and gold exposure.

The product uses public market data and public source feeds. It does not use an
AI API, a Trading 212 credential, or portfolio balances. `config/holdings.yaml`
is the only portfolio configuration and contains the 17 symbols verified on
2026-09-21 without quantities, costs or balances.

## Run

From this directory:

```sh
python3 run.py --asof 2026-09-20
cd site && npm ci && npm run build
```

The normal weekly command is:

```sh
python3 run.py --scheduled --json
```

The scheduled command accepts a Sunday run at or after 19:37 in
`Europe/London`. The issue date is the last completed Sunday. Market bars are
limited to dates on or before that issue date, so a delayed GitHub run cannot
include Monday's partial session.

The normal publication gate requires at least 80% fresh price coverage and one
successful public news discovery feed. `--no-news` is an explicit data-only
exception and remains labelled in the edition quality note. A partial edition
shows its coverage note in the generated data rather than hiding the failure.

## Product rules

- Public source evidence comes before editorial selection.
- Concrete operational events outrank generic market commentary.
- A market move is context. The pipeline never claims that an event caused it.
- Missing data remains visible. A quiet holding is not a negative signal.
- Google News is discovery only. Official company, filing and government links
  receive higher source scores when the feed identifies them.
- Optional X enrichment is not configured and is not required.
- The verified universe includes CNX1.L, VALL.L, SGLN.L and the NYSE MUFG ADR.
- VALL is newly launched. The pipeline does not infer its missing long history
  from an index proxy.

## Layout

`app/` contains the standard-library Python ingestion, calculations, editorial
selection and archive writer. `site/` is an Astro static site. `data/editions/`
stores dated editions and receipts. The live site data under
`site/src/data/` is replaced only by a publishable edition.

The generated edition contract is `config/edition.schema.json`. The current
edition is `site/src/data/edition.json`. The same payload is archived at
`data/editions/YYYY-MM-DD/edition.json` and copied to
`site/src/data/archive/YYYY-MM-DD.json`.

`generated_at` records the actual UTC build time of the first successful issue
creation. Same-issue reruns preserve that timestamp.

## Methodology

The momentum layer preserves the public momentum-power-scanner method:

1. Eight Minervini-style Stage 2 gates.
2. Weighted performance of 40% three-month, 20% six-month, 20% nine-month,
   and 20% twelve-month returns.
3. Percentile RS rating on the current comparison universe.
4. Portfolio Momentum Score for every holding with all four components present,
   ranked across the verified coverage universe.
5. K-ratio as the t-statistic of a log-price trend over up to 252 sessions.

Stage 2 remains a separate eight-gate badge. It does not restrict the
portfolio-relative score.

The public scanner was inspected read-only at
`https://github.com/soylee22/momentum-power-scanner`. This repository does not
modify or replace it.

## Checks

```sh
python3 -m pytest tests -q
python3 -m compileall -q app run.py
cd site && npm run build
```

The GitHub Pages workflow uses the repository's native timezone schedule:

```yaml
cron: "37 19 * * 0"
timezone: "Europe/London"
```
