# RunHub

**RunHub is an open-source developer workspace manager.** It is a DevBoard-style desktop
application that manages all of your local development projects from one dashboard —
like a task manager + project manager built specifically for developers.

```
React App          Node API          Python Project      Laravel Project
     ↓                  ↓                    ↓                   ↓
  Start               Start               Start               Start
     ↓                  ↓                    ↓                   ↓
 Live Logs          Live Logs           Live Logs           Live Logs
     ↓                  ↓                    ↓                   ↓
Open Browser      Open Browser        Open Browser        Open Browser
     ↓                  ↓                    ↓                   ↓
  Restart            Restart             Restart             Restart
     ↓                  ↓                    ↓                   ↓
   Stop               Stop                Stop                Stop
```

- **Language:** Python 3.12+
- **GUI:** PyQt5
- **Storage:** plain JSON files only — no Docker, no PostgreSQL, no MongoDB, no Firebase,
  no cloud. Everything runs 100% locally.
- **License:** MIT

---

## Why RunHub?

Most developers juggle `npm run dev` in one terminal, `uvicorn` in another, `php artisan serve`
in a third — plus browser tabs, logs and restarts. RunHub replaces that chaos with a single
dashboard: every project is a card with Start / Stop / Restart, a live console, its port and
one-click access to the folder, VS Code and the browser.

| | |
|---|---|
| **Dashboard** | Spotlight-glow project cards with live status, port badges and action buttons |
| **Auto-detection** | React (Vite/Next/CRA/Remix), Node.js, Python, FastAPI, Django, Laravel |
| **Process manager** | Real subprocess lifecycle: start / stop / restart / kill / monitor, whole process tree |
| **Live log viewer** | Auto-scroll, search with match highlighting, level filters, save, clear, error highlighting |
| **Browser manager** | Port probing, URL detection from console output, auto-open when the server is up |
| **System monitor** | CPU / RAM / Disk / Network gauges + sparklines + per-process table (psutil) |
| **Workspace manager** | Open folder, VS Code (auto-detected), terminal (Windows Terminal / PowerShell / …) |
| **Profiles** | Frontend / Backend / AI / Trading / Personal groups — bulk start with staggered launch |
| **JSON database** | `projects.json`, `settings.json`, `profiles.json`, `logs.json` — atomic writes + backups |
| **Plugin system** | Drop `plugins/<name>_plugin.py` files to add detection, tool commands and UI actions |
| **Command palette** | `Ctrl+P` fuzzy-search over commands and projects |
| **Theme system** | Dark + light mode, six accents, animated toggle, fully token-driven QSS |

The UI follows a VS Code / Linear / Raycast / Vercel-inspired design system: dock-style
expandable navigation tabs, spotlight cards that track the mouse, shadcn-style badges,
pulsing status dots, animated theme toggle and SVG-only icons.

---

## Quick start

```bash
# 1. Get the source
git clone <your-repo-url> runhub
cd runhub

# 2. Install dependencies (Python 3.12+)
pip install -r requirements.txt

# 3. Run
python main.py
```

Optional flags:

```bash
python main.py --data-dir "D:/runhub-data"   # custom JSON storage location
python main.py --debug                        # verbose console logging
python main.py --version
```

The `RUNHUB_DATA_DIR` environment variable works too. By default RunHub stores data in
`./data` next to the source (portable/dev mode) and falls back to `~/.runhub`.

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for the full guide (virtualenv,
per-OS notes, troubleshooting).

---

## First run

1. RunHub creates its data directory and seeds five starter profiles:
   **Frontend, Backend, AI, Trading, Personal**.
2. Click **New project** (or `Ctrl+N`), pick a folder — RunHub detects the stack
   automatically and proposes the dev command and port.
3. Hit **▶ Start** on the card. Output streams into the live console;
   when the dev server answers on its port, the browser opens automatically
   (configurable).
4. Or use **Scan folder…** to bulk-import every project inside a directory tree.

---

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+P` / `Ctrl+K` | Command palette |
| `Ctrl+N` | Add new project |
| `Ctrl+R` | Restart current project |
| `Ctrl+L` | Focus the live log search |
| `Ctrl+O` | Open current project folder |
| `Ctrl+F` | Focus dashboard search |
| `Ctrl+1…4` | Dashboard / Profiles / Monitor / Settings |
| `Ctrl+,` | Settings |
| `Ctrl+Q` | Quit |
| `Esc` | Back to dashboard |

---

## Project layout

```
RunHub/
├── main.py                     # entry point (args, high-DPI, excepthook)
├── requirements.txt
├── app/
│   ├── core/
│   │   ├── application.py      # RunHubApplication facade (services, CRUD, bulk ops)
│   │   ├── config_manager.py   # data-dir resolution, logging, JSON IO
│   │   ├── database.py         # thread-safe JSON collections (atomic writes)
│   │   └── plugin_api.py       # BasePlugin, DetectContext, CommandSpec, ActionSpec
│   ├── models/
│   │   ├── project.py          # Project model + ProjectStatus
│   │   ├── profile.py          # Profile model + defaults
│   │   └── settings.py         # AppSettings
│   ├── services/
│   │   ├── process_manager.py  # subprocess lifecycle, StreamReader/Watcher/Stopper
│   │   ├── log_manager.py      # ring buffers, classification, persistence
│   │   ├── browser_manager.py  # port probing, auto-open
│   │   ├── workspace_manager.py# VS Code / terminal / file explorer
│   │   ├── project_detector.py # plugin-based detection + folder scanning
│   │   ├── plugin_loader.py    # isolated import + validation
│   │   └── system_monitor.py   # psutil CPU/RAM/Disk/Network
│   ├── ui/
│   │   ├── theme.py            # design tokens + dark/light palettes + QSS
│   │   ├── icons.py            # SVG icon factory
│   │   ├── main_window.py      # dock nav, pages, shortcuts, toasts
│   │   ├── dashboard.py        # project card grid + list view
│   │   ├── project_view.py     # detail page + live console
│   │   ├── profiles_view.py    # profile cards + bulk actions
│   │   ├── monitor_view.py     # gauges, sparklines, process table
│   │   ├── settings_view.py    # appearance/behavior/integrations/storage/plugins
│   │   ├── command_palette.py  # Ctrl+P fuzzy palette
│   │   ├── dialogs.py          # project/profile editors, bulk import
│   │   └── widgets/            # SpotlightCard, DockNav, ThemeToggle, LogConsole,
│   │                           # Badge, StatusDot, Sparkline, ArcGauge, Toast, …
│   └── utils/
│       ├── filesystem.py       # path validation, permission checks, atomic writes
│       └── helpers.py          # safe command parser/validator, text helpers
└── plugins/
    ├── react_plugin.py
    ├── node_plugin.py
    ├── python_plugin.py
    ├── fastapi_plugin.py
    ├── django_plugin.py
    └── laravel_plugin.py
```

---

## JSON storage

All state lives in human-readable JSON inside the data directory:

```
data/
├── projects.json    # registered projects
├── profiles.json    # workspace profiles (project groups)
├── settings.json    # preferences (theme, accent, toggles, paths)
├── logs.json        # rolling console history per project
├── runhub.log       # application log
└── backups/         # timestamped backups (corruption recovery)
```

Every write is atomic (temp file + `os.replace`), so a crash can never corrupt the
previous state. Corrupted files are backed up and reset automatically. Example project
record:

```json
{
  "id": "a1b2c3d4e5f6",
  "name": "My React App",
  "path": "C:/Projects/app",
  "type": "react",
  "command": "npm run dev",
  "port": 5173,
  "env": { "BROWSER": "none" },
  "groups": ["frontend-id"],
  "favorite": true,
  "auto_open_browser": true
}
```

Example bundles live in [`examples/`](examples/).

---

## Plugin system

Drop a file into `plugins/` following the `<name>_plugin.py` naming pattern:

```python
# plugins/astro_plugin.py
from app.core.plugin_api import BasePlugin, CommandSpec, DetectContext

class Plugin(BasePlugin):
    id = "astro"
    kind = "astro"
    name = "Astro Detector"
    version = "1.0.0"
    priority = 11          # lower = evaluated earlier

    label = "Astro"
    color = "#ff5d01"
    icon = "rocket"
    default_port = 4321

    def detect(self, ctx: DetectContext):
        if not ctx.has_matching_file("astro.config.*"):
            return None
        return {
            "command": "npm run dev",
            "port": 4321,
            "meta": "Astro project (astro.config)",
            "confidence": 0.9,
        }

    def commands(self, project):
        return [CommandSpec(id="sync", label="astro sync", command="npm run sync")]
```

A plugin can contribute:

- **Detection** — `detect(ctx)` inspects the folder (`ctx.files`, `ctx.dirs`,
  `ctx.read_json("package.json")`, `ctx.read_text(".env")`, `ctx.has(...)`).
- **Tool commands** — long-running commands shown as buttons in the project view;
  output streams into the project console.
- **Quick actions** — small one-shot actions.
- **Lifecycle hooks** — `on_loaded(app)` / `on_unloaded()`.

Plugins are imported in isolation: a broken plugin never crashes RunHub — its error
appears in Settings → Plugins. Reload from Settings → **Reload plugins**.

---

## Security model

- **No shell by default.** Commands are parsed into argv lists and executed with
  `shell=False`. Shell operators (`|`, `&&`, `>`, `<`) require explicitly enabling
  *Allow shell* per project.
- **Executable resolution** goes through `shutil.which`; unknown executables are
  rejected with a clear message instead of a shell guess.
- **Always-blocked patterns:** `rm -rf /`, `del /s /q`, `format c:`, `shutdown`,
  `mkfs`, `dd if=`, fork bombs, `git push --force`, …
- **Working directory is validated** (exists, is a directory, readable) before launch.
- **Environment variables are name-validated**; invalid entries are dropped.
- **Process trees are terminated** via psutil (grace period → force kill).
- **Path handling funnels through one module** with permission checks and
  path-traversal resistance.

RunHub never sends data anywhere: no telemetry, no network calls except opening URLs
in *your* browser.

---

## Documentation

- [docs/INSTALLATION.md](docs/INSTALLATION.md) — setup, virtualenv, per-OS notes
- [docs/USAGE.md](docs/USAGE.md) — daily workflow, profiles, plugins, troubleshooting
- [examples/](examples/) — example `projects.json`, `settings.json`, `profiles.json`

## Contributing

PRs are welcome. Please keep the constraints: Python 3.12+, PyQt5, JSON-only storage,
no cloud dependencies. Run the offscreen smoke suite before submitting:

```bash
python -m compileall -q main.py app plugins
```

## License

MIT — see [LICENSE](LICENSE).
