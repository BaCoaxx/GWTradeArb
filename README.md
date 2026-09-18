"""Phase 2 of GWTradeArb: public Kamadan trade-chat fetch + parse.

GWTradeArb will become a Guild Wars Kamadan trading **opportunity scanner**.
This repository is **Phase 2 only**: scrape public JSON, parse it deterministically,
and print listing atoms. It does not match buyers to sellers, persist a database,
or ship a UI.

## What this is (and is not)

This tool:

- `GET`s public JSON from [decltype](https://kamadan.decltype.org/) and
  [GWToolbox](https://kamadan.gwtoolbox.com/)
- splits WTS/WTB lines into listing atoms
- extracts item / quantity / gold-or-shorthand price **only when confident**

This tool **never**:

- automates the Guild Wars client
- sends whispers or trades
- drives mouse or keyboard
- stores game credentials
- depends on an LLM to parse chat

If a source is down, the other source still runs.

## Layout

```
src/gwtradearb/
  models/listing.py      RawMessage + Listing
  scrapers/decltype.py   GET https://kamadan.decltype.org/api/
  scrapers/gwtoolbox.py  GET https://kamadan.gwtoolbox.com/m
  parsing/parser.py      deterministic gold-first parser
  fingerprint.py         within-source ids + content fingerprints
  collect.py             fetch both sources, isolate failures
  cli.py                 one-shot smoke entry
tests/fixtures/          anonymised public JSON captures
```

## Setup

Python 3.11+. Runtime is the standard library; pytest is only for tests.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
# or: pip install -r requirements.txt && pip install -e .
```

## Smoke CLI

One-shot fetch + parse (no UI):

```bash
python -m gwtradearb
python -m gwtradearb --source decltype
python -m gwtradearb --source gwtoolbox --search ecto
python -m gwtradearb --high-only
python -m gwtradearb --json
```

`--high-only` prints gold listings the later matching engine should consider.

## Tests

```bash
pytest
pytest -m "not network"          # fixtures only; skip live HTTP
GWTRADEARB_OFFLINE=1 pytest      # skip live smokes even if the marker is selected
```

Fixture tests always run offline. Live smokes hit the public endpoints and
**skip** (they do not fail) if the network or a source is down.

## Parser rules (Phase 2)

- Detect `WTS` / `WTB` case-insensitively.
- Pure `WTT` is kept as a non-matchable (low confidence) atom, or ignored for matching.
- Split multi-intent lines on a new `WTS`/`WTB`/`WTT` and on ` -- `.
  Example: `WTS Armbraces 30e/ea -- WTB Mini Rift Warden 15a` → two atoms.
- Gold prices: `100k`, `45k`, `12,5k`, `g`. `k` means ×1000 gold.
- Ecto `e` and armbrace `a` are recorded as those units and **never high-confidence**
  in this phase (no conversion table yet).
- Quantities: `x2`, `(5x)`, `8 for 100k`, `/ea`, `/stack`. `8 for 100k (5x)` uses
  bundle size 8, not the extra lot marker.
- Missing intent, item, quantity, or a comparable gold price → `null` fields and
  `parse_confidence=low`. The parser does not invent values.
- Same-intent grocery lists with several prices stay low rather than being guessed apart.

Dedup:

- Within source: decltype `id`, gwtoolbox `t`.
- Cross-source (later): SHA-256 of normalised player + message (`content_fingerprint`).

GWToolbox `r` is stored as `replaces_id` and is not collapsed yet.

## Public HTTP sources

| Source    | Live                                      | Search                                      | Native id | Time                  |
|-----------|-------------------------------------------|---------------------------------------------|---------|-----------------------|
| decltype  | `GET https://kamadan.decltype.org/api/`   | `GET .../api/search/{query}` (~25)          | `id`    | `timestamp` Unix s    |
| gwtoolbox | `GET https://kamadan.gwtoolbox.com/m`     | `GET .../s/{query}` (~100 live)             | `t`     | `t` Unix ms           |

The GWToolbox LZ-compressed WebSocket is **out of scope** for v1.

Requests send a identifying `User-Agent` (`GWTradeArb/0.2 … no game automation`)
and a 15s timeout.

Fixtures in `tests/fixtures/` are anonymised captures of those public JSON
feeds (player names replaced with `TraderNNN`; message text is real public
trade chat).

## Limitations

- No item catalogue / wiki aliasing (`gott` vs Gift of the Traveler).
- No ecto↔gold or armbrace↔ecto conversion, so most Kamadan lines stay low.
- No matching of WTS against WTB.
- No history, SQLite, or UI.
- Chat is noisy; high-confidence recall is intentionally low.

## Later phases (do not build here)

- **Matching engine** — gold-only, high-confidence WTS vs WTB.
- **SQLite persistence** — never commit DBs with personal data.
- **PySide6 UI** and auto-scan scheduler.
- **Packaging** — PyInstaller / GitHub Release.
- Still never: game automation, credential storage, LLM parsing.

## License / affiliation

Not affiliated with ArenaNet, NCsoft, decltype, or GWToolbox. Public trade
chat only. Guild Wars is a trademark of NCsoft / ArenaNet.
