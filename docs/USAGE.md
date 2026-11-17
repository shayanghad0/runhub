# Usage Guide

RunHub is a local-first developer workspace manager: it keeps every project
you run on your machine in one dashboard, starts/stops them like services,
streams their logs, and groups them into one-click profiles. All state lives
in four JSON files next to you — nothing is uploaded anywhere.

> Install first? See **[INSTALLATION.md](INSTALLATION.md)**.

---

## The main window

| Area | What it does |
|---|---|
| **Dock rail** (left) | Expandable navigation — Dashboard, Project detail, Profiles, Monitor, Settings, plus the dark/light toggle at the bottom. Hover to expand, click to switch. |
| **Page stack** (center) | The active page. |
| **Status bar** (footer) | Running count, `Ctrl+P` hint, live CPU / RAM and the app version. |
| **Toasts** (top-right) | Non-blocking notifications: port detected, process exited, tool started… |

**Pages:** `Ctrl+1` Dashboard · `Ctrl+2` Project detail · `Ctrl+3` Profiles ·
`Ctrl+4` Monitor · `Ctrl+5` Settings

---

## Quick start — add your first project

1. Press **Ctrl+N** (or *New project* on the empty dashboard).
2. Point the dialog at a project folder, e.g. `D:\dev\my-app`.
3. RunHub **auto-detects** the stack: React, Node, Python, FastAPI, Django,
   Laravel — and fills in a run command and (when known) a default port.
4. Press **Save**, then **Start** on the card. Your dev server boots as a
   managed process; when the port opens, the card shows a link and (optionally)
   your browser opens it automatically.

**Scan folder…** (dashboard header) does the same in bulk: pick a parent
folder and RunHub detects every project inside it, so you can import the
whole set at once with checkboxes.

### Detection, editing and your saved config

- The edit dialog re-detects **only when the folder path changes**. Editing a
  project without touching its path keeps your saved command, type and port —
  detection will not silently rewrite your working setup.
- Change the folder and detection runs again; the "Detection:" line shows what
  it found before anything is overwritten.

---

## The dashboard

Each **card** shows the project name, type icon, live status dot, port badge
and action row:

- **Start / Stop** — toggles the process (whole process tree, including child
  node processes, is terminated on Stop).
- **Restart** (`Ctrl+R` on the current project) — graceful stop, then start.
- **Open folder** — your file manager, and **Open terminal** — a terminal
  pre-positioned in the project directory.
- **Open browser / Copy URL** — when a port is configured.
- **VS Code** — opens the folder in your editor (auto-discovered or set in
  Settings → *Editor path*).

Right-click a card for the full menu (open details, VS Code, terminal,
copy path, edit, delete). Click a card to open the **detail view** with stats,
URLs, environment table and the live console.

**Filtering tools** above the grid:

- Search box (`Ctrl+F` to focus) — matches name, type, path, tags, description.
- Status chips (running / stopped), type filter, sort control,
  **grid / list** view toggle. Favorites can be pinned to the top.

---

## Live log console

Open a project's detail view to watch stdout/stderr in real time.

- **Auto-scroll** pauses automatically while you scroll up and resumes at the bottom.
- **Level chips** — filter INFO / WARN / ERROR / SYS; warnings and errors stay highlighted.
- **Search box** (`Ctrl+L` to focus) — highlights every match, `Enter` jumps to the next.
- **Toolbar** — clear, save to file, font size −/+, word-wrap toggle.

---

## Profiles — start everything at once

A profile is a named group of projects (the seeds are *Frontend, Backend, AI,
Trading, Personal* — edit them freely).

1. **Profiles → New profile**, give it a name, color and tick the member projects.
2. On the profile card: **Start all**, **Stop all**, **Restart all** — members
   are started staggered (one after another) so port conflicts and racey
   boot order don't bite.
3. Click a member chip to jump straight to that project.

---

## Monitor page

Live system health for the whole machine plus a table of every process RunHub
manages (CPU %, memory, uptime, pid):

- CPU / RAM gauges with history sparklines, network throughput, disk usage.
- The managed-process table refreshes with the monitor interval
  (Settings → *Monitor interval*).
- Requires `psutil`; without it the page shows a notice and the rest of the
  app keeps working.

---

## Command palette & shortcuts

**Ctrl+P** (or **Ctrl+K**) opens the fuzzy-search palette: navigate anywhere,
toggle the theme, start/stop any project by name, open folders or browsers.

| Shortcut | Action |
|---|---|
| `Ctrl + P` / `Ctrl + K` | Command palette |
| `Ctrl + N` | Add a new project |
| `Ctrl + O` | Open current project folder |
| `Ctrl + R` | Restart current project |
| `Ctrl + L` | Focus live log search |
| `Ctrl + F` | Focus dashboard search |
| `Ctrl + 1…5` | Switch pages |
| `Ctrl + ,` | Settings |
| `Ctrl + Q` | Quit (warns if processes are running) |

---

## Appearance

- **Dark / light toggle** — the pill switch in Settings or the moon/sun button
  on the dock rail; both stay in sync and the window restyles live.
- **Accent** — six hues (Indigo, Violet, Rose, Emerald, Cyan, Amber) drive the
  glow, highlights and buttons.
- **Font size** — scales the UI between 8 and 14 pt.

Choices persist in `settings.json` and survive restarts.

---

## Plugins (project detectors)

Plugins are small Python files in `plugins/` that recognize project types and
contribute tool commands to the detail view. Built-ins: **react, node,
python, fastapi, django, laravel**.

- Settings → *Plugins* lists every detector with a checkbox.
- Toggling one off stops it from detecting projects **and** removes its tool
  commands; the entry stays listed (unchecked) so you can re-enable it any time.
- Broken plugin files never crash the app — they appear as ⚠ entries.

Write your own: subclass `BasePlugin` from `app/core/plugin_api.py`, drop the
file into `plugins/` as `mything_plugin.py`, press **Reload plugins** in
Settings.

---

## Where your data lives

Everything is plain JSON in the data directory (see
[INSTALLATION.md → Data directory](INSTALLATION.md#data-directory)):

| File | Contents |
|---|---|
| `projects.json` | Every project (see `examples/projects.example.json`) |
| `profiles.json` | Profiles and their member project ids |
| `settings.json` | Appearance, behavior and plugin toggles |
| `logs.json` | Persisted log tail per project (size capped in Settings) |
| `runhub.log` | Application log |
| `backups/` | Timestamped copies written when a corrupt file is recovered |

Move a workspace by closing RunHub and copying the folder — relaunch with
`--data-dir` pointing at the new location. Example files in `examples/` show
the exact shape of each document; you can seed a fresh data directory from
them (drop them in *without* the `examples` filenames, or start RunHub once
and paste the contents).

---

## Safety model

- Commands run through a parsed argv, **never a shell**, unless you
  explicitly enable *Allow shell* on a project.
- A blocklist rejects dangerous commands (`rm -rf`, `shutdown`, `format`,
  fork bombs, …) before they can start.
- Stopping and quitting-with-runners ask for confirmation (both can be
  disabled in Settings).
- Process trees are killed via psutil — no orphaned `node` children.

---

## Tips

- Pin your daily driver as **Favorite** (star in the detail view header) — favorites sort first and surface on top in the palette.
- Frontend needs the backend up first? Start the API alone once (it stays up), or give the API `auto_open_browser` off so profile starts don't spam browser tabs.
- If a port badge shows *no port*, set the port in the edit dialog to get browser/copy-URL actions.
