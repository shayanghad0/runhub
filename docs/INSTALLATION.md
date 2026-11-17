# Installation

RunHub is a local-first desktop app: **Python 3.12+**, **PyQt5**, plain **JSON**
storage. No Docker, no database server, no cloud account. Everything runs on
your machine.

---

## Requirements

| Component | Minimum | Notes |
|---|---|---|
| Python | 3.12 | 3.13 / 3.14 work as well |
| PyQt5 | 5.15+ | `pip install PyQt5` |
| psutil | any recent | optional but recommended (system monitor + process-tree kill) |
| OS | Windows 10/11, macOS 12+, Linux (X11/Wayland) | Windows is the primary dev platform |
| Disk | ~120 MB | app + Qt runtime |
| Display | 1280×660 or larger | window minimum size |

Optional integrations (auto-detected, can be overridden in Settings):

- **VS Code** — for the “Open in VS Code” action (`code` on PATH or picked manually)
- **Windows Terminal / iTerm / GNOME Terminal / konsole** — for “Open terminal here”
- Node.js, Python, PHP — needed only to actually *run* your projects

---

## Quick install

```bash
git clone <your-repo-url> runhub
cd runhub
python -m pip install -r requirements.txt
python main.py
```

`requirements.txt` contains:

```
PyQt5>=5.15.9
psutil>=5.9.0
```

That's the entire dependency tree.

---

## Virtual environment (recommended)

### Windows (PowerShell)

```powershell
cd runhub
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

If PowerShell blocks the activation script, run once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS / Linux

```bash
cd runhub
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## First launch

On the first start RunHub:

1. Creates its **data directory** (see below) and the four JSON files
   (`projects.json`, `profiles.json`, `settings.json`, `logs.json`).
2. Seeds five starter profiles: **Frontend, Backend, AI, Trading, Personal**.
3. Loads every detector plugin from `plugins/`.
4. Opens on the empty dashboard — use **New project** (`Ctrl+N`) or
   **Scan folder…** to begin.

Nothing is installed system-wide and no background service is created.

---

## Data directory

RunHub stores *all* state as JSON. The location is resolved in this order:

1. `--data-dir` command-line flag
2. `RUNHUB_DATA_DIR` environment variable
3. `./data` next to the source tree (portable/dev mode)
4. `~/.runhub` fallback

```bash
python main.py --data-dir "D:/runhub-data"
# or
set RUNHUB_DATA_DIR=D:\runhub-data   (Windows)
export RUNHUB_DATA_DIR=~/runhub-data (macOS/Linux)
```

To move an existing workspace: close RunHub, move the folder, relaunch with
the new `--data-dir`. The files are plain JSON — open them with any editor.

---

## Command-line flags

| Flag | Effect |
|---|---|
| `--data-dir PATH` | Use a custom storage location |
| `--debug` | Verbose console logging of internal events |
| `--version` | Print the version and exit |

Application log: `runhub.log` inside the data directory. On unexpected
exceptions RunHub shows a dialog and writes the traceback to the console
(also visible with `--debug`).

---

## Per-OS notes

### Windows

- Tested on Windows 10/11 with Python 3.12–3.14.
- Process-tree termination uses `psutil` — install it for reliable
  “kill children too” behavior (npm/`vite` spawn child node processes).
- Display scaling 125 %/150 % is fully supported; icons render crisply.
- If Windows SmartScreen warns on first run, it is because the app is
  unsigned — review the source or run from your venv.

### macOS

- PyQt5 via pip works on Intel and Apple Silicon (Rosetta not required for 5.15.9+ wheels).
- First browser-open may trigger a macOS permission prompt — allow it once.
- Gatekeeper applies only if you download a bundled binary; running from
  source has no such step.

### Linux

- Needs an X11 or Wayland session. Headless? Use
  `QT_QPA_PLATFORM=offscreen python main.py` for CI/tests (no GUI).
- Some distros ship `python3` only: `python3 -m pip install -r requirements.txt`.
- If Qt fails to load platform plugins, install the usual suspects:
  `sudo apt install libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0`.

---

## Verifying the install

```bash
python -m compileall -q main.py app plugins
python main.py --version
```

Both should succeed without errors. To sanity-check the full stack without a
display you can also run the bundled offscreen smoke suite (used during
development):

```bash
python - <<'PY'
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import main
print("import OK")
PY
```

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ModuleNotFoundError: No module named 'PyQt5'` | Dependencies not installed in the active interpreter. Re-run `pip install -r requirements.txt` inside the venv you launch with. |
| `python` opens the Microsoft Store | Windows alias hijack — use the real install or `py -3.12 main.py`. |
| Window opens but is unstyled/black | Another QApplication-level stylesheet conflict; launch with `--debug` and check `runhub.log`. |
| “psutil is not installed” on the Monitor page | `pip install psutil`. Without it, CPU/RAM gauges are hidden and child processes may outlive a Stop action. |
| Processes keep running after Stop (Node/npm chains) | Install psutil — RunHub then terminates the whole process tree, not just the shell. |
| Logs directory “Permission denied” | The data dir is not writable (e.g., inside `C:\Program Files`). Choose a user-writable `--data-dir`. |
| Corrupted `projects.json` after a crash / power loss | Automatic: the file is reset and a timestamped copy is kept in `data/backups/`. Manually: delete the JSON file — RunHub recreates it on launch. |
| App starts with no projects though they exist | Check the `--data-dir` you launched with; projects are stored per data directory. |
| High-DPI blur | Ensure PyQt5 ≥ 5.15.9 (the app enables `AA_UseHighDpiPixmaps` itself). |

---

## Uninstall

Delete the repository folder and (optionally) your data directory — there is
no registry entry, no service and no other residue. On Windows the venv is
inside the repo (`.venv`), so it goes with it.
