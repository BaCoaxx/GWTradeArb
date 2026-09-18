# GWTradeArb — Phase 5

Public Kamadan trade-chat **fetch + parse + gold matching + local SQLite + PySide6 UI**.
No Guild Wars automation, no whispers, no stored credentials, no LLM, no packaging.

You still execute every trade by hand. Chat listings vanish. A positive
`potential_difference` is a **spread between two public prices**, not
guaranteed profit and not an executed trade. The UI never shows a "total profit"
figure and never asks what you actually paid.

## What this is (and is not)

This tool:

- `GET`s public JSON from [decltype](https://kamadan.decltype.org/) and
  [GWToolbox](https://kamadan.gwtoolbox.com/)
- parses WTS/WTB listing atoms and matches high-confidence **gold** pairs
- persists them in a local SQLite file
- shows them in a desktop table (Scan Now, Mark Traded, Dismiss, filters)

This tool **never**:

- automates the Guild Wars client
- sends whispers or trades
- drives mouse or keyboard
- stores game credentials
- depends on an LLM
- records actual gold exchanged

If one public source is down, the other still runs. The UI shows Online/Offline
badges and keeps going.

## Run the GUI (Windows and Linux, from source)

Python 3.11+. PySide6 is a runtime dependency.

```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
# or: pip install -r requirements.txt && pip install -e .
```

```bash
python -m gwtradearb
python -m gwtradearb --gui
python -m gwtradearb --gui --db ./data/gwtradearb.sqlite
```

With no action flags, the desktop UI opens. CLI commands still work:

```bash
python -m gwtradearb --scan
python -m gwtradearb --match --search ecto
python -m gwtradearb --stats
python -m gwtradearb --list --status traded
```

Keyboard in the UI: F5 refresh, Ctrl+R scan, Ctrl+T mark traded, Ctrl+D dismiss.

Auto-scan: Manual (default) / 1 / 5 / 10 / 30 minutes. Stored in the settings
table. Do not pick a faster interval — be polite to the public sites.

There is no per-message permalink. **Open Decltype** / **Open GWToolbox** open
the public search homepages.

## Layout

```
src/gwtradearb/
  models/                   RawMessage, Listing, Opportunity
  scrapers/                 public JSON clients
  parsing/parser.py         deterministic gold-first parser
  matching/                 aliases + match_listings
  database.py               SQLite
  scan.py                   one fetch→match→persist cycle
  display.py                gold formatting + row filters (no Qt)
  ui/window.py              PySide6 main window
  ui/worker.py              QThread scan worker
  cli.py
```

## Database location

- Linux: `~/.local/share/gwtradearb/gwtradearb.sqlite`
- macOS: `~/Library/Application Support/gwtradearb/gwtradearb.sqlite`
- Windows: `%APPDATA%\gwtradearb\gwtradearb.sqlite`

`GWTRADEARB_DB` or `--db` overrides. Files are gitignored. Schema
`PRAGMA user_version = 1`.

Settings include `scan_interval_seconds` (`0` = manual) and window size
placeholders for the UI.

## Tests

```bash
pytest
pytest -m "not network"
pytest -m "not network and not gui"
```

GUI smoke uses Qt's offscreen platform when PySide6 can start.

## Parser / matcher (Phases 2–3)

Gold-first listings; ecto/armbrace stay unmatchable. Item keys use `casefold`,
an alias table (`ecto`/`ECTOS` → `glob of ectoplasm`), and light last-token
plurals. Lots are not split. `opportunity_key` is stable across rescans.

`Listing.price_amount` is the parsed token (`8 for 100k` is a lot of 8).
Opportunity prices are gold for the fill quantity.

## Persistence (Phase 4)

Upsert listings and opportunities. Status `new` / `traded` / `dismissed` /
`expired`. History is never deleted; status events store no amounts. `new`
rows expire only after a complete scan (every requested source responded).

## Limitations

- Tiny alias table. `gott` will not match Gift of the Traveler.
- No ecto↔gold conversion.
- No standalone installer (Phase 6+).
- No Discord/email/GW notifications.

## Later phases (do not build here)

- **Packaging** — PyInstaller / GitHub Release.
- Still never: game automation, credential storage, LLM parsing, profit ledgers.

## License / affiliation

Not affiliated with ArenaNet, NCsoft, decltype, or GWToolbox. Public trade
chat only. Guild Wars is a trademark of NCsoft / ArenaNet.
