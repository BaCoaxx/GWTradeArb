# GWTradeArb

Public Kamadan trade-chat **scanner**: fetch → parse → compare → display.

It never automates Guild Wars, never sends whispers, never drives mouse or
keyboard, and never stores game credentials. You still execute every trade by
hand.

A positive `potential_difference` is a **spread between two public chat
prices**, not guaranteed profit and not an executed trade. The UI never shows a
"total profit" figure and never asks what you actually paid.

**Latest standalone builds:** [GitHub Releases](https://github.com/BaCoaxx/GWTradeArb/releases/latest)
(tag `v*`, for example `v0.5.0`). If that page has no assets yet, install from
source below or run the **Release builds** workflow after the tag is on GitHub.

## What this is (and is not)

This tool:

- `GET`s public JSON from [decltype](https://kamadan.decltype.org/) and
  [GWToolbox](https://kamadan.gwtoolbox.com/)
- parses WTS/WTB listing atoms and matches high-confidence **gold** pairs
- persists them in a local SQLite file
- shows them in a desktop table (Scan Now, Mark Traded, Dismiss, filters)
- can also run as a CLI (`--scan`, `--match`, `--list`, `--stats`)

This tool **never**:

- automates the Guild Wars client
- sends whispers or trades
- drives mouse or keyboard
- stores game credentials
- depends on an LLM
- records actual gold exchanged

If one public source is down, the other still runs. The UI shows Online/Offline
badges and keeps going.

## Data sources

| Source | Live feed | Search |
| --- | --- | --- |
| [decltype](https://kamadan.decltype.org/) | `GET https://kamadan.decltype.org/api/` | `/api/search/{query}` |
| [GWToolbox](https://kamadan.gwtoolbox.com/) | `GET https://kamadan.gwtoolbox.com/m` | `/s/{query}` |

No Guild Wars memory reading, no LZ WebSocket, no login. Polite HTTP only.

There is no per-message permalink. **Open Decltype** / **Open GWToolbox** open
the public search homepages.

## How matching works

Deterministic WTS↔WTB gold pairs only. False positives are treated as worse
than misses.

- Item keys use `str.casefold`, a small alias table (`ecto` / `ECTOS` →
  `glob of ectoplasm`), and light last-token plural stripping (`lockpicks` →
  `lockpick`). `gott` will not match Gift of the Traveler.
- Only **high-confidence gold** listings participate. Ecto-priced and
  armbrace-priced lines stay unmatchable. There is no ecto↔gold conversion.
- A WTS unit gold must be cheaper than a WTB unit gold for the same item.
- Lots are all-or-nothing (`8 for 100k` is not split into 1-of-8).
- Same player on both sides, or the same message fingerprint, is skipped.
- `opportunity_key` is a stable SHA-256 across rescans.

`Listing.price_amount` is the parsed token (`8 for 100k` is a lot of 8).
Opportunity prices and `potential_difference` are gold **for the fill
quantity**.

## Download Windows / Linux builds

You do **not** need to install Python if you use a Release asset.

1. Open **[the latest Release](https://github.com/BaCoaxx/GWTradeArb/releases/latest)**.
2. Download:
   - **Windows x64:** `GWTradeArb-Windows-x64.zip` (built on GitHub Actions `windows-latest`)
   - **Linux x64:** `GWTradeArb-Linux-x64.tar.gz` (built on GitHub Actions `ubuntu-latest`)
3. Extract and run:
   - Windows: `GWTradeArb.exe`
   - Linux: `./GWTradeArb`

With no flags, the desktop UI opens. `--help`, `--scan`, and `--stats` work
from a terminal. The Windows zip is **not** a Linux cross-compile.

SQLite still lives in the platform user-data folder (see below), not inside the
extracted directory, unless you pass `--db` or `GWTRADEARB_DB`.

## Install from source

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
python -m gwtradearb --help
```

Keyboard in the UI: F5 refresh, Ctrl+R scan, Ctrl+T mark traded, Ctrl+D dismiss.

Auto-scan: Manual (default) / 1 / 5 / 10 / 30 minutes. Stored in the settings
table. Do not pick a faster interval — be polite to the public sites.

## Database location

- Linux: `~/.local/share/gwtradearb/gwtradearb.sqlite`
- macOS: `~/Library/Application Support/gwtradearb/gwtradearb.sqlite`
- Windows: `%APPDATA%\gwtradearb\gwtradearb.sqlite`

`GWTRADEARB_DB` or `--db` overrides. `GWTRADEARB_DB_LOCAL=1` uses
`./data/gwtradearb.sqlite`. Files are gitignored. Schema
`PRAGMA user_version = 1`.

Settings include `scan_interval_seconds` (`0` = manual) and window size
placeholders for the UI.

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
packaging/                  PyInstaller spec, build + smoke scripts
.github/workflows/          tests + native Release builds
```

## Tests

```bash
pytest
pytest -m "not network"
pytest -m "not network and not gui"
```

GUI smoke uses Qt's offscreen platform when PySide6 can start.

## Building standalone archives

PyInstaller **onedir** bundles. Always build on the target OS. Do not relabel a
Linux build as Windows.

### Linux x64 (this repo, or Ubuntu)

```bash
pip install -e ".[dev]" pyinstaller
python packaging/build_release.py
python packaging/smoke_archive.py
# → dist/GWTradeArb-Linux-x64.tar.gz
```

Requires Python 3.11+ and common Qt runtime libraries (`libegl1`, `libgl1`,
`libxkbcommon0`, …). Smoke runs `--help`, `--version`, and `--stats` against a
temp database (no GUI, no Guild Wars).

### Windows x64

Build on Windows (GitHub Actions `windows-latest` is the supported path):

```bat
python -m pip install -e ".[dev]" pyinstaller
python packaging/build_release.py
python packaging/smoke_archive.py
rem → dist\GWTradeArb-Windows-x64.zip
```

CI: push a `v*` tag (for example `v0.5.0`) or run **Release builds** via
`workflow_dispatch`. The tag workflow attaches both archives to a GitHub
Release. Windows verification is the Actions log for `Smoke packaged binary`
on `windows-latest`.

## Limitations

- Tiny alias table. Common abbreviations beyond the table are not guessed.
- No ecto↔gold conversion.
- No Discord / email / in-game notifications.
- Chat listings vanish. A spread you saw can be gone before you whisper.
- `potential_difference` is not profit.
- Packaged builds are x64 only (Linux and Windows). No macOS archive yet;
  run from source on macOS.
- The Windows exe is a console+GUI hybrid so `--help` works; a console window
  may appear when launched from Explorer.

## License / affiliation

MIT. See [LICENSE](LICENSE).

Not affiliated with ArenaNet, NCsoft, decltype, or GWToolbox. Public trade
chat only. Guild Wars is a trademark of NCsoft / ArenaNet.
