"""
Toppan Timesheet Auto-submit using HTTP Requests
使用 Python requests 库自动提交时间表
"""
import logging
import os
import random
import re
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NamedTuple, Union

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

# Windows 上 socket.getaddrinfo (DNS 解析) 不受 requests timeout 控制
# 可能无限挂起。设置全局默认 socket 超时作为底线。
socket.setdefaulttimeout(30)


class TimesheetSession:
    """Toppan 时间表 HTTP 会话"""

    BASE_URL = "https://intranet.toppanecquaria.com"
    LOGIN_URL = f"{BASE_URL}/sop/workdesk/login.jsp"
    LOGIN_POST_URL = f"{BASE_URL}/sop/LoginHandler"
    TIMESHEET_URL = f"{BASE_URL}/sop/forwarder.jsp?url=/WebPageHandler?p=TimesheetPrj&pn=SubmitTimesheet&ecbeans.SOP_THIS_UB=public"
    SUBMIT_URL = f"{BASE_URL}/sop/WebPageHandler"

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
        self.last_action: str = "init"  # init | submitted | skipped | failed

        # 创建 session 并配置重试
        self.session = requests.Session()
        # 内网通常使用自签名 / 内部 CA 证书,默认关闭 TLS 校验
        # (可通过 verify_tls=True 或传入 CA bundle 路径重新启用)
        self.session.verify = verify_tls
        if not verify_tls:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            backoff_jitter=2,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # 设置请求头
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

        self.is_logged_in = False
        self.jsessionid: str | None = None

        logger.info("TimesheetSession initialized")

    def close(self) -> None:
        """关闭会话"""
        if self.session:
            self.session.close()
            logger.info("Session closed")

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

    @staticmethod
    def _parse_hidden_inputs(html: str) -> dict[str, str]:
        """Extract all <input type=hidden> fields from an HTML form.

        Returns a dict mapping field name → value. Used to capture
        server-generated tokens (e.g. ecbeans.nextPage, LANG) that must
        be echoed back in the POST.
        """
        fields: dict[str, str] = {}
        for m in re.finditer(r"<input\b[^>]*>", html, re.IGNORECASE):
            tag = m.group(0)
            if not re.search(r'type\s*=\s*["\']?hidden', tag, re.IGNORECASE):
                continue
            name_m = re.search(r'name\s*=\s*["\']?([^"\'\s>]+)', tag, re.IGNORECASE)
            value_m = re.search(r'value\s*=\s*["\']?([^"\'>]*)', tag, re.IGNORECASE)
            if name_m:
                fields[name_m.group(1)] = value_m.group(1) if value_m else ""
        return fields

    @staticmethod
    def _find_link_index_by_label(html: str, label: str) -> "str | None":
        """Find submitBy('N') index whose <a> visible text contains `label`."""
        for m in re.finditer(r"submitBy\('(\d+)'\)[^>]*>([^<]*)<", html):
            if label in m.group(2):
                return m.group(1)
        return None

    @staticmethod
    def _find_link_index_by_name(state: dict[str, str], link_name: str) -> "str | None":
        """Find sop.webflow.link.N index whose name field equals `link_name`."""
        for i in range(32):
            if state.get(f"sop.webflow.link.{i}.name") == link_name:
                return str(i)
        return None

    @staticmethod
    def _extract_error_message(html: str) -> str:
        """Extract the message inside <code>...</code> from the SOP error page."""
        m = re.search(r"<code>([^<]+)</code>", html, re.IGNORECASE)
        return m.group(1).strip() if m else "unknown error"

    def _validate_project_task(self, form_html: str) -> None:
        """Warn if configured project/task is not present in the page's dropdowns."""
        for field, label, configured in [
            ("opPrjid1", "project", self.project),
            ("opTaskid1", "task", self.task),
        ]:
            m = re.search(
                rf'<select[^>]*name="{field}"[^>]*>(.*?)</select>',
                form_html, re.DOTALL | re.IGNORECASE,
            )
            if not m:
                continue
            options = re.findall(r'<option[^>]*value="([^"]*)"', m.group(1), re.IGNORECASE)
            if configured not in options:
                # Suggest closest matches by prefix
                prefix = configured[:3].lower()
                hints = [o for o in options if prefix in o.lower()][:5]
                logger.warning(
                    f"Configured {label}={configured!r} not in dropdown "
                    f"({len(options)} options). Similar: {hints}"
                )

    @staticmethod
    def _parse_form_state(html: str) -> "tuple[str, list[dict[str, str]]]":
        """
        解析录入页: 提取状态横幅文字 + 12 行已有值 (project/task/Mon..Sun)。

        Returns:
            (status_text, rows)
            - status_text: <font class="success">…</font> 内的文字 (空字符串 = 未提交)
            - rows: 12 行 dict,每行含 project/task/mon/tue/wed/thu/fri/sat/sun
        """
        status_match = re.search(
            r'<font\s+class="success">\s*([^<]*?)\s*</font>',
            html, re.IGNORECASE,
        )
        status_text = status_match.group(1).strip() if status_match else ""

        day_bases = ["opMon", "opTue", "opWed", "opThu", "opFri", "opSat", "opSun"]
        rows: list[dict[str, str]] = []
        for row_n in range(1, 13):
            row: dict[str, str] = {}
            for base, label in [
                ("opPrjid", "project"), ("opTaskid", "task"),
                *[(b, b[2:].lower()) for b in day_bases],
            ]:
                fid = f"{base}{row_n}"
                sel_block = re.search(
                    rf'<select[^>]*id="{fid}"[^>]*>(.*?)</select>',
                    html, re.DOTALL | re.IGNORECASE,
                )
                if not sel_block:
                    row[label] = ""
                    continue
                options_html = sel_block.group(1)
                # 状态1: value="X" selected
                m = re.search(
                    r'<option[^>]*value="([^"]+)"[^>]*\bselected\b',
                    options_html, re.IGNORECASE,
                ) or re.search(
                    r'<option[^>]*\bselected\b[^>]*value="([^"]+)"',
                    options_html, re.IGNORECASE,
                )
                if not m:
                    # 回退到第一个 option (浏览器默认)
                    m = re.search(r'<option[^>]*value="([^"]+)"', options_html)
                row[label] = m.group(1) if m else ""
            rows.append(row)
        return status_text, rows

    def _log_timesheet_table(
        self, week_label: str, status_text: str, rows: list[dict[str, str]]
    ) -> bool:
        """
        日志输出当前周的 timesheet 表格 + 已提交状态。

        Returns:
            bool: True = 已提交过 (status_text 非空且含 submit/saved)
        """
        date_range = self.week_date_range(week_label)
        logger.info(f"Week {week_label} ({date_range})")

        if status_text:
            logger.info(f"Status banner: {status_text!r}")
        else:
            logger.info("Status banner: (empty - not yet submitted this week)")

        banner_submitted = bool(status_text) and any(
            kw in status_text.lower() for kw in ("submit", "saved", "approved")
        )

        # 即使 banner 为空,只要第 1 行已有真实项目/任务,就说明之前保存/提交过
        # (banner 只在 POST 之后立刻显示,re-open 后会被清空)
        row1 = rows[0] if rows else {}
        row1_has_data = (
            row1.get("project", "") and row1.get("project", "") != "-NA-"
        )
        if row1_has_data and not banner_submitted:
            logger.warning(
                f"⚠ Week {week_label} already has saved data "
                f"(row 1: {row1.get('project','')}/{row1.get('task','')}). "
                f"Likely submitted/saved in a previous session."
            )
        is_submitted = banner_submitted or row1_has_data

        day_labels = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        header = f"  {'#':<2} {'Project':<28} {'Task':<18} " + " ".join(d.upper() for d in day_labels)
        logger.info(f"Current timesheet for {week_label}:")
        logger.info(header)
        non_empty = 0
        for i, row in enumerate(rows, 1):
            project = row.get("project", "")
            task = row.get("task", "")
            if not project or project == "-NA-":
                continue  # 跳过空行
            non_empty += 1
            hours = [row.get(d, "0") for d in day_labels]
            logger.info(
                f"  {i:<2} {project[:28]:<28} {task[:18]:<18} "
                + " ".join(f"{h:>3}" for h in hours)
            )
        if non_empty == 0:
            logger.info("  (no project entries - all rows are -NA-)")
        total = sum(
            int(row.get(d, "0") or 0)
            for row in rows
            for d in day_labels
            if (row.get(d, "0") or "0").isdigit()
        )
        logger.info(f"  Total hours (all rows): {total}")

        if is_submitted:
            if banner_submitted:
                logger.warning(
                    f"⚠ Week {week_label} status: {status_text!r}. "
                    f"Re-submitting will overwrite the existing entry."
                )
            # row1-based warning 已在上面打印过
        return is_submitted

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        expected_marker: str | None = None,
        max_retries: int = 2,
        **kwargs,
    ) -> requests.Response:
        """
        发送请求,支持基于响应内容的重试。

        urllib3 的 Retry 仅在网络层 / 状态码层重试 (连接错误、429、5xx)。
        对于返回 200 但页面未完全加载、或被重定向到错误页的情况,
        需要此包装层手动重试。

        Args:
            method: HTTP 方法 ("GET" / "POST")
            url: 目标 URL
            expected_marker: 响应文本中必须包含的关键字符串,未找到则重试
            max_retries: 内容校验失败时的最大重试次数
            **kwargs: 透传给 session 请求方法的参数 (data, timeout 等)
        """
        kwargs.setdefault("timeout", 30)
        method_upper = method.upper()

        for attempt in range(max_retries + 1):
            try:
                if method_upper == "GET":
                    response = self.session.get(url, **kwargs)
                else:
                    response = self.session.post(url, **kwargs)
                response.raise_for_status()

                if expected_marker and expected_marker not in response.text:
                    if attempt < max_retries:
                        wait = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            f"Marker {expected_marker!r} not found "
                            f"(attempt {attempt + 1}/{max_retries + 1} for {url}), "
                            f"retrying in {wait:.1f}s"
                        )
                        time.sleep(wait)
                        continue
                    logger.error(
                        f"Content check failed after {max_retries + 1} attempts for {url}"
                    )
                return response

            except requests.RequestException as e:
                if attempt < max_retries:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"Request error (attempt {attempt + 1}/{max_retries + 1} for {url}): "
                        f"{e}, retrying in {wait:.1f}s"
                    )
                    time.sleep(wait)
                    continue
                raise

        raise requests.RequestException(
            f"Request to {url} exhausted retries unexpectedly"
        )

    def login(self) -> bool:
        """
        登录到 Toppan 系统

        Returns:
            bool: 登录是否成功
        """
        logger.info(
            f"Attempting login: user={self.username!r} "
            f"verify_tls={'OFF' if self.verify_tls is False else self.verify_tls}"
        )

        try:
            # 先访问登录页面获取 cookies (校验页面确实包含登录表单)
            response = self._request_with_retry(
                "GET", self.LOGIN_URL, expected_marker="USERID"
            )
            logger.info(
                f"Login page GET: status={response.status_code}, "
                f"len={len(response.text)}, cookies={list(self.session.cookies.keys())}"
            )

            # 动态解析所有 hidden 字段 (ecbeans.nextPage / ecbeans.inFrame / LANG 等),
            # 这些是 Java SOP 框架维持会话状态必需的,服务端会校验
            form_data = self._parse_hidden_inputs(response.text)
            form_data["USERID"] = self.username
            form_data["PASSWD"] = self.password
            hidden_fields = {k: v for k, v in form_data.items() if k not in ("USERID", "PASSWD")}
            logger.debug(
                f"Login POST fields: {list(form_data.keys())} -> {self.LOGIN_POST_URL}; "
                f"hidden={hidden_fields!r}"
            )

            # 发送登录请求到真正的 form action (不是 login.jsp)
            login_response = self.session.post(
                self.LOGIN_POST_URL,
                data=form_data,
                allow_redirects=True,
                timeout=30,
                headers={
                    "Referer": self.LOGIN_URL,
                    "Origin": self.BASE_URL,
                },
            )

            logger.info(
                f"Login POST: status={login_response.status_code}, "
                f"final_url={login_response.url}, body_len={len(login_response.text)}, "
                f"cookies={list(self.session.cookies.keys())}"
            )
            logger.debug(f"Login POST body[:300]: {login_response.text[:300]!r}")
            self._save_debug_html("login_post_response.html", login_response.text)

            # 服务器登录成功后返回 200 + JS 客户端跳转 (非 HTTP 3xx),
            # 需解析 location.href 并主动跟随,才能确认会话已建立
            m = re.search(
                r"location\.href\s*=\s*['\"]([^'\"]+)['\"]",
                login_response.text,
                re.IGNORECASE,
            )
            if m:
                next_path = m.group(1)
                next_url = (
                    self.BASE_URL + next_path
                    if next_path.startswith("/")
                    else next_path
                )
                logger.info(f"Following JS redirect -> {next_url}")
                verify_response = self.session.get(
                    next_url, allow_redirects=True, timeout=30
                )
                logger.info(
                    f"Verify GET: status={verify_response.status_code}, "
                    f"final_url={verify_response.url}, len={len(verify_response.text)}"
                )
                # 若 session 已建立,main.jsp 不会重定向回 login.jsp
                if "login.jsp" not in verify_response.url.lower():
                    self.is_logged_in = True
                    logger.info(f"Login successful (landed at {verify_response.url})")
                    return True
                logger.warning(f"Verify bounced back to login page: {verify_response.url}")
            else:
                logger.warning("Login POST response has no JS location.href redirect")

            logger.warning(
                f"Login may have failed. Body preview: {login_response.text[:200]!r}"
            )
            return False

        except requests.RequestException as e:
            logger.error(f"Login failed: {e}")
            return False

    def navigate_to_timesheet(self) -> "requests.Response | None":
        """
        导航到时间表页面。

        Returns:
            Response 对象 (成功) 或 None (失败)
        """
        logger.info(f"GET {self.TIMESHEET_URL}")

        try:
            response = self._request_with_retry("GET", self.TIMESHEET_URL)
            logger.info(
                f"Timesheet page: status={response.status_code}, "
                f"final_url={response.url}, len={len(response.text)}"
            )
            logger.debug(f"Timesheet body[:400]: {response.text[:400]!r}")
            self._save_debug_html("timesheet_page.html", response.text)
            return response

        except requests.RequestException as e:
            logger.error(f"Failed to navigate to timesheet: {e}")
            return None

    def get_current_week(self) -> str:
        """获取当前周编号，格式如 'WK-52/2025'"""
        today = datetime.now()
        # 计算周数（ISO 8601）
        week_num = today.isocalendar()[1]
        year = today.isocalendar()[0]
        return f"WK-{week_num}/{year}"

    @staticmethod
    def week_date_range(week_label: str) -> str:
        """
        把 'WK-33/2026' 转成 '2026/8/10 - 2026/8/16' (Mon - Sun)。

        Args:
            week_label: 'WK-{N}/{YYYY}' 格式字符串

        Returns:
            'YYYY/M/D - YYYY/M/D' (无前导零); 解析失败时返回原字符串
        """
        m = re.match(r"WK-(\d{1,2})/(\d{4})", week_label.strip())
        if not m:
            return week_label
        week_num, year = int(m.group(1)), int(m.group(2))
        try:
            monday = datetime.fromisocalendar(year, week_num, 1).date()
            sunday = monday + timedelta(days=6)
            return (
                f"{monday.year}/{monday.month}/{monday.day} - "
                f"{sunday.year}/{sunday.month}/{sunday.day}"
            )
        except ValueError:
            return week_label

    def submit_timesheet(self, hours_per_day: int = 8, force_submit: bool = False) -> bool:
        """
        提交时间表 (两步 WebFlow):

        1. GET timesheet 选周页 → 拿 continuationPassID / caseID + 当前周 link index
        2. POST 选当前周 → 服务器返回带 opPrjid1 / opMon1 等字段的录入页
        3. POST 录入页表单 (项目/任务/hours + 点 btnSubmit) → 完成提交

        Args:
            hours_per_day: 每天工作小时数 (Mon-Fri); Sat/Sun 固定为 0

        Returns:
            bool: 是否成功
        """
        target_week = self.get_current_week()
        logger.info(
            f"Submitting timesheet: project={self.project!r}, task={self.task!r}, "
            f"hours/day={hours_per_day}, week={target_week} "
            f"({self.week_date_range(target_week)})"
        )

        try:
            # === Step 1: GET 选周页 ===
            page = self.navigate_to_timesheet()
            if page is None:
                return False

            state = self._parse_hidden_inputs(page.text)
            week_idx = self._find_link_index_by_label(page.text, target_week)
            if week_idx is None:
                logger.error(f"Week {target_week} not in selector. Available weeks:")
                for m in re.finditer(r"submitBy\('(\d+)'\)[^>]*>([^<]+)<", page.text):
                    logger.error(f"  link[{m.group(1)}]: {m.group(2).strip()!r}")
                return False
            logger.info(f"Step 1: week {target_week} -> link[{week_idx}]")

            # === Step 2: POST 选周 ===
            state["submitID"] = week_idx
            # form enctype=multipart/form-data,必须用 files= 而非 data=
            # (否则服务器返回 "1" 这种语义不清的错误)
            week_multipart = {k: (None, v) for k, v in state.items()}
            week_resp = self.session.post(
                self.SUBMIT_URL,
                files=week_multipart,
                allow_redirects=True,
                timeout=30,
                headers={"Referer": self.TIMESHEET_URL, "Origin": self.BASE_URL},
            )
            logger.info(
                f"Step 2 POST (select week): status={week_resp.status_code}, "
                f"len={len(week_resp.text)}, url={week_resp.url}"
            )
            self._save_debug_html("timesheet_form.html", week_resp.text)
            if "an error has occured" in week_resp.text.lower():
                logger.error(
                    f"Step 2 failed: {self._extract_error_message(week_resp.text)!r}. "
                    f"See timesheet_form.html"
                )
                return False

            # === Step 2.5: 解析并打印当前周的录入表 + 检查是否已提交 ===
            status_text, rows = self._parse_form_state(week_resp.text)
            already_submitted = self._log_timesheet_table(target_week, status_text, rows)
            if already_submitted and not force_submit:
                logger.warning(
                    f"Skipping re-submission for {target_week}. "
                    f"Pass --force-submit to override."
                )
                self.last_action = "skipped"
                return True

            # === Step 3: 解析录入页 + 提交 ===
            form_state = self._parse_hidden_inputs(week_resp.text)
            submit_idx = self._find_link_index_by_name(form_state, "sop.webflow.field.btnSubmit")
            if submit_idx is None:
                logger.error("Submit button (sop.webflow.field.btnSubmit) not found on form page")
                return False
            logger.debug(f"Step 3: btnSubmit -> link[{submit_idx}]")

            # 警告配置的项目/任务不在下拉框 (POST 几乎肯定失败,但让服务器最终判定)
            self._validate_project_task(week_resp.text)

            # form 中所有 12 行 op selects 都共享 name=opPrjid1 / opTaskid1 / opMon1..
            # (id 不同但 name 重复) → 浏览器会提交 12 个同名值。服务器据此按行索引读取。
            # 因此必须用 list-of-tuples 形式构造 multipart,而不是 dict (dict 只能发 1 个值)
            hours_str = str(hours_per_day)
            day_defaults = ["0"] * 7
            day_filled = [
                hours_str, hours_str, hours_str, hours_str, hours_str, "0", "0"
            ]  # Mon-Fri=hours, Sat/Sun=0

            submit_fields: list[tuple[str, tuple[None, str]]] = []
            # 1) hidden state (DOM 顺序: ecbeans.action, requestType, continuationPassID,
            #    caseID, submitID, ecbeans.SOP_THIS_UB, 以及所有 sop.webflow.link.N.*)
            for k, v in form_state.items():
                if k == "submitID":
                    submit_fields.append((k, (None, submit_idx)))
                else:
                    submit_fields.append((k, (None, v)))
            # 如果 form_state 没有 submitID,则追加
            if "submitID" not in form_state:
                submit_fields.append(("submitID", (None, submit_idx)))

            # 2) 12 行 op 字段,每行 9 个: opPrjid1, opTaskid1, opMon1..opSun1
            day_field_names = ["opMon1", "opTue1", "opWed1", "opThu1", "opFri1", "opSat1", "opSun1"]
            for row in range(12):
                if row == 0:
                    submit_fields.append(("opPrjid1", (None, self.project)))
                    submit_fields.append(("opTaskid1", (None, self.task)))
                    for fname, val in zip(day_field_names, day_filled):
                        submit_fields.append((fname, (None, val)))
                else:
                    submit_fields.append(("opPrjid1", (None, "-NA-")))
                    submit_fields.append(("opTaskid1", (None, "-NA-")))
                    for fname, val in zip(day_field_names, day_defaults):
                        submit_fields.append((fname, (None, val)))

            logger.debug(
                f"Step 3 POST: {len(submit_fields)} multipart parts "
                f"(op fields = 12 rows × 9 = 108)"
            )

            submit_resp = self.session.post(
                self.SUBMIT_URL,
                files=submit_fields,
                allow_redirects=True,
                timeout=30,
                headers={"Referer": self.SUBMIT_URL, "Origin": self.BASE_URL},
            )
            logger.info(
                f"Step 3 POST (submit): status={submit_resp.status_code}, "
                f"len={len(submit_resp.text)}, url={submit_resp.url}"
            )
            logger.debug(f"Submit body[:500]: {submit_resp.text[:500]!r}")
            self._save_debug_html("submit_response.html", submit_resp.text)

            # 内容校验
            if "login.jsp" in submit_resp.url.lower():
                logger.error("Submit bounced back to login.jsp — session lost")
                return False
            if "an error has occured" in submit_resp.text.lower():
                logger.error(
                    f"Submit failed: {self._extract_error_message(submit_resp.text)!r}. "
                    f"See submit_response.html"
                )
                return False

            logger.info(f"Timesheet submitted for {target_week}")
            self.last_action = "submitted"
            return True

        except requests.RequestException as e:
            logger.error(f"Failed to submit timesheet: {e}")
            self.last_action = "failed"
            return False

    def run(self, force_submit: bool = False) -> bool:
        """
        运行完整的自动提交流程

        Args:
            force_submit: 即使当周已提交/已保存也强制重新提交

        Returns:
            bool: 是否成功
        """
        logger.info("Starting auto timesheet submission flow")

        # 1. 登录
        if not self.login():
            logger.error("Login failed")
            return False

        # 2. 提交时间表 (内部会先 GET timesheet 页)
        if not self.submit_timesheet(force_submit=force_submit):
            logger.error("Failed to submit timesheet")
            return False

        logger.info("Auto timesheet submission completed successfully")
        return True


@dataclass(frozen=True)
class TimesheetConfig:
    """时间表配置"""
    username: str
    password: str
    project: str
    task: str
    hours_per_day: int = 8
    verify_tls: Union[bool, str] = False


class TimesheetResult(NamedTuple):
    """时间表提交结果"""
    success: bool
    message: str
    week: str


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

    try:
        success = session.run(force_submit=force_submit)

        if success:
            action = session.last_action
            if action == "skipped":
                message = "Time sheet already submitted/saved - skipped (use --force-submit to overwrite)"
            else:
                message = "Time sheet submitted successfully"
            return TimesheetResult(
                success=True,
                message=message,
                week=session.get_current_week(),
            )
        else:
            return TimesheetResult(
                success=False,
                message="Failed to submit time sheet",
                week=session.get_current_week(),
            )
    finally:
        session.close()


# 使用示例
if __name__ == "__main__":
    import argparse

    # CLI 运行时使用默认 stderr-only 配置 (没有日志文件)
    configure_logging(level="INFO")

    parser = argparse.ArgumentParser(description="Toppan Timesheet Auto-submit")
    parser.add_argument(
        "--username",
        default=os.environ.get("TOPPAN_USERNAME", "zhiming"),
        help="Login user id (env: TOPPAN_USERNAME, default: zhiming)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("TOPPAN_PASSWORD", "password$1"),
        help="Login password (env: TOPPAN_PASSWORD, default: password$1)",
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("TOPPAN_PROJECT", "PD_AGP"),
        help="Project code (env: TOPPAN_PROJECT, default: PD_AGP)",
    )
    parser.add_argument(
        "--task",
        default=os.environ.get("TOPPAN_TASK", "Prodt Devt"),
        help="Task name (env: TOPPAN_TASK, default: Prodt Devt)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=int(os.environ.get("TOPPAN_HOURS", "8")),
        help="Hours per day Mon-Fri (env: TOPPAN_HOURS, default: 8)",
    )
    parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("TOPPAN_CA_BUNDLE", ""),
        help=(
            "Path to CA bundle (.pem / .crt). "
            "Empty (default) = disable TLS verification."
        ),
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging (dumps request bodies, hidden fields, cookies, etc.)",
    )
    parser.add_argument(
        "--force-submit",
        action="store_true",
        help="Re-submit even if week already has submitted/saved status (default: skip)",
    )
    args = parser.parse_args()

    # 根据参数调整 root logger 等级 (basicConfig 默认是 WARNING,我们已经设了 INFO)
    logging.getLogger().setLevel(logging.DEBUG if args.verbose else logging.INFO)
    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    verify_tls: Union[bool, str] = args.ca_bundle if args.ca_bundle else False

    config = TimesheetConfig(
        username=args.username,
        password=args.password,
        project=args.project,
        task=args.task,
        hours_per_day=args.hours,
        verify_tls=verify_tls,
    )

    try:
        result = submit_timesheet(config, force_submit=args.force_submit)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user (Ctrl+C) — likely stuck on DNS or network")
        raise SystemExit(130)
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection failed (DNS or network): {e}")
        raise SystemExit(1)

    if result.success:
        logger.info(f"✓ {result.message} for {result.week}")
    else:
        logger.error(f"✗ {result.message}")
