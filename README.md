# GWTradeArb — Phase 3

Public Kamadan trade-chat **fetch + parse + gold WTS↔WTB matching**.
No Guild Wars automation, no whispers, no stored credentials, no LLM.

You still execute every trade by hand. Chat listings vanish. A positive
`potential_difference` is a **spread between two public prices**, not
guaranteed profit and not an executed trade.

## What this is (and is not)

This tool:

- `GET`s public JSON from [decltype](https://kamadan.decltype.org/) and
  [GWToolbox](https://kamadan.gwtoolbox.com/)
- splits WTS/WTB lines into listing atoms (Phase 2)
- matches high-confidence **gold** WTS against WTB when the item, unit, and
  quantities line up (Phase 3)

This tool **never**:

- automates the Guild Wars client
- sends whispers or trades
- drives mouse or keyboard
- stores game credentials
- depends on an LLM to parse or match chat

If a source is down, the other source still runs.

## Layout

```
src/gwtradearb/
  models/listing.py         RawMessage + Listing
  models/opportunity.py     Opportunity (a WTS↔WTB pair)
  scrapers/decltype.py      GET https://kamadan.decltype.org/api/
  scrapers/gwtoolbox.py     GET https://kamadan.gwtoolbox.com/m
  parsing/parser.py         deterministic gold-first parser
  matching/aliases.py       explicit item shorthand table
  matching/matcher.py       match_listings(listings) -> list[Opportunity]
  fingerprint.py            within-source ids + content fingerprints
  collect.py                fetch both sources, isolate failures
  cli.py                    one-shot smoke entry
tests/fixtures/             anonymised public JSON captures
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

Fetch, parse, **match**, print opportunities:

```bash
python -m gwtradearb --match
python -m gwtradearb --match --high-only
python -m gwtradearb --match --listings
python -m gwtradearb --match --json
python -m gwtradearb --match --search ecto
```

`--high-only` still filters the listing dump to high-confidence gold rows.
The matcher **always** ignores low-confidence and non-gold listings, with or
without that flag.

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
  (no conversion table yet), so they never enter the matcher.
- Quantities: `x2`, `(5x)`, `8 for 100k`, `/ea`, `/stack`. `8 for 100k (5x)` uses
  bundle size 8, not the extra lot marker.
- Missing intent, item, quantity, or a comparable gold price → `null` fields and
  `parse_confidence=low`. The parser does not invent values.
- Same-intent grocery lists with several prices stay low rather than being guessed apart.

Dedup:

- Within source: decltype `id`, gwtoolbox `t`.
- Cross-source listing identity: SHA-256 of normalised player + message
  (`content_fingerprint`). The matcher uses this so the same chat line mirrored
  on both sites is one logical side.

GWToolbox `r` is stored as `replaces_id` and is not collapsed yet.

## How Phase 2 prices are stored (needed for matching)

`Listing.price_amount` is the **parsed price token**, not a rewritten inventory total.

| Chat                         | qty | `price_amount` | Basis the matcher uses |
|------------------------------|-----|----------------|------------------------|
| `WTS shield 50k`             | 1   | 50000          | each (qty 1)           |
| `WTB ectos 13k/ea`           | 1   | 13000          | each                   |
| `WTB ectos 13k/ea x5`        | 5   | 13000          | each (`/ea`)           |
| `WTB Ectos 8 for 100k`       | 8   | 100000         | lot (bundle)           |
| `wts 8 ectos 100k`           | 8   | 100000         | lot (qty>1, no `/ea`)  |

`potential_difference`, `sell_price`, and `buy_price` on an Opportunity are gold
**for the fill quantity** (the overlapping lot), not leftover per-unit quotes.

## Matcher rules (Phase 3)

`match_listings(listings) -> list[Opportunity]` is deterministic.

An opportunity is created only when **all** of these hold:

1. **Same item** after normalisation (lowercase, punctuation stripped) and an
   explicit alias table (`ecto` / `ectos` / `ectoplasm` → `glob of ectoplasm`,
   `lockpick` / `lockpicks` → `lockpick`). No fuzzy / substring / wiki matching.
2. One side `WTS`, the other `WTB`.
3. Both `parse_confidence == high` (which already implies gold in Phase 2).
4. Same `quantity_unit` (`each` vs `stack` do not mix).
5. Compatible quantities without inventing a split:
   - **Each-priced** lines may partial-fill (`fill_qty = min(qty)`).
   - **Lots** (`N for 100k`, `N=100k`, `N/100k`, or qty>1 without `/ea`) are
     all-or-nothing. An `8 for 100k` seller is never assumed to sell 1-of-8.
     A buyer of 10 each *can* take a whole lot of 8.
6. `WTS` unit gold **<** `WTB` unit gold. Otherwise no opportunity.
7. Different players (normalised). You cannot arb with yourself.
8. Different `content_fingerprint` (do not pair a line with its other-site mirror
   as the counterparty).

`opportunity_key` is a SHA-256 of canonical item + fill qty + each side's
`(content_fingerprint, intent, item, quantity_unit)`. Rescans and decltype /
GWToolbox mirrors of the same chat line do not multiply a pair.

Rank: fresher pair first (`max(wts timestamp, wtb timestamp)`), then larger
`potential_difference`, then `opportunity_key`.

### What `potential_difference` is not

It is **not** guaranteed profit, actual profit, or a completed trade. The
other player may be gone, joking, or already filled. Confirm in-game, by hand.

## Public HTTP sources

| Source    | Live                                      | Search                                      | Native id | Time                  |
|-----------|-------------------------------------------|---------------------------------------------|---------|-----------------------|
| decltype  | `GET https://kamadan.decltype.org/api/`   | `GET .../api/search/{query}` (~25)          | `id`    | `timestamp` Unix s    |
| gwtoolbox | `GET https://kamadan.gwtoolbox.com/m`     | `GET .../s/{query}` (~100 live)             | `t`     | `t` Unix ms           |

The GWToolbox LZ-compressed WebSocket is **out of scope** for v1.

Requests send a identifying `User-Agent` (`GWTradeArb/0.3 … no game automation`)
and a 15s timeout.

Fixtures in `tests/fixtures/` are anonymised captures of those public JSON
feeds (player names replaced with `TraderNNN`; message text is real public
trade chat).

## Limitations

- Tiny item alias table. `gott` will not match Gift of the Traveler.
- No ecto↔gold or armbrace↔ecto conversion; those listings stay unmatchable.
- Lots are not split. Many real Kamadan lines therefore produce no opportunity.
- No SQLite history, no New/Traded/Dismissed status, no UI.
- Chat is noisy; high-confidence recall is intentionally low.

## Later phases (do not build here)

- **SQLite persistence** — never commit DBs with personal data.
- **PySide6 UI** and auto-scan scheduler (New / Traded / Dismissed).
- **Packaging** — PyInstaller / GitHub Release.
- Still never: game automation, credential storage, LLM parsing.

## License / affiliation

Not affiliated with ArenaNet, NCsoft, decltype, or GWToolbox. Public trade
chat only. Guild Wars is a trademark of NCsoft / ArenaNet.
