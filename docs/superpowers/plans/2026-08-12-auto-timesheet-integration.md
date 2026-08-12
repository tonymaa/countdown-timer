# Auto Timesheet Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the standalone `auto_timesheet_python/main.py` into the countdown-timer app as an importable module with tray-configurable params, daily schedule, and manual trigger.

**Architecture:** Copy the script as `auto_timesheet.py` with minimal, surgical modifications (configurable debug output dir, configurable logging). In `main.py`, extend the existing `config.cof` schema with a `timesheet` sub-key, add a tray submenu, a settings dialog, and wire execution into the existing `schedule`-based loop.

**Tech Stack:** Python 3.10+, Tkinter (existing), pystray (existing), `schedule` (existing), `requests` (new dep — comes from the script).

## Global Constraints

- Working directory: `E:\python_project\countdown-timer`
- Shell on Windows is bash (Unix syntax — forward slashes, `/dev/null` not `NUL`).
- All paths in code must work when the app is launched from any CWD. Use `os.path.dirname(os.path.abspath(__file__))` for the app's own directory.
- No new third-party deps beyond what `auto_timesheet.py` already requires (`requests`, `urllib3`). Add `requests` to a new `requirements.txt` if missing.
- Config schema additions live under `config["timesheet"]` per the spec.
- No automated tests (matches existing project scope). Each task ends with a manual smoke check.
- Commit after every task. Conventional commit format: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
- Do NOT skip hooks (`--no-verify`) — none are configured, but principle holds.
- The script's standalone CLI in its `__main__` block must remain functional after each modification.

---

## File Structure

```
countdown-timer/
├── main.py                       # MODIFY — tray submenu, scheduler hook, settings dialog
├── auto_timesheet.py             # CREATE — copy + adapt from source
├── toppan-ca-bundle.pem          # CREATE — copy verbatim from source
├── requirements.txt              # CREATE — pin requests, urllib3, etc. (matches existing runtime)
├── timesheet_debug/              # AUTO-CREATED at runtime
│   ├── *.html                    # debug HTML dumps from script
│   └── timesheet.log             # rotating log
└── docs/superpowers/specs/2026-08-12-auto-timesheet-integration-design.md  # existing spec
```

`main.py` is currently ~500 lines in a single `App` class with all logic inline. We will extend that class — no refactor — to keep diff size small and avoid touching the timer logic. If a clean separation is desired later, a follow-up could extract the timesheet feature into its own module; that is explicitly out of scope here.

---

## Task 1: Copy and adapt `auto_timesheet.py`

**Files:**
- Create: `E:\python_project\countdown-timer\auto_timesheet.py`
- Create: `E:\python_project\countdown-timer\toppan-ca-bundle.pem`
- Create: `E:\python_project\countdown-timer\requirements.txt`

**Interfaces:**
- Produces: `auto_timesheet.submit_timesheet(config: TimesheetConfig, force_submit: bool = False, debug_dir: str | None = None) -> TimesheetResult`
- Produces: `auto_timesheet.TimesheetConfig(username: str, password: str, project: str, task: str, hours_per_day: int = 8, verify_tls: Union[bool, str] = False)`
- Produces: `auto_timesheet.TimesheetResult(success: bool, message: str, week: str)`
- Produces: `auto_timesheet.configure_logging(log_path: Path | None = None, level: str = "INFO") -> None`

- [ ] **Step 1: Copy the script and CA bundle**

```bash
cp "E:/project/private_user_scripts/auto_timesheet_python/main.py" "E:/python_project/countdown-timer/auto_timesheet.py"
cp "E:/project/private_user_scripts/auto_timesheet_python/toppan-ca-bundle.pem" "E:/python_project/countdown-timer/toppan-ca-bundle.pem"
```

- [ ] **Step 2: Verify both files landed**

```bash
ls -la "E:/python_project/countdown-timer/auto_timesheet.py" "E:/python_project/countdown-timer/toppan-ca-bundle.pem"
```

Expected: both listed with non-zero size.

- [ ] **Step 3: Create `requirements.txt`**

Write `E:\python_project\countdown-timer\requirements.txt`:

```
requests>=2.31.0
urllib3>=2.0.0
pystray>=0.19.5
Pillow>=10.0.0
schedule>=1.2.0
pywin32>=306
```

- [ ] **Step 4: In `auto_timesheet.py`, replace the module-level logging config with a `configure_logging` helper**

Find (top of file, around lines 20-25):

```python
# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
```

Replace with:

```python
# 日志配置延迟到 configure_logging() 被调用时才设置 handler。
# 模块 import 时不做任何 logging 配置 — 由 host 应用 (main.py) 显式调用。
# 如果 host 不调用 (例如直接 CLI 运行), __main__ 块会调用 configure_logging() 走默认配置。
logger = logging.getLogger(__name__)
_LOGGING_CONFIGURED = False


def configure_logging(
    log_path: "Path | None" = None,
    level: str = "INFO",
) -> None:
    """
    为 auto_timesheet 模块配置 root logger。

    Args:
        log_path: 日志文件路径。为 None 时只输出到 stderr。
                  传入路径会自动创建父目录并使用 RotatingFileHandler
                  (max 1 MB, 3 backups)。
        level: "DEBUG" / "INFO" / "WARNING" / "ERROR"
    """
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    _LOGGING_CONFIGURED = True

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    if log_path is not None:
        from logging.handlers import RotatingFileHandler
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(log_path), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
```

- [ ] **Step 5: Add `debug_dir` param to `TimesheetSession.__init__`**

Find (around line 41-49):

```python
    def __init__(
        self,
        username: str = "zhiming",
        password: str = "password$1",
        project: str = "PD_AGP",
        task: str = "Prodt Devt",
        delay: float = 1.0,
        verify_tls: Union[bool, str] = False,
    ):
        self.username = username
        self.password = password
        self.project = project
        self.task = task
        self.delay = delay
        self.verify_tls = verify_tls
```

Replace with:

```python
    def __init__(
        self,
        username: str = "zhiming",
        password: str = "password$1",
        project: str = "PD_AGP",
        task: str = "Prodt Devt",
        delay: float = 1.0,
        verify_tls: Union[bool, str] = False,
        debug_dir: "str | None" = None,
    ):
        self.username = username
        self.password = password
        self.project = project
        self.task = task
        self.delay = delay
        self.verify_tls = verify_tls
        # debug_dir 为 None 时, _save_debug_html 写入 CWD (向后兼容旧行为)。
        # 设置后, 所有 *.html 调试文件会写入该目录 (lazy 创建)。
        self.debug_dir = debug_dir
```

- [ ] **Step 6: Modify `_save_debug_html` to honor `debug_dir`**

Find (around line 97-104):

```python
    def _save_debug_html(self, filename: str, content: str) -> None:
        """保存 HTML 响应到文件,便于事后分析。"""
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
            logger.debug(f"Saved HTML ({len(content)} bytes) -> {filename}")
        except OSError as e:
            logger.warning(f"Failed to save {filename}: {e}")
```

Replace with:

```python
    def _save_debug_html(self, filename: str, content: str) -> None:
        """保存 HTML 响应到文件,便于事后分析。"""
        try:
            if self.debug_dir:
                import os
                os.makedirs(self.debug_dir, exist_ok=True)
                out_path = os.path.join(self.debug_dir, filename)
            else:
                out_path = filename
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.debug(f"Saved HTML ({len(content)} bytes) -> {out_path}")
        except OSError as e:
            logger.warning(f"Failed to save {filename}: {e}")
```

- [ ] **Step 7: Add `debug_dir` kwarg to `submit_timesheet`**

Find (around line 700-718):

```python
def submit_timesheet(config: TimesheetConfig, force_submit: bool = False) -> TimesheetResult:
    """
    提交时间表的便捷函数

    Args:
        config: 时间表配置
        force_submit: 即使当周已提交/已保存也强制重新提交

    Returns:
        TimesheetResult: 提交结果
    """
    session = TimesheetSession(
        username=config.username,
        password=config.password,
        project=config.project,
        task=config.task,
        verify_tls=config.verify_tls,
    )
```

Replace with:

```python
def submit_timesheet(
    config: TimesheetConfig,
    force_submit: bool = False,
    debug_dir: "str | None" = None,
) -> TimesheetResult:
    """
    提交时间表的便捷函数

    Args:
        config: 时间表配置
        force_submit: 即使当周已提交/已保存也强制重新提交
        debug_dir: 调试 HTML 文件输出目录; None = 写入 CWD (向后兼容)

    Returns:
        TimesheetResult: 提交结果
    """
    session = TimesheetSession(
        username=config.username,
        password=config.password,
        project=config.project,
        task=config.task,
        verify_tls=config.verify_tls,
        debug_dir=debug_dir,
    )
```

- [ ] **Step 8: Update `__main__` block to call `configure_logging`**

Find (around line 744-797, the `if __name__ == "__main__":` block) and add `configure_logging()` at the top of it. After `import argparse`:

```python
if __name__ == "__main__":
    import argparse

    # CLI 运行时使用默认 stderr-only 配置 (没有日志文件)
    configure_logging(level="INFO")
```

Then at the bottom where the level is reset (around line 794-796), keep the existing level override:

```python
    logging.getLogger().setLevel(logging.DEBUG if args.verbose else logging.INFO)
    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)
```

This is fine — `configure_logging` is idempotent via the `_LOGGING_CONFIGURED` flag, and `setLevel` after it adjusts the level correctly.

- [ ] **Step 9: Verify the script imports cleanly**

Run:

```bash
cd "E:/python_project/countdown-timer" && python -c "from auto_timesheet import submit_timesheet, TimesheetConfig, TimesheetResult, configure_logging; print('OK')"
```

Expected: prints `OK`, no traceback.

- [ ] **Step 10: Verify the script's standalone CLI still works**

Run:

```bash
cd "E:/python_project/countdown-timer" && python auto_timesheet.py --help
```

Expected: argparse usage output, exit code 0.

- [ ] **Step 11: Commit**

```bash
cd "E:/python_project/countdown-timer"
git add auto_timesheet.py toppan-ca-bundle.pem requirements.txt
git commit -m "feat: import auto_timesheet module and CA bundle"
```

---

## Task 2: Add `timesheet` config migration and `_reschedule_timesheet` skeleton in `main.py`

**Files:**
- Modify: `E:\python_project\countdown-timer\main.py`

**Interfaces:**
- Produces: `App._get_default_timesheet_config() -> dict` — default timesheet config block
- Produces: `App._init_timesheet_config() -> None` — merges defaults into `self.config["timesheet"]`
- Produces: `App._reschedule_timesheet() -> None` — clears tag `"timesheet"`, schedules if enabled
- Produces: module-level `TIMESHEET_DEBUG_DIR: str` — absolute path to `timesheet_debug/` next to `main.py`

- [ ] **Step 1: Add module-level constants and import**

In `main.py`, find the import block at the top (lines 1-16) and add after `import win32gui`:

```python
from pathlib import Path
from auto_timesheet import submit_timesheet, TimesheetConfig, configure_logging

# 计时器程序所在目录 — 用于解析 ca_bundle 等相对路径
APP_DIR = os.path.dirname(os.path.abspath(__file__))
TIMESHEET_DEBUG_DIR = os.path.join(APP_DIR, "timesheet_debug")
```

- [ ] **Step 2: Add default config helper**

In the `App` class, find `get_default_config` (around line 82). Add a new method right after it:

```python
    def _get_default_timesheet_config(self):
        return {
            "enabled": False,
            "username": "zhiming",
            "password": "password$1",
            "project": "PD_AGP",
            "task": "Prodt Devt",
            "hours": 8,
            "exec_time": "09:05",
            "force_submit": False,
            "ca_bundle": "toppan-ca-bundle.pem",
            "last_run": None,
            "last_result": None,
        }
```

- [ ] **Step 3: Add merge helper**

Right after `_get_default_timesheet_config`, add:

```python
    def _init_timesheet_config(self):
        """首次启动或老 config.cof 缺少 timesheet 段时,用默认值补齐字段。"""
        defaults = self._get_default_timesheet_config()
        current = self.config.get("timesheet", {})
        merged = {**defaults, **current}
        # 类型修正: 防止历史配置里 hours 是字符串
        try:
            merged["hours"] = int(merged.get("hours", 8))
        except (TypeError, ValueError):
            merged["hours"] = 8
        self.config["timesheet"] = merged
        self.save_config(self.config)
```

- [ ] **Step 4: Call `_init_timesheet_config` in `__init__`**

In `__init__` (lines 19-43), find:

```python
    def __init__(self):
        self.config = self.read_config()
        self.window_width = 140
        self.window_height = 27
        self.init_pos()
        self.init_url()
        self.init_alpha()
```

Add `_init_timesheet_config` call after `init_alpha`:

```python
    def __init__(self):
        self.config = self.read_config()
        self.window_width = 140
        self.window_height = 27
        self.init_pos()
        self.init_url()
        self.init_alpha()
        self._init_timesheet_config()
        # timesheet 运行状态
        self._timesheet_running = False
```

- [ ] **Step 5: Configure logging in `__init__`**

In `__init__`, after the work_countdown state restoration block (around lines 36-42), and before `self.run_app()`, add:

```python
        # 配置 auto_timesheet 模块的日志输出
        configure_logging(
            log_path=Path(TIMESHEET_DEBUG_DIR) / "timesheet.log",
            level="INFO",
        )
```

- [ ] **Step 6: Add `_reschedule_timesheet` method**

Find `set_one_new_schedule` (around line 290). Add a new method after it:

```python
    def _reschedule_timesheet(self):
        """根据 config.timesheet.enabled 重新调度 timesheet 任务。"""
        schedule.clear("timesheet")
        ts_cfg = self.config.get("timesheet", {})
        if not ts_cfg.get("enabled", False):
            return
        exec_time = ts_cfg.get("exec_time", "09:05")
        try:
            datetime.datetime.strptime(exec_time, "%H:%M")
        except ValueError:
            logger_warn = f"Invalid exec_time {exec_time!r}, falling back to 09:05"
            print(logger_warn)
            exec_time = "09:05"
            ts_cfg["exec_time"] = exec_time
            self.save_config(self.config)
        schedule.every().day.at(exec_time).do(
            self._run_timesheet_async, force=False
        ).tag("timesheet")
```

- [ ] **Step 7: Call `_reschedule_timesheet` from `start_schedule`**

Find `start_schedule` (around line 281):

```python
    def start_schedule(self):
        if self.work_countdown_enabled:
            self._schedule_work_screen_off()
        else:
            self.set_one_new_schedule()
        thread = threading.Thread(target=self.run_task)
        thread.setDaemon(True)
        thread.start()
```

Add `_reschedule_timesheet()` before the thread start:

```python
    def start_schedule(self):
        if self.work_countdown_enabled:
            self._schedule_work_screen_off()
        else:
            self.set_one_new_schedule()
        self._reschedule_timesheet()
        thread = threading.Thread(target=self.run_task)
        thread.setDaemon(True)
        thread.start()
```

- [ ] **Step 8: Smoke check**

Run:

```bash
cd "E:/python_project/countdown-timer" && python -c "
import main
print('App class imports OK')
print('Has _reschedule_timesheet:', hasattr(main.App, '_reschedule_timesheet'))
print('Has _init_timesheet_config:', hasattr(main.App, '_init_timesheet_config'))
"
```

Expected: both `True`, no errors. (The script won't actually instantiate App because `app = App()` is at module level — wait, it IS at module level. So importing `main` will launch the GUI. Better to do a syntax-check instead.)

Substitute with:

```bash
cd "E:/python_project/countdown-timer" && python -m py_compile main.py && echo "compile OK"
```

Expected: prints `compile OK`, exit code 0.

- [ ] **Step 9: Verify config.cof gains `timesheet` key**

Back up current config:

```bash
cp "E:/python_project/countdown-timer/config.cof" "E:/python_project/countdown-timer/config.cof.bak"
```

Launch the app briefly and quit (use a timeout to auto-kill it):

```bash
cd "E:/python_project/countdown-timer" && timeout 5 python main.py || true
```

Then check the config:

```bash
python -c "import json; c=json.load(open('E:/python_project/countdown-timer/config.cof')); print('timesheet key present:', 'timesheet' in c); print(json.dumps(c.get('timesheet'), indent=2))"
```

Expected: `timesheet key present: True` and a JSON object with all 11 default fields.

Restore the previous config if you want to keep test isolated:

```bash
mv "E:/python_project/countdown-timer/config.cof.bak" "E:/python_project/countdown-timer/config.cof"
```

(Or keep it — the migration is meant to be permanent.)

- [ ] **Step 10: Commit**

```bash
cd "E:/python_project/countdown-timer"
git add main.py
git commit -m "feat: add timesheet config migration and scheduler hook"
```

---

## Task 3: Add execution flow (`_run_timesheet_async`, `_build_timesheet_config`, `_on_timesheet_done`)

**Files:**
- Modify: `E:\python_project\countdown-timer\main.py`

**Interfaces:**
- Produces: `App._build_timesheet_config() -> TimesheetConfig` — reads `self.config["timesheet"]`, resolves CA bundle path
- Produces: `App._run_timesheet_async(force: bool = False) -> None` — non-blocking entry, spawns daemon thread
- Produces: `App._run_timesheet_sync(force: bool) -> None` — actual `submit_timesheet` call
- Produces: `App._on_timesheet_done(action: str, message: str, week: str) -> None` — persist last_run/last_result + toast

- [ ] **Step 1: Add `_build_timesheet_config`**

In `main.py`, right after `_reschedule_timesheet` (added in Task 2), add:

```python
    def _build_timesheet_config(self):
        """从 self.config["timesheet"] 构造 TimesheetConfig,解析 ca_bundle 路径。"""
        ts = self.config["timesheet"]
        ca_bundle = ts.get("ca_bundle", "").strip()

        if not ca_bundle:
            verify_tls = False
        else:
            # 相对路径相对于 APP_DIR 解析
            abs_path = ca_bundle if os.path.isabs(ca_bundle) else os.path.join(APP_DIR, ca_bundle)
            if os.path.isfile(abs_path):
                verify_tls = abs_path
            else:
                print(f"[timesheet] CA bundle not found at {abs_path}, falling back to TLS OFF")
                verify_tls = False

        return TimesheetConfig(
            username=ts.get("username", ""),
            password=ts.get("password", ""),
            project=ts.get("project", ""),
            task=ts.get("task", ""),
            hours_per_day=int(ts.get("hours", 8) or 8),
            verify_tls=verify_tls,
        )
```

- [ ] **Step 2: Add `_run_timesheet_async` and `_run_timesheet_sync`**

Right after `_build_timesheet_config`, add:

```python
    def _run_timesheet_async(self, force: bool = False):
        """非阻塞入口: 防止重复触发,然后丢给后台线程。"""
        if self._timesheet_running:
            print("[timesheet] already running, skipping")
            return
        self._timesheet_running = True
        thread = threading.Thread(target=self._run_timesheet_sync, args=(force,), daemon=True)
        thread.start()

    def _run_timesheet_sync(self, force: bool):
        """实际执行 submit_timesheet; 在 daemon thread 中跑。"""
        ts = self.config["timesheet"]
        try:
            cfg = self._build_timesheet_config()
            result = submit_timesheet(
                cfg,
                force_submit=bool(force or ts.get("force_submit", False)),
                debug_dir=TIMESHEET_DEBUG_DIR,
            )
            msg_lower = result.message.lower()
            if not result.success:
                action = "failed"
            elif "skipped" in msg_lower:
                action = "skipped"
            else:
                action = "submitted"
            self._on_timesheet_done(action, result.message, result.week)
        except Exception as e:
            self._on_timesheet_done("failed", f"Exception: {e}", "")
        finally:
            self._timesheet_running = False
```

- [ ] **Step 3: Add `_on_timesheet_done`**

Right after `_run_timesheet_sync`, add:

```python
    def _on_timesheet_done(self, action: str, message: str, week: str):
        """更新 last_run/last_result 到 config,弹出 toast 提示。"""
        ts = self.config.setdefault("timesheet", {})
        ts["last_run"] = datetime.datetime.now().isoformat()
        ts["last_result"] = action
        self.save_config(self.config)

        title_map = {
            "submitted": "Timesheet submitted",
            "skipped": "Timesheet skipped",
            "failed": "Timesheet failed",
        }
        title = title_map.get(action, "Timesheet")
        body = f"{week}: {message}" if week else message
        try:
            self._show_toast(title, body)
        except Exception as e:
            print(f"[timesheet] toast failed: {e}")
```

- [ ] **Step 4: Smoke check**

```bash
cd "E:/python_project/countdown-timer" && python -m py_compile main.py && echo "compile OK"
```

Expected: `compile OK`, exit code 0.

- [ ] **Step 5: Commit**

```bash
cd "E:/python_project/countdown-timer"
git add main.py
git commit -m "feat: implement timesheet run flow and result handling"
```

---

## Task 4: Add tray submenu structure

**Files:**
- Modify: `E:\python_project\countdown-timer\main.py`

**Interfaces:**
- Produces: tray submenu `"Auto Timesheet"` with four items (Enabled, Settings..., Run Now, Last)
- Consumes: `App._run_timesheet_async` (Task 3), `App._open_timesheet_settings` (added in Task 5), `App._toggle_timesheet_enabled` (added in this task)

- [ ] **Step 1: Add toggle handler and dynamic-text helpers**

In `main.py`, right after `_on_timesheet_done`, add:

```python
    def _toggle_timesheet_enabled(self):
        ts = self.config.setdefault("timesheet", {})
        ts["enabled"] = not ts.get("enabled", False)
        self.save_config(self.config)
        self._reschedule_timesheet()

    def _timesheet_last_label(self):
        """生成托盘菜单中 'Last' 项的显示文本。"""
        ts = self.config.get("timesheet", {})
        last_run = ts.get("last_run")
        last_result = ts.get("last_result")
        if not last_run:
            return "Last: (never)"
        try:
            dt = datetime.datetime.fromisoformat(last_run)
            when = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            when = last_run
        return f"Last: {when} — {last_result or 'unknown'}"
```

- [ ] **Step 2: Insert the submenu into the existing tray menu**

Find the existing `pystray.Menu(...)` construction inside `create_window` (lines 184-198):

```python
        self.menu = pystray.Menu(
            pystray.MenuItem("打开浏览器", self.open_browser),
            pystray.MenuItem("显示计时器", action=self.display_timer, checked=lambda e: self.is_show_timer_label),
            pystray.MenuItem("切换模式", pystray.Menu(
                pystray.MenuItem("目标时间倒计时", action=self.switch_to_target_mode, checked=lambda e: not self.work_countdown_enabled),
                pystray.MenuItem("上班倒计时", action=self.switch_to_work_mode, checked=lambda e: self.work_countdown_enabled),
            )),
            pystray.MenuItem("修改计时器", action=self.set_target_time, visible=lambda e: not self.work_countdown_enabled),
            pystray.MenuItem("立即倒计时9小时", action=self.reset_work_countdown, visible=lambda e: self.work_countdown_enabled),
            pystray.MenuItem("选择字体颜色", action=self.choose_color),
            pystray.MenuItem("调整字体透明度", action=self.adjust_alpha),
            pystray.MenuItem("调整窗口位置", action=self.move_time_label, checked=lambda e: self.is_able_move),
            pystray.MenuItem("初始化窗口位置", action=self.reset_window_pos),
            pystray.MenuItem("退出", self.stop)
        )
```

Replace with:

```python
        self.menu = pystray.Menu(
            pystray.MenuItem("打开浏览器", self.open_browser),
            pystray.MenuItem("显示计时器", action=self.display_timer, checked=lambda e: self.is_show_timer_label),
            pystray.MenuItem("切换模式", pystray.Menu(
                pystray.MenuItem("目标时间倒计时", action=self.switch_to_target_mode, checked=lambda e: not self.work_countdown_enabled),
                pystray.MenuItem("上班倒计时", action=self.switch_to_work_mode, checked=lambda e: self.work_countdown_enabled),
            )),
            pystray.MenuItem("修改计时器", action=self.set_target_time, visible=lambda e: not self.work_countdown_enabled),
            pystray.MenuItem("立即倒计时9小时", action=self.reset_work_countdown, visible=lambda e: self.work_countdown_enabled),
            pystray.MenuItem("选择字体颜色", action=self.choose_color),
            pystray.MenuItem("调整字体透明度", action=self.adjust_alpha),
            pystray.MenuItem("调整窗口位置", action=self.move_time_label, checked=lambda e: self.is_able_move),
            pystray.MenuItem("初始化窗口位置", action=self.reset_window_pos),
            pystray.MenuItem("Auto Timesheet", pystray.Menu(
                pystray.MenuItem(
                    "Enabled",
                    action=lambda *_: self._toggle_timesheet_enabled(),
                    checked=lambda e: bool(self.config.get("timesheet", {}).get("enabled", False)),
                ),
                pystray.MenuItem("Settings...", action=lambda *_: self._open_timesheet_settings()),
                pystray.MenuItem(
                    "Run Now",
                    action=lambda *_: self._run_timesheet_async(force=False),
                    enabled=lambda e: not self._timesheet_running,
                ),
                pystray.MenuItem(
                    text=lambda e: self._timesheet_last_label(),
                    action=None,
                ),
            )),
            pystray.MenuItem("退出", self.stop)
        )
```

- [ ] **Step 3: Add stub `_open_timesheet_settings` (Task 5 fills it in)**

Right after `_timesheet_last_label`, add a temporary stub so the menu wiring works:

```python
    def _open_timesheet_settings(self):
        """Placeholder — implemented in Task 5."""
        print("[timesheet] settings dialog not implemented yet")
```

- [ ] **Step 4: Smoke check**

```bash
cd "E:/python_project/countdown-timer" && python -m py_compile main.py && echo "compile OK"
```

Expected: `compile OK`, exit code 0.

Then launch the app and verify the tray menu shows the new "Auto Timesheet" submenu with the four items. Toggle Enabled on and off; click "Run Now" (it will attempt a real submission if credentials are filled — see Task 5 for safer testing). Right-click → Last should show `Last: (never)` on first run.

```bash
cd "E:/python_project/countdown-timer" && timeout 5 python main.py || true
```

(Visually verify the menu; quit via the "退出" item before the timeout fires.)

- [ ] **Step 5: Commit**

```bash
cd "E:/python_project/countdown-timer"
git add main.py
git commit -m "feat: add Auto Timesheet tray submenu"
```

---

## Task 5: Implement Settings dialog

**Files:**
- Modify: `E:\python_project\countdown-timer\main.py`

**Interfaces:**
- Produces: `App._open_timesheet_settings() -> None` — opens Toplevel, fields bound to current config, Save triggers `_reschedule_timesheet()`

- [ ] **Step 1: Replace the stub with the full dialog implementation**

In `main.py`, find the stub `_open_timesheet_settings` (added in Task 4 Step 3) and replace it entirely:

```python
    def _open_timesheet_settings(self):
        """打开 Auto Timesheet 设置对话框。"""
        ts = dict(self.config.get("timesheet", {}))  # shallow copy for editing

        top = tk.Toplevel(self.window)
        top.title("Auto Timesheet Settings")
        top.geometry("420x340")
        top.resizable(False, False)
        top.transient(self.window)

        # ---- variables ----
        v_username = tk.StringVar(value=ts.get("username", ""))
        v_password = tk.StringVar(value=ts.get("password", ""))
        v_project = tk.StringVar(value=ts.get("project", ""))
        v_task = tk.StringVar(value=ts.get("task", ""))
        v_hours = tk.IntVar(value=int(ts.get("hours", 8) or 8))
        exec_time = ts.get("exec_time", "09:05")
        try:
            hh_str, mm_str = exec_time.split(":", 1)
        except ValueError:
            hh_str, mm_str = "09", "05"
        v_hh = tk.StringVar(value=hh_str)
        v_mm = tk.StringVar(value=mm_str)
        v_cabundle = tk.StringVar(value=ts.get("ca_bundle", "toppan-ca-bundle.pem"))
        v_force = tk.BooleanVar(value=bool(ts.get("force_submit", False)))

        # ---- form grid ----
        row = 0
        def label(text):
            return tk.Label(top, text=text, anchor="e", width=12)

        label("Username:").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        tk.Entry(top, textvariable=v_username, width=32).grid(row=row, column=1, columnspan=2, sticky="w", padx=4)
        row += 1

        label("Password:").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        tk.Entry(top, textvariable=v_password, width=32, show="*").grid(row=row, column=1, columnspan=2, sticky="w", padx=4)
        row += 1

        label("Project:").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        tk.Entry(top, textvariable=v_project, width=32).grid(row=row, column=1, columnspan=2, sticky="w", padx=4)
        row += 1

        label("Task:").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        tk.Entry(top, textvariable=v_task, width=32).grid(row=row, column=1, columnspan=2, sticky="w", padx=4)
        row += 1

        label("Hours/day:").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        tk.Spinbox(top, from_=1, to=12, textvariable=v_hours, width=5).grid(row=row, column=1, sticky="w", padx=4)
        row += 1

        label("Exec time:").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        time_frame = tk.Frame(top)
        time_frame.grid(row=row, column=1, columnspan=2, sticky="w", padx=4)
        tk.Entry(time_frame, textvariable=v_hh, width=4).pack(side="left")
        tk.Label(time_frame, text=" : ").pack(side="left")
        tk.Entry(time_frame, textvariable=v_mm, width=4).pack(side="left")
        tk.Label(time_frame, text="(HH:MM 24h)").pack(side="left", padx=(8, 0))
        row += 1

        label("CA bundle:").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        ca_frame = tk.Frame(top)
        ca_frame.grid(row=row, column=1, columnspan=2, sticky="ew", padx=4)
        tk.Entry(ca_frame, textvariable=v_cabundle, width=28).pack(side="left")
        def browse_ca():
            picked = tk.filedialog.askopenfilename(
                parent=top,
                title="Select CA bundle",
                filetypes=[("PEM/CRT", "*.pem *.crt"), ("All files", "*.*")],
            )
            if picked:
                v_cabundle.set(picked)
        tk.Button(ca_frame, text="Browse...", command=browse_ca).pack(side="left", padx=4)
        row += 1

        tk.Checkbutton(top, text="Force re-submit even if week already saved", variable=v_force).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=4, pady=4
        )
        row += 1

        # ---- action buttons ----
        btn_frame = tk.Frame(top)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=10)

        def save():
            try:
                hh = int(v_hh.get())
                mm = int(v_mm.get())
                if not (0 <= hh <= 23 and 0 <= mm <= 59):
                    raise ValueError("time out of range")
            except ValueError:
                tk.messagebox.showerror("Error", f"Invalid exec time: HH={v_hh.get()!r} MM={v_mm.get()!r}", parent=top)
                return
            try:
                hours = int(v_hours.get())
            except (tk.TclError, ValueError):
                tk.messagebox.showerror("Error", "Hours must be an integer 1-12", parent=top)
                return
            if not (1 <= hours <= 12):
                tk.messagebox.showerror("Error", "Hours must be 1-12", parent=top)
                return
            username = v_username.get().strip()
            project = v_project.get().strip()
            task = v_task.get().strip()
            if not (username and project and task):
                tk.messagebox.showerror("Error", "Username, Project, Task must not be empty", parent=top)
                return

            ca_bundle_raw = v_cabundle.get().strip()
            # 若用户选了 APP_DIR 内的文件, 存为相对路径
            if ca_bundle_raw and os.path.isabs(ca_bundle_raw):
                try:
                    rel = os.path.relpath(ca_bundle_raw, APP_DIR)
                    if not rel.startswith(".."):
                        ca_bundle_raw = rel
                except ValueError:
                    pass

            new_ts = {
                "enabled": ts.get("enabled", False),  # 保留原值, 不在对话框里切换
                "username": username,
                "password": v_password.get(),
                "project": project,
                "task": task,
                "hours": hours,
                "exec_time": f"{hh:02d}:{mm:02d}",
                "force_submit": bool(v_force.get()),
                "ca_bundle": ca_bundle_raw,
                "last_run": ts.get("last_run"),
                "last_result": ts.get("last_result"),
            }
            self.config["timesheet"] = new_ts
            self.save_config(self.config)
            self._reschedule_timesheet()
            top.destroy()

        tk.Button(btn_frame, text="Save", width=10, command=save).pack(side="left", padx=8)
        tk.Button(btn_frame, text="Cancel", width=10, command=top.destroy).pack(side="left", padx=8)

        top.grab_release()  # 不要 grab, 否则会阻塞 timer 主窗口交互
```

- [ ] **Step 2: Ensure `tk.filedialog` and `tk.messagebox` are imported**

Check the top of `main.py`. The existing code uses `from tkinter import messagebox, colorchooser, Scale, Frame, YES, BOTH` — so `messagebox` is already in scope as `tk.messagebox`. For `filedialog`, add an explicit import at the top of the file after the existing tkinter imports:

```python
from tkinter import filedialog
```

And update the `browse_ca` callback to call `filedialog.askopenfilename(...)` (no `tk.` prefix). Equivalently, change the dialog code to use `tk.filedialog` and add `import tkinter.filedialog` after `import tkinter as tk`. Pick whichever is consistent with existing style — the existing code uses `tk.messagebox`, so for consistency use `tk.filedialog` and add `import tkinter.filedialog` once near the top.

In the implementation above I used `tk.filedialog.askopenfilename(...)` — make sure `import tkinter.filedialog` (or `import tkinter as tk` already covers it; it does in standard CPython). Verify with a quick compile check in Step 4.

- [ ] **Step 3: Smoke check**

```bash
cd "E:/python_project/countdown-timer" && python -m py_compile main.py && echo "compile OK"
```

Expected: `compile OK`.

- [ ] **Step 4: End-to-end manual test**

Launch the app:

```bash
cd "E:/python_project/countdown-timer" && python main.py &
```

In the tray menu: Auto Timesheet → Settings...

1. Verify the dialog opens with all fields populated from defaults.
2. Change `Hours/day` to `9` and `Exec time` to `09:30`. Save.
3. Verify `config.cof` reflects the change:

```bash
python -c "import json; c=json.load(open('E:/python_project/countdown-timer/config.cof')); print(json.dumps(c['timesheet'], indent=2))"
```

Expected: `"hours": 9`, `"exec_time": "09:30"`.

4. Re-open Settings — verify the saved values are loaded.
5. Try validation: enter `99` for hours → Save → expect error dialog.
6. Try validation: clear Username → Save → expect error dialog.
7. Browse button: pick `toppan-ca-bundle.pem` from the countdown-timer dir → Save → verify it's stored as a relative path (`"toppan-ca-bundle.pem"`).
8. Click "Run Now" in the tray. Within ~30s expect a toast notification. Verify `timesheet_debug/` now contains HTML files and `timesheet.log`.

- [ ] **Step 5: Commit**

```bash
cd "E:/python_project/countdown-timer"
git add main.py
git commit -m "feat: implement Auto Timesheet settings dialog"
```

---

## Task 6: Final verification and doc touch-ups

**Files:**
- Read-only: `E:\python_project\countdown-timer\config.cof`, `E:\python_project\countdown-timer\timesheet_debug\*`

- [ ] **Step 1: Schedule-fire test**

Open Settings, set `exec_time` to a time 2 minutes in the future. Toggle Enabled on. Wait. Verify:

- Toast notification fires at the scheduled minute.
- `config.cof` `last_run` and `last_result` updated.
- `timesheet_debug/timesheet.log` has new lines.

- [ ] **Step 2: Disabled-schedule test**

Toggle Enabled off in the tray. Wait past the scheduled time. Verify no toast fires (and `last_run` unchanged).

- [ ] **Step 3: Failure-path test**

Temporarily change Username to garbage in Settings, Save, click Run Now. Verify toast says "Timesheet failed" with the error message. Verify `last_result` = `"failed"` in `config.cof`. Restore the username.

- [ ] **Step 4: README touch-up (optional)**

If `README.md` exists and documents features, add a short "Auto Timesheet" section describing:

- The tray submenu.
- Where debug files go.
- The CA bundle file.

Skip if README is minimal/placeholder.

- [ ] **Step 5: Final commit**

```bash
cd "E:/python_project/countdown-timer"
git add README.md  # only if touched
git commit -m "docs: note auto timesheet feature" || echo "no README changes"
```

---

## Self-Review Notes

- **Spec coverage:**
  - Config schema (11 fields) → Task 2 Step 2, Task 5 Step 1.
  - Tray submenu (4 items) → Task 4 Step 2.
  - Settings dialog (all fields, validation, browse) → Task 5 Step 1.
  - `_reschedule_timesheet` → Task 2 Step 6.
  - `_run_timesheet_async` / `_build_timesheet_config` / `_on_timesheet_done` → Task 3.
  - `configure_logging` + `timesheet_debug/timesheet.log` → Task 1 Step 4, Task 2 Step 5.
  - CA bundle handling (relative path, fallback to TLS OFF) → Task 3 Step 1.
  - Debug HTML redirect to subdir → Task 1 Step 6.
  - Manual smoke tests for each scenario → Task 6.

- **No placeholders.** Each step contains exact code, exact commands, expected outputs.

- **Type/name consistency:** `submit_timesheet(config, force_submit, debug_dir)`, `TimesheetConfig`, `configure_logging(log_path, level)` — all match across Task 1 (definition) and Task 3 (consumption). `_timesheet_running`, `_reschedule_timesheet`, `_init_timesheet_config`, `_build_timesheet_config`, `_run_timesheet_async`, `_run_timesheet_sync`, `_on_timesheet_done`, `_open_timesheet_settings`, `_toggle_timesheet_enabled`, `_timesheet_last_label` — consistent across Tasks 2-5.

- **Scope check:** Six tasks, each producing a testable deliverable, fits one implementation cycle.
