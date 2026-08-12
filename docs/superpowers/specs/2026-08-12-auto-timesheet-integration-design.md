# Auto Timesheet Integration — Design

**Date:** 2026-08-12
**Project:** countdown-timer
**Author:** zhiming

## Goal

Migrate the standalone `auto_timesheet_python/main.py` script into the countdown-timer app so that:

1. The script is imported as a module (no subprocess, no separate process).
2. All script startup parameters are configurable from the tray menu.
3. The user can set a daily execution time.
4. A manual "Run Now" trigger is available.

## Source Files to Migrate

From `E:\project\private_user_scripts\auto_timesheet_python\`:

- `main.py` → `auto_timesheet.py` (renamed to avoid clash with countdown-timer's `main.py`).
- `toppan-ca-bundle.pem` → copied verbatim (TLS verification stays ON).

The script exposes `submit_timesheet(config: TimesheetConfig, force_submit: bool) -> TimesheetResult` and the `TimesheetConfig` dataclass. These are the only public symbols consumed.

## File Layout

```
countdown-timer/
├── main.py                       # existing — gains tray submenu + scheduler hook
├── auto_timesheet.py             # NEW — copied from source, minimally adapted
├── toppan-ca-bundle.pem          # NEW — copied from source
├── timesheet_debug/              # NEW — auto-created at runtime
│   ├── *.html                    # debug HTML dumps
│   └── timesheet.log             # rotated log file
├── config.cof                    # existing — gains a "timesheet" sub-key
└── ... (existing files unchanged)
```

## Modifications to `auto_timesheet.py`

Minimal, preserving the script's standalone CLI usability:

1. **`TimesheetSession.__init__` gains `debug_dir: str | None = None`.**
   When set, `_save_debug_html` writes into that directory (created lazily). Default `None` preserves current behavior (writes to CWD) for direct CLI invocation.

2. **`submit_timesheet(config, force_submit)` accepts an optional `debug_dir` kwarg**, forwarded to `TimesheetSession`.

3. **Module-level `socket.setdefaulttimeout(30)`** stays unchanged.

4. **The `__main__` argparse block stays** so the script remains runnable standalone.

5. **`logging.basicConfig` at module import** is replaced with lazy configuration:
   - Remove the module-level `basicConfig` call.
   - Expose `configure_logging(log_path: Path | None = None, level=str = "INFO") -> None` that main.py calls once at startup with `timesheet_debug/timesheet.log`. If never called, the module falls back to a default `basicConfig` so standalone runs still work.

No other behavioral changes to the script.

## Config Schema

Added under the existing `config.cof` JSON, in a new `timesheet` sub-key:

```json
{
  "timesheet": {
    "enabled": false,
    "username": "zhiming",
    "password": "password$1",
    "project": "PD_AGP",
    "task": "Prodt Devt",
    "hours": 8,
    "exec_time": "09:05",
    "force_submit": false,
    "ca_bundle": "toppan-ca-bundle.pem",
    "last_run": null,
    "last_result": null
  }
}
```

Field rules:

- `exec_time` — `"HH:MM"` 24h with leading zeros. Consumed by `schedule.every().day.at(...)`.
- `ca_bundle` — path relative to the countdown-timer directory, or absolute. Empty string = TLS verification OFF (falls back to `verify_tls=False`).
- `hours` — int 1–12 inclusive.
- `last_run` — ISO 8601 datetime of the last attempt; `null` until first run.
- `last_result` — `"submitted" | "skipped" | "failed"`; `null` until first run.

**Migration:** On startup, if `config["timesheet"]` is missing or any field is missing, it's merged with the defaults shown above (same pattern as existing `init_url` / `init_alpha`). Existing timer config is untouched.

## Tray Submenu

Inserted into the existing `pystray.Menu` between `初始化窗口位置` and `退出`:

```
Auto Timesheet ▸
  ├─ Enabled  ✓/✗                  (checkable toggle, persists enabled)
  ├─ Settings...                   (opens Tk Toplevel dialog)
  ├─ Run Now                       (manual trigger; disabled while a run is in progress)
  └─ Last: 2026-08-12 09:05 — submitted   (informational, dynamic text)
```

Behavior:

- **Enabled** — toggles `config["timesheet"]["enabled"]`, persists immediately, calls `_reschedule_timesheet()`.
- **Settings...** — opens the dialog (see next section). Parented to `self.window` (the timer's hidden Tk root) so it stays above other windows.
- **Run Now** — calls `_run_timesheet_async(force=False)`. The menu item uses `pystray.MenuItem(..., enabled=lambda item: not self._timesheet_running)` so it's grayed out while a run is in progress.
- **Last** — non-clickable item (its `action` is `None`); its `text` is a callable that formats `"Last: {last_run:%Y-%m-%d %H:%M} — {last_result}"` or `"Last: (never)"` before the first run.

## Settings Dialog

A single `tk.Toplevel`, ~360×320, titled `"Auto Timesheet Settings"`:

```
┌─────────────────────────────────────────────┐
│  Username:  [zhiming___________]            │
│  Password:  [********___________]  (show='*')│
│  Project:   [PD_AGP____________]            │
│  Task:      [Prodt Devt_________]           │
│  Hours/day: [Spinbox 1–12, default 8]       │
│  Exec time: [09] : [05]    (HH:MM, 24h)     │
│  CA bundle: [toppan-ca-bundle.pem] [Browse] │
│  ☐ Force re-submit even if already saved    │
│                                             │
│              [Save]   [Cancel]              │
└─────────────────────────────────────────────┘
```

Validation on Save:

- Hours ∈ [1, 12].
- HH ∈ [0, 23], MM ∈ [0, 59].
- Username, project, task non-empty (stripped).
- Password may be empty (server will reject; we don't pre-validate).

On validation error: `messagebox.showerror`, keep the dialog open.

On successful Save:

1. Update `config["timesheet"]` with all fields.
2. Persist via existing `save_config`.
3. Call `_reschedule_timesheet()`.
4. Close dialog.

Cancel: close without writing.

Browse button: opens `filedialog.askopenfilename(filetypes=[("PEM/CRT", "*.pem *.crt"), ("All", "*.*")])`; on selection, stores absolute path. On Save, if path is under the countdown-timer directory, it's stored as a relative path; otherwise as absolute.

## Scheduling & Execution Flow

### Scheduling

New method on `App`:

```
_reschedule_timesheet():
    schedule.clear("timesheet")
    if not config["timesheet"]["enabled"]:
        return
    exec_time = config["timesheet"]["exec_time"]
    schedule.every().day.at(exec_time).do(self._run_timesheet_async, force=False).tag("timesheet")
```

Called from:

- `start_schedule()` (existing method, after the existing work/target scheduling).
- After every successful Settings Save.
- After every Enabled toggle.

The existing `run_task()` thread continues to call `schedule.run_pending()` every second; no new thread needed.

### Execution

```
_run_timesheet_async(self, force: bool = False):
    if self._timesheet_running:
        return
    self._timesheet_running = True
    threading.Thread(target=self._run_timesheet_sync, args=(force,), daemon=True).start()

_run_timesheet_sync(self, force: bool):
    cfg = self._build_timesheet_config()
    try:
        result = submit_timesheet(cfg, force_submit=force or cfg.force_submit, debug_dir=TIMESHEET_DEBUG_DIR)
        action = "skipped" if "skipped" in result.message.lower() else (
                 "submitted" if result.success else "failed")
        self._on_timesheet_done(action, result.message, result.week)
    except Exception as e:
        self._on_timesheet_done("failed", f"Exception: {e}", "")
    finally:
        self._timesheet_running = False

_on_timesheet_done(self, action, message, week):
    config["timesheet"]["last_run"] = datetime.datetime.now().isoformat()
    config["timesheet"]["last_result"] = action
    save_config(config)
    title = "Timesheet submitted" if action == "submitted" else (
            "Timesheet skipped" if action == "skipped" else "Timesheet failed")
    body = f"{week}: {message}" if week else message
    self._show_toast(title, body)
```

`_build_timesheet_config` reads `config["timesheet"]`, resolves `ca_bundle`:

- If `ca_bundle` is empty → `verify_tls=False`.
- Else: resolved to absolute path. If the file exists → `verify_tls=<abs_path>`. Else → log a warning and fall back to `verify_tls=False`.

`TIMESHEET_DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timesheet_debug")`.

### Logging

At startup in `main.py` (inside `App.__init__`, before any timesheet operation):

```
from auto_timesheet import configure_logging
configure_logging(log_path=Path(TIMESHEET_DEBUG_DIR) / "timesheet.log", level="INFO")
```

The `configure_logging` helper attaches:

- A `RotatingFileHandler` writing to the given path (max 1 MB, 3 backups).
- A `StreamHandler` to stderr (so standalone CLI runs still see output).

Idempotent: safe to call multiple times.

## Error & Edge Cases

| Case | Handling |
|------|----------|
| PC off at scheduled time | `schedule` skips missed runs. Acceptable for v1. |
| Concurrent Run Now + scheduled fire | `_timesheet_running` flag makes the second call a no-op. |
| Login failure (bad credentials, network) | `submit_timesheet` returns `success=False`; surfaced via toast with the error message; `last_result="failed"`. |
| Config missing on first launch | Merged with defaults (see "Migration" above); `enabled=False`. |
| CA bundle file missing despite config | Falls back to `verify_tls=False`, logs warning. |
| Debug HTML files | Written to `timesheet_debug/`, overwriting prior run's files. |
| Settings dialog validation error | `messagebox.showerror`, dialog stays open. |

## Out of Scope

- Automated tests (the project currently has none; matching scope).
- Missed-run catch-up (run-on-startup-if-missed).
- Encrypted password storage.
- Localization of toast messages.

## Testing Plan

Manual:

1. First launch: defaults populated, Enabled shows ✗, Last shows "(never)".
2. Open Settings, change project to a known-good value, Save.
3. Click Run Now: toast "Timesheet submitted for WK-XX/YYYY" within ~30 s; Last updated.
4. Click Run Now again: toast "Timesheet skipped" (already submitted this week) — unless Force is on.
5. Set `exec_time` to 1 minute ahead, enable; verify scheduled fire works.
6. Disable in tray; verify schedule cleared (next minute does NOT fire).
7. Bad password: toast "Timesheet failed".
