# GWTradeArb — Phase 4

Public Kamadan trade-chat **fetch + parse + gold WTS↔WTB matching + local SQLite**.
No Guild Wars automation, no whispers, no stored credentials, no LLM, no UI.

You still execute every trade by hand. Chat listings vanish. A positive
`potential_difference` is a **spread between two public prices**, not
guaranteed profit and not an executed trade. The database never stores a
"total profit" figure or paid/received amounts.

## What this is (and is not)

This tool:

- `GET`s public JSON from [decltype](https://kamadan.decltype.org/) and
  [GWToolbox](https://kamadan.gwtoolbox.com/)
- splits WTS/WTB lines into listing atoms (Phase 2)
- matches high-confidence **gold** WTS against WTB (Phase 3)
- upserts listings and opportunities into a **local SQLite** file (Phase 4)

This tool **never**:

- automates the Guild Wars client
- sends whispers or trades
- drives mouse or keyboard
- stores game credentials
- depends on an LLM to parse or match chat
- records actual gold exchanged

If a source is down, the other source still runs. A partial scan does **not**
expire stored opportunities.

## Layout

```
src/gwtradearb/
  models/listing.py         RawMessage + Listing
  models/opportunity.py     Opportunity (a WTS↔WTB pair)
  scrapers/                  public JSON clients
  parsing/parser.py         deterministic gold-first parser
  matching/aliases.py       casefold + aliases + light plurals
  matching/matcher.py       match_listings(listings) -> list[Opportunity]
  database.py               SQLite connect/init/upsert/status/stats
  fingerprint.py            within-source ids + content fingerprints
  collect.py                fetch both sources, isolate failures
  cli.py                    fetch / match / scan / list / stats
tests/fixtures/             anonymised public JSON captures
```

## Setup

Python 3.11+. Runtime is the standard library (including `sqlite3`); pytest is
only for tests.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Database location

Default file (created on first `--scan` / `--save`):

- Linux: `~/.local/share/gwtradearb/gwtradearb.sqlite` (`$XDG_DATA_HOME` if set)
- macOS: `~/Library/Application Support/gwtradearb/gwtradearb.sqlite`
- Windows: `%APPDATA%\gwtradearb\gwtradearb.sqlite`

Overrides:

```bash
export GWTRADEARB_DB=/path/to/file.sqlite
python -m gwtradearb --scan --db ./data/gwtradearb.sqlite
GWTRADEARB_DB_LOCAL=1 python -m gwtradearb --scan   # ./data/gwtradearb.sqlite
```

SQLite files are gitignored (`*.sqlite`, `data/`). Do not commit a DB that
contains your scan history. Schema version is `PRAGMA user_version = 1`.

### Schema overview

| Table | Purpose |
|-------|---------|
| `listings` | Parsed atoms; upserted on `(listing_key)` from source + native id + intent + span |
| `opportunities` | Matched pairs keyed by `opportunity_key`; `status` is `new` / `traded` / `dismissed` / `expired` |
| `opportunity_status_events` | Status history only (no amounts). Rows are never deleted. |
| `settings` | `scan_interval_seconds`, `retention_days`, UI placeholders |
| `scans` | Technical log: started/finished, counts, errors, whether the scan was complete |

`new` opportunities missing from a **complete** later scan (every requested
source responded) are marked `expired`. Traded/dismissed rows stay put.
Re-seeing an expired pair with the same `opportunity_key` revives it to `new`.
Traded/dismissed are not auto-revived.

## Smoke CLI

```bash
python -m gwtradearb
python -m gwtradearb --match
python -m gwtradearb --scan
python -m gwtradearb --match --save --db ./data/gwtradearb.sqlite
python -m gwtradearb --stats
python -m gwtradearb --list
python -m gwtradearb --list --status traded
python -m gwtradearb --mark abcdef012345 traded
```

`--scan` means fetch + parse + match + save. `--high-only` still filters the
listing dump; the matcher always ignores low-confidence and non-gold rows.

`--stats` prints scan/listing/opportunity counts by status. It does **not**
print profit.

## Tests

```bash
pytest
pytest -m "not network"
GWTRADEARB_OFFLINE=1 pytest
```

## Parser rules (Phase 2)

- Detect `WTS` / `WTB` case-insensitively.
- Pure `WTT` is kept as a non-matchable (low confidence) atom.
- Split multi-intent lines on a new `WTS`/`WTB`/`WTT` and on ` -- `.
- Gold prices: `100k`, `45k`, `12,5k`, `g`. `k` means ×1000 gold.
- Ecto `e` and armbrace `a` are recorded as those units and never high-confidence.
- Quantities: `x2`, `(5x)`, `8 for 100k`, `/ea`, `/stack`.
- Missing pieces → `parse_confidence=low`. The parser does not invent values.

Within-source dedup: decltype `id`, gwtoolbox `t`. Cross-source:
`content_fingerprint` of normalised player + message.

## How Phase 2 prices are stored

`Listing.price_amount` is the **parsed price token**, not a rewritten total.

| Chat                         | qty | `price_amount` | Matcher basis |
|------------------------------|-----|----------------|---------------|
| `WTS shield 50k`             | 1   | 50000          | each          |
| `WTB ectos 13k/ea`           | 1   | 13000          | each          |
| `WTB ectos 13k/ea x5`        | 5   | 13000          | each          |
| `WTB Ectos 8 for 100k`       | 8   | 100000         | lot           |
| `wts 8 ectos 100k`           | 8   | 100000         | lot           |

Opportunity prices are gold **for the fill quantity**.

## Matcher rules (Phase 3)

`match_listings(listings) -> list[Opportunity]`.

1. **Same canonical item** (see below).
2. One `WTS`, one `WTB`.
3. Both high-confidence gold.
4. Same `quantity_unit`.
5. Lots are all-or-nothing; each-priced lines may partial-fill.
6. WTS unit gold **<** WTB unit gold.
7. Different players.
8. Different `content_fingerprint`.

`opportunity_key` is stable across rescans and across decltype/GWToolbox mirrors
of the same chat line.

### Item canonicalisation (case and plurals)

Matching uses `canonical_item()`, not the raw chat string:

1. Unicode NFKC + **`casefold`** (so `ecto` / `Ecto` / `ECTOS` agree).
2. Explicit alias table (`ecto`/`ectos`/`ectoplasm` → `glob of ectoplasm`;
   `lockpick`/`lockpicks`; `armbrace`/`armbraces`/`arms`; `warhorn`/`warhorns`;
   `conset`/`consets`).
3. If still unknown, a **light singularisation** of the last token (`mallyx
   shields` → `mallyx shield`). Tokens ending in `ss`/`us`/`is` (`focus`) are
   left alone.

No substring / wiki / LLM matching. `gott` will not become Gift of the Traveler.

### What `potential_difference` is not

Not guaranteed profit, actual profit, or a completed trade.

## Public HTTP sources

| Source    | Live                                      | Search                         | Native id | Time               |
|-----------|-------------------------------------------|--------------------------------|-----------|--------------------|
| decltype  | `GET https://kamadan.decltype.org/api/`   | `GET .../api/search/{query}`   | `id`      | Unix seconds       |
| gwtoolbox | `GET https://kamadan.gwtoolbox.com/m`     | `GET .../s/{query}`            | `t`       | Unix milliseconds  |

User-Agent identifies `GWTradeArb/0.4` as scrape-only, no game automation.
Timeout 15s.

## Limitations

- Tiny alias table plus light plurals. Most slang still will not match.
- No ecto↔gold conversion.
- Lots are not split.
- Expired means "absent from a later complete scan", not "proven unfillable".
- No PySide6 UI, no auto-scan scheduler, no packaging.

## Later phases (do not build here)

- **PySide6 UI** and auto-scan scheduler (New / Traded / Dismissed).
- **Packaging** — PyInstaller / GitHub Release.
- Still never: game automation, credential storage, LLM parsing, profit ledgers.

## License / affiliation

Not affiliated with ArenaNet, NCsoft, decltype, or GWToolbox. Public trade
chat only. Guild Wars is a trademark of NCsoft / ArenaNet.
