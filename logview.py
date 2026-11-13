#!/usr/bin/env python3
"""LogViewer - TUI สำหรับดู Log สด (ไฟล์ / pipe / --run) ด้วย Textual

ใช้งาน:
    python logview.py app.log
    pm2 logs --raw | logview
    logview --run "pm2 logs --raw"
    logview --demo

เมาส์:  ลากคลุม (ลากเลยขอบจอแล้วเลื่อนตามอัตโนมัติ) = คัดลอกทันที
        ดับเบิลคลิก = เลือกคำ / ทริปเปิลคลิก = เลือกทั้งบรรทัด / คลิกเฉยๆ = ล้างการคลุม
"""
import argparse
import bisect
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime

# เปิดสีครบทุกเฉดแม้ใช้งานผ่าน SSH บน Linux (หากไม่ได้ตั้ง NO_COLOR)
if "NO_COLOR" not in os.environ:
    os.environ.setdefault("COLORTERM", "truecolor")

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Header, Input, Static

MAX_BUFFER_LINES = 2000          # เก็บประวัติสูงสุดบนหน้าจอ
TAIL_BYTES = 65536               # โหลดท้ายไฟล์ตอนเปิด
READ_CHUNK_BYTES = 4 * 1024 * 1024
DRAIN_INTERVAL = 0.1             # วินาที: รวมบรรทัดใหม่เป็นชุดแล้วค่อยวาด
INCOMING_LIMIT = 100_000         # กันคิวบวม
AUTOSCROLL_HZ = 30               # ความถี่เลื่อนจออัตโนมัติตอนลากเลยขอบ
AUTOSCROLL_MAX_LINES = 12        # เลื่อนเร็วสุดต่อครั้ง
SELECTION_STYLE = "bold white on #2563eb"

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
NON_SGR_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-ln-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
WORD_RE = re.compile(r"[\w./:\-@\\]+", re.UNICODE)

# จับรูปแบบเวลา รวมถึง ISO8601 ที่ลงท้ายด้วย Z หรือ +07:00
TS_RE = re.compile(
    r"^(\[?\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\]?|\[?\d{2}:\d{2}:\d{2}(?:\.\d+)?\]?)\s*(.*)"
)
# จับแท็กนำหน้า เช่น [telegram] [config] [PM2]
TAG_RE = re.compile(r"^(\[[^\]\r\n]{1,32}\])\s*(.*)")
# จับระดับ Log ชัดเจนที่ต้นข้อความ เช่น ERR, WRN, INF, ERROR, WARN, INFO
LEVEL_RE = re.compile(
    r"^(ERR(?:OR)?|FATAL|CRITICAL|WRN|WARN(?:ING)?|INF(?:O)?|DBG|DEBUG)\b\s*(.*)",
    re.I,
)

ERROR_RE = re.compile(
    r"ERROR|EXCEPTION|\b(?:ERR|FATAL|CRITICAL|TRACEBACK|FAIL(?:ED|URE)?|ECONNREFUSED|ETIMEDOUT)\b|Bad Request|พัง|ผิดพลาด|ล้มเหลว",
    re.I,
)
WARN_RE = re.compile(
    r"\b(?:WRN|WARN(?:ING)?|Retrying|disconnected)\b|⚠|Lost connection|เตือน|ระวัง",
    re.I,
)
OK_RE = re.compile(
    r"\b(?:SUCCESS|OK|READY|CONNECTED|LISTENING|Registered)\b|\s200\s|สำเร็จ",
    re.I,
)
DEBUG_RE = re.compile(r"\b(?:DBG|DEBUG)\b", re.I)


class StatusBar(Static):
    allow_select = False


# ---------------------------------------------------------------- text helpers
def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def clean_line(raw: str) -> str:
    line = raw.rstrip("\r\n")
    if "\r" in line:
        line = line.rsplit("\r", 1)[-1]
    return line.replace("\t", "    ").replace("\x00", "")


def split_lines(text: str) -> list[str]:
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return [p + "\n" for p in parts]


def _classify_body_style(body: str) -> str:
    if ERROR_RE.search(body):
        return "bold red"
    if WARN_RE.search(body):
        return "bold yellow"
    if OK_RE.search(body):
        return "green"
    if DEBUG_RE.search(body):
        return "dim white"
    return "white"


def style_log_line(raw_line: str, keyword: str = "") -> Text:
    """ลงสี Log อัตโนมัติ (รองรับทั้งสี ANSI จากต้นทาง และข้อความดิบจาก Pipe/ไฟล์)"""
    clean = clean_line(raw_line)

    if "\x1b[" in clean:
        text = Text.from_ansi(NON_SGR_RE.sub("", clean))
    else:
        text = Text()
        rest = clean

        # 1. ส่วนวันที่/เวลา
        ts_match = TS_RE.match(rest)
        if ts_match:
            text.append(ts_match.group(1) + " ", style="dim cyan")
            rest = ts_match.group(2)

        # 2. แท็กนำหน้า เช่น [telegram] [config]
        tag_match = TAG_RE.match(rest)
        if tag_match:
            text.append(tag_match.group(1) + " ", style="bold magenta")
            rest = tag_match.group(2)

        # 3. ระดับ Log ชัดเจน (ERR / WRN / INF / DEBUG)
        lvl_match = LEVEL_RE.match(rest)
        if lvl_match:
            lvl_token = lvl_match.group(1)
            msg_body = lvl_match.group(2)
            lvl_upper = lvl_token.upper()

            if lvl_upper.startswith(("ERR", "FATAL", "CRIT")):
                text.append(lvl_token + " ", style="bold red")
                text.append(msg_body, style="bold red")
            elif lvl_upper.startswith("W"):
                text.append(lvl_token + " ", style="bold yellow")
                text.append(msg_body, style="yellow")
            elif lvl_upper.startswith("I"):
                text.append(lvl_token + " ", style="bold cyan")
                text.append(msg_body, style=_classify_body_style(msg_body))
            else:
                text.append(lvl_token + " ", style="dim white")
                text.append(msg_body, style="dim white")
        else:
            text.append(rest, style=_classify_body_style(rest))

    if not text.plain.strip():
        return Text(" ")

    if keyword:
        text.highlight_words([keyword], style="bold black on yellow", case_sensitive=False)
    return text


def col_from_cell(plain: str, cell_x: int) -> int:
    """แปลงตำแหน่งคอลัมน์บนจอ (cell) เป็นตำแหน่งตัวอักษร รองรับไทย/อักษรกว้าง/สระลอย"""
    if cell_x <= 0:
        return 0
    acc = 0.0
    for i, ch in enumerate(plain):
        w = cell_len(ch)
        if cell_x < acc + w / 2:
            return i
        acc += w
    return len(plain)


# ---------------------------------------------------------------- clipboard
def _win_set_clipboard(text: str) -> bool:
    """เขียน Clipboard ของ Windows ผ่าน Win32 API โดยตรง (รองรับ Unicode/ไทย เต็มรูปแบบ)"""
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32

    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalLock.restype = wintypes.LPVOID
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.OpenClipboard.restype = wintypes.BOOL
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u32.SetClipboardData.restype = wintypes.HANDLE

    data = (text.replace("\r\n", "\n").replace("\n", "\r\n") + "\0").encode("utf-16le")

    for _ in range(20):
        if u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False

    try:
        u32.EmptyClipboard()
        handle = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ptr = k32.GlobalLock(handle)
        if not ptr:
            k32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, data, len(data))
        k32.GlobalUnlock(handle)
        if not u32.SetClipboardData(CF_UNICODETEXT, handle):
            k32.GlobalFree(handle)
            return False
        return True
    finally:
        u32.CloseClipboard()


def copy_to_clipboard_cross_platform(app: App, text: str) -> bool:
    """คัดลอกลง Clipboard (Windows / macOS / Linux X11+Wayland) คืน True ถ้าสำเร็จ"""
    if not text:
        return False

    osc_ok = False
    try:
        app.copy_to_clipboard(text)
        osc_ok = True
    except Exception:
        pass

    system_ok = False
    try:
        if os.name == "nt":
            system_ok = _win_set_clipboard(text)
            if not system_ok:
                subprocess.run(
                    ["clip"],
                    input=text.encode("utf-16le"),
                    check=True,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                system_ok = True
        else:
            for cmd in (
                ["wl-copy"],
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
                ["pbcopy"],
            ):
                if shutil.which(cmd[0]):
                    subprocess.run(
                        cmd,
                        input=text.encode("utf-8"),
                        check=True,
                        timeout=3,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    system_ok = True
                    break
    except Exception:
        pass

    return system_ok or osc_ok


# ---------------------------------------------------------------- subprocess & pipe cleanup
def _force_kill(proc: subprocess.Popen) -> None:
    try:
        if proc.poll() is None:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass


def terminate_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            timer = threading.Timer(3.0, _force_kill, args=(proc,))
            timer.daemon = True
            timer.start()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def _find_pipe_writers(pipe_inode: int) -> list[int]:
    """ค้นหา PID ของโปรแกรมต้นทางที่ส่งข้อมูลเข้าท่อ Pipe นี้ (เฉพาะ Linux)"""
    if not pipe_inode or not os.path.isdir("/proc"):
        return []
    my_pid = os.getpid()
    target = f"pipe:[{pipe_inode}]"
    writers: list[int] = []
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            if pid == my_pid:
                continue
            fd_dir = f"/proc/{pid}/fd"
            try:
                for fd_name in os.listdir(fd_dir):
                    try:
                        if os.readlink(f"{fd_dir}/{fd_name}") == target:
                            writers.append(pid)
                            break
                    except OSError:
                        continue
            except OSError:
                continue
    except OSError:
        pass
    return writers


def cleanup_pipe_writers(pipe_inode: int | None) -> None:
    """ปิดโปรเซสต้นทางของท่อ Pipe เมื่อออกจาก logview เพื่อไม่ให้ค้างพิมพ์ทับ Terminal"""
    if not pipe_inode:
        return
    pids = _find_pipe_writers(pipe_inode)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    if pids:
        time.sleep(0.15)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


# ---------------------------------------------------------------- log widget
class LogView(ScrollView, can_focus=True):
    """แสดง Log แบบ virtual rendering + ระบบคลุมข้อความของตัวเอง"""

    allow_select = False

    BINDINGS = [
        Binding("up", "scroll_up", show=False),
        Binding("down", "scroll_down", show=False),
        Binding("left", "scroll_left", show=False),
        Binding("right", "scroll_right", show=False),
        Binding("pageup", "page_up", show=False),
        Binding("pagedown", "page_down", show=False),
        Binding("home", "scroll_home", show=False),
        Binding("end", "scroll_end", show=False),
    ]

    class Selected(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ids: list[int] = []
        self._texts: list[Text] = []
        self._copy: list[str] = []
        self._max_cells = 1
        self.follow = True
        self._anchor: tuple[int, int] | None = None
        self._cursor: tuple[int, int] | None = None
        self._dragging = False
        self._adjusting = False
        self._last_x = 0
        self._last_y = 0
        self._drag_timer = None
        self._edge_ticks = 0

    def _sync_size(self) -> None:
        self.virtual_size = Size(max(self._max_cells, 1), len(self._texts))

    def add_items(self, items: list[tuple[int, Text, str]]) -> None:
        if not items:
            return
        for seq, text, copy in items:
            self._ids.append(seq)
            self._texts.append(text)
            self._copy.append(copy)
            if text.cell_len > self._max_cells:
                self._max_cells = text.cell_len
        removed = len(self._ids) - MAX_BUFFER_LINES
        if removed > 0:
            del self._ids[:removed]
            del self._texts[:removed]
            del self._copy[:removed]
        self._sync_size()
        if removed > 0 and not self.follow:
            self._adjusting = True
            try:
                self.scroll_to(y=max(0, self.scroll_y - removed), animate=False)
            finally:
                self._adjusting = False
        if self.follow and not self._dragging:
            self.scroll_end(animate=False)
        self.refresh()

    def set_items(self, items: list[tuple[int, Text, str]]) -> None:
        self._ids = [i[0] for i in items]
        self._texts = [i[1] for i in items]
        self._copy = [i[2] for i in items]
        self._max_cells = max((t.cell_len for t in self._texts), default=1)
        self._sync_size()
        if self.follow:
            self.scroll_end(animate=False)
        self.refresh()

    def clear(self) -> None:
        self._ids, self._texts, self._copy = [], [], []
        self._max_cells = 1
        self._anchor = self._cursor = None
        self.stop_drag()
        self.follow = True
        self._sync_size()
        self.scroll_home(animate=False)
        self.refresh()

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if self._dragging or self._adjusting:
            return
        if new_value >= self.max_scroll_y - 1:
            self.follow = True
        elif new_value < old_value:
            self.follow = False

    def action_scroll_end(self) -> None:
        self.follow = True
        self.scroll_end(animate=False)

    def _index_of(self, pos: tuple[int, int]) -> tuple[int, int]:
        seq, col = pos
        n = len(self._ids)
        if n == 0:
            return 0, 0
        idx = bisect.bisect_left(self._ids, seq)
        if idx >= n:
            return n - 1, len(self._texts[-1].plain)
        if self._ids[idx] == seq:
            return idx, col
        return idx, 0

    def _selection_range(self):
        if self._anchor is None or self._cursor is None or not self._ids:
            return None
        a = self._index_of(self._anchor)
        b = self._index_of(self._cursor)
        if a == b:
            return None
        return (a, b) if a <= b else (b, a)

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        width = self.size.width
        row = scroll_y + y
        if row >= len(self._texts):
            return Strip.blank(width, self.rich_style)

        text = self._texts[row]
        sel = self._selection_range()
        if sel is not None:
            (i1, c1), (i2, c2) = sel
            if i1 <= row <= i2:
                total = len(text.plain)
                start = c1 if row == i1 else 0
                end = c2 if row == i2 else total
                start, end = min(start, total), min(end, total)
                if end > start:
                    text = text.copy()
                    text.stylize(SELECTION_STYLE, start, end)

        strip = Strip(list(text.render(self.app.console)))
        strip = strip.crop_extend(scroll_x, scroll_x + width, self.rich_style)
        return strip.apply_style(self.rich_style)

    @property
    def has_selection(self) -> bool:
        return self._selection_range() is not None

    def clear_selection(self) -> None:
        if self._anchor is not None or self._cursor is not None:
            self._anchor = self._cursor = None
            self.refresh()

    def get_selected_text(self) -> str:
        sel = self._selection_range()
        if sel is None:
            return ""
        (i1, c1), (i2, c2) = sel
        if i1 == i2:
            return self._copy[i1][c1:c2]
        parts = [self._copy[i1][c1:]]
        parts.extend(self._copy[i1 + 1:i2])
        parts.append(self._copy[i2][:c2])
        return "\n".join(parts)

    def _pos_at(self, x: float, y: float) -> tuple[int, int] | None:
        n = len(self._ids)
        if n == 0:
            return None
        height = max(self.size.height, 1)
        vy = min(max(int(y), 0), height - 1)
        idx = min(self.scroll_offset.y + vy, n - 1)
        col = col_from_cell(self._texts[idx].plain, int(x) + self.scroll_offset.x)
        return self._ids[idx], col

    def _update_cursor_from_pointer(self) -> None:
        pos = self._pos_at(self._last_x, self._last_y)
        if pos is not None and pos != self._cursor:
            self._cursor = pos
            self.refresh()

    def stop_drag(self) -> None:
        self._dragging = False
        if self._drag_timer is not None:
            self._drag_timer.stop()
            self._drag_timer = None
        try:
            if self.app.mouse_captured is self:
                self.release_mouse()
        except Exception:
            pass

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 3:
            event.stop()
            text = self.get_selected_text()
            if text:
                self.post_message(self.Selected(text))
            return
        if event.button != 1:
            return
        event.stop()
        self.focus()
        pos = self._pos_at(event.x, event.y)
        if pos is None:
            return
        self._last_x, self._last_y = event.x, event.y
        self.follow = False
        self._anchor = self._cursor = pos
        self._dragging = True
        self._edge_ticks = 0
        self.capture_mouse()
        if self._drag_timer is None:
            self._drag_timer = self.set_interval(1 / AUTOSCROLL_HZ, self._drag_tick)
        self.refresh()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        event.stop()
        self._last_x, self._last_y = event.x, event.y
        self._update_cursor_from_pointer()

    def _drag_tick(self) -> None:
        if not self._dragging:
            return
        height = self.size.height
        if self._last_y < 0:
            direction, dist = -1, int(-self._last_y)
        elif self._last_y >= height:
            direction, dist = 1, int(self._last_y - height)
        else:
            self._edge_ticks = 0
            return
        self._edge_ticks += 1
        step = direction * min(1 + dist + self._edge_ticks // 4, AUTOSCROLL_MAX_LINES)
        target = min(max(self.scroll_y + step, 0), self.max_scroll_y)
        if target != self.scroll_y:
            self.scroll_to(y=target, animate=False)
        self._update_cursor_from_pointer()

    def on_click(self, event: events.Click) -> None:
        chain = getattr(event, "chain", 1)
        if event.button != 1 or chain < 2:
            return
        pos = self._pos_at(event.x, event.y)
        if pos is None:
            return
        event.stop()
        idx = self._index_of(pos)[0]
        plain = self._texts[idx].plain
        if chain == 2:
            for m in WORD_RE.finditer(plain):
                if m.start() <= pos[1] <= m.end():
                    self._anchor, self._cursor = (pos[0], m.start()), (pos[0], m.end())
                    break
            else:
                return
        else:
            self._anchor, self._cursor = (pos[0], 0), (pos[0], len(plain))
        self.refresh()
        text = self.get_selected_text()
        if text:
            self.post_message(self.Selected(text))

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if event.button != 1 or not self._dragging:
            return
        event.stop()
        self.stop_drag()
        if self.scroll_y >= self.max_scroll_y - 1:
            self.follow = True
        text = self.get_selected_text()
        if text:
            self.post_message(self.Selected(text))
        else:
            self.clear_selection()


# ---------------------------------------------------------------- app
class LogViewerApp(App):
    CSS = """
    #status-bar {
        height: 1;
        background: $boost;
        color: $text;
        padding: 0 1;
    }
    #log-scroll {
        height: 1fr;
        background: $surface;
    }
    #search-input {
        display: none;
        height: 3;
        border: tall $accent;
    }
    #search-input.visible {
        display: block;
    }
    """

    ALLOW_SELECT = False

    BINDINGS = [
        Binding("space", "toggle_pause", "Pause/Live"),
        Binding("slash", "open_search", "Filter (/)"),
        Binding("e", "toggle_error", "Error Only"),
        Binding("r", "restart_process", "Restart"),
        Binding("ctrl+c", "copy_selection", "Copy", priority=True),
        Binding("y", "copy_selection", "Copy", show=False),
        Binding("a", "copy_all", "Copy All"),
        Binding("s", "save_logs", "Save"),
        Binding("c", "clear_logs", "Clear"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        file_path: str | None = None,
        run_cmd: str | None = None,
        piped_stream=None,
        demo: bool = False,
    ):
        super().__init__()
        self.file_path = file_path
        self.run_cmd = run_cmd
        self.piped_stream = piped_stream
        self.demo_mode = demo or not any((file_path, run_cmd, piped_stream))

        self.lines: deque[tuple[int, str]] = deque(maxlen=MAX_BUFFER_LINES)
        self._seq = 0
        self._incoming: deque[str] = deque(maxlen=INCOMING_LIMIT)
        self.file_pos = 0
        self.paused = False
        self.error_only = False
        self.keyword = ""
        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()
        self._proc_gen = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield StatusBar("", id="status-bar")
        yield LogView(id="log-scroll")
        yield Input(
            placeholder="พิมพ์คำค้นหาแล้วกด Enter (กด Esc เพื่อล้างตัวกรอง)...",
            id="search-input",
        )
        yield Footer()

    def on_mount(self) -> None:
        if self.run_cmd:
            self.title = f"LogViewer [RUN] - {self.run_cmd}"
        elif self.piped_stream:
            self.title = "LogViewer [PIPE]"
        elif self.file_path:
            self.title = f"LogViewer - {self.file_path}"
        else:
            self.title = "LogViewer - DEMO MODE"

        self._view().focus()
        self.update_status_bar()
        self.set_interval(DRAIN_INTERVAL, self._drain_incoming)

        if self.run_cmd:
            self.start_subprocess()
        elif self.piped_stream:
            threading.Thread(target=self._read_pipe_worker, daemon=True).start()
        elif self.file_path:
            self.load_initial_tail()
            self.set_interval(0.2, self.poll_file)
        else:
            self.set_interval(0.7, self.generate_demo_log)

    def on_unmount(self) -> None:
        self.stop_subprocess()
        if self.piped_stream:
            try:
                self.piped_stream.close()
            except Exception:
                pass

    def _view(self) -> LogView:
        return self.query_one("#log-scroll", LogView)

    def start_subprocess(self) -> None:
        self.stop_subprocess()
        if not self.run_cmd:
            return

        with self._proc_lock:
            gen = self._proc_gen

        now = datetime.now().strftime("%H:%M:%S")
        self._incoming.append(f"[{now}] INFO  Starting: {self.run_cmd}\n")

        def _worker() -> None:
            try:
                env = os.environ.copy()
                env.setdefault("FORCE_COLOR", "1")
                env.setdefault("PYTHONUNBUFFERED", "1")
                env.setdefault("PYTHONIOENCODING", "utf-8")
                kwargs = {
                    "shell": True,
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.STDOUT,
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                    "bufsize": 1,
                    "env": env,
                }
                if os.name != "nt":
                    kwargs["start_new_session"] = True

                proc = subprocess.Popen(self.run_cmd, **kwargs)
                with self._proc_lock:
                    if gen != self._proc_gen:
                        terminate_process_tree(proc)
                        return
                    self._proc = proc

                if proc.stdout:
                    for line in proc.stdout:
                        if gen != self._proc_gen:
                            return
                        self._incoming.append(line)

                code = proc.wait()
                if gen == self._proc_gen:
                    end_time = datetime.now().strftime("%H:%M:%S")
                    level = "INFO " if code == 0 else "ERROR"
                    self._incoming.append(
                        f"[{end_time}] {level} Process exited with code {code}\n"
                    )
            except Exception as e:
                if gen == self._proc_gen:
                    self._incoming.append(f"[ERROR] รันคำสั่งไม่สำเร็จ: {e}\n")

        threading.Thread(target=_worker, daemon=True).start()

    def stop_subprocess(self) -> None:
        with self._proc_lock:
            self._proc_gen += 1
            proc = self._proc
            self._proc = None
        if proc:
            terminate_process_tree(proc)

    def action_restart_process(self) -> None:
        if not self.run_cmd:
            self.notify('ปุ่ม R ใช้ได้เฉพาะตอนเปิดด้วยโหมด --run "คำสั่ง"', timeout=2)
            return
        self.notify("กำลังรีสตาร์ทโปรเซส...", timeout=1.5)
        self.start_subprocess()

    def _read_pipe_worker(self) -> None:
        try:
            for line in self.piped_stream:
                self._incoming.append(line)
            self._incoming.append("[INFO] Stream ended (EOF)\n")
        except Exception:
            pass

    def update_status_bar(self) -> None:
        state = "⏸ PAUSED" if self.paused else "● LIVE"
        mode = " [ERROR ONLY]" if self.error_only else ""
        filt = f" | Filter: '{self.keyword}'" if self.keyword else ""
        total = f" | Buffer: {len(self.lines)} lines"
        try:
            self.query_one("#status-bar", StatusBar).update(f"{state}{mode}{filt}{total}")
        except Exception:
            pass

    def matches_filter(self, line: str) -> bool:
        plain = strip_ansi(line)
        if self.error_only and not ERROR_RE.search(plain):
            return False
        if self.keyword and self.keyword.lower() not in plain.lower():
            return False
        return True

    def _store(self, raw_lines: list[str]) -> list[tuple[int, str]]:
        entries = []
        for raw in raw_lines:
            self._seq += 1
            entries.append((self._seq, raw))
        self.lines.extend(entries)
        return entries

    def _make_item(self, seq: int, raw: str) -> tuple[int, Text, str]:
        text = style_log_line(raw, self.keyword)
        plain = text.plain
        return seq, text, plain if plain.strip() else ""

    def _drain_incoming(self) -> None:
        if not self._incoming:
            return
        batch: list[str] = []
        while True:
            try:
                batch.append(self._incoming.popleft())
            except IndexError:
                break
        if batch:
            self._ingest(batch)

    def _ingest(self, batch: list[str]) -> None:
        entries = self._store(batch)
        if not self.paused:
            visible = [
                self._make_item(seq, raw)
                for seq, raw in entries[-MAX_BUFFER_LINES:]
                if self.matches_filter(raw)
            ]
            self._view().add_items(visible)
        self.update_status_bar()

    def rebuild_view(self) -> None:
        visible = [
            self._make_item(seq, raw)
            for seq, raw in self.lines
            if self.matches_filter(raw)
        ]
        self._view().set_items(visible)
        self.update_status_bar()

    def load_initial_tail(self) -> None:
        path = self.file_path
        if not path or not os.path.exists(path):
            return
        try:
            size = os.path.getsize(path)
            start = max(0, size - TAIL_BYTES)
            with open(path, "rb") as f:
                f.seek(start)
                data = f.read(size - start)
        except OSError as e:
            self._incoming.append(f"[ERROR] เปิดไฟล์ไม่ได้: {e}\n")
            return

        if start > 0:
            nl = data.find(b"\n")
            if nl == -1:
                self.file_pos = size
                return
            data = data[nl + 1:]
            start += nl + 1

        last = data.rfind(b"\n")
        complete = data[: last + 1] if last != -1 else b""
        self.file_pos = start + len(complete)
        self._store(split_lines(complete.decode("utf-8", errors="replace")))
        self.rebuild_view()

    def poll_file(self) -> None:
        path = self.file_path
        if not path or not os.path.exists(path):
            return
        try:
            size = os.path.getsize(path)
            if size < self.file_pos:
                self.file_pos = 0
                self._incoming.append("[INFO] ไฟล์ถูกตัด/หมุนเวียน อ่านใหม่จากต้นไฟล์\n")
            if size == self.file_pos:
                return
            with open(path, "rb") as f:
                f.seek(self.file_pos)
                data = f.read(min(size - self.file_pos, READ_CHUNK_BYTES))
            last = data.rfind(b"\n")
            if last == -1:
                return
            complete = data[: last + 1]
            self.file_pos += len(complete)
            self._incoming.extend(split_lines(complete.decode("utf-8", errors="replace")))
        except OSError:
            pass

    def generate_demo_log(self) -> None:
        samples = [
            "INFO  Worker #1 connected to database successfully",
            "INFO  GET /api/status 200 OK (14ms)",
            "WARN  Memory usage reached 78%, running garbage collection",
            "DEBUG Payload verified: checksum=a94f02c",
            "ERROR Connection timeout while reaching upstream gateway (retry 1/3)",
            "INFO  Task queue processed 42 jobs",
        ]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._incoming.append(f"{now} {random.choice(samples)}\n")

    def _get_selected_text(self) -> str:
        try:
            text = self._view().get_selected_text()
            if text:
                return text
            search_box = self.query_one("#search-input", Input)
            if search_box.has_focus:
                return getattr(search_box, "selected_text", "") or ""
        except Exception:
            pass
        return ""

    def _copy_text(self, text: str, what: str) -> None:
        if copy_to_clipboard_cross_platform(self, text):
            self.notify(f"คัดลอก{what}แล้ว ({len(text.splitlines())} บรรทัด)", timeout=2)
        else:
            self.notify(
                "คัดลอกไม่สำเร็จ (Linux: ติดตั้ง wl-clipboard / xclip / xsel)",
                severity="error",
                timeout=4,
            )

    def on_log_view_selected(self, message: LogView.Selected) -> None:
        self._copy_text(message.text, "")

    def action_copy_selection(self) -> None:
        selected = self._get_selected_text()
        if selected:
            self._copy_text(selected, "")
        else:
            self.notify(
                "ลากเมาส์คลุมข้อความก่อน หรือกด a เพื่อคัดลอกทั้งหมด (q เพื่อออก)",
                timeout=3,
            )

    def _visible_plain_lines(self) -> list[str]:
        return [strip_ansi(clean_line(ln)) for _, ln in self.lines if self.matches_filter(ln)]

    def action_copy_all(self) -> None:
        lines = self._visible_plain_lines()
        if not lines:
            self.notify("ยังไม่มี Log ให้คัดลอก", timeout=2)
            return
        self._copy_text("\n".join(lines), "ทั้งหมด")

    def action_save_logs(self) -> None:
        lines = self._visible_plain_lines()
        if not lines:
            self.notify("ยังไม่มี Log ให้บันทึก", timeout=2)
            return
        path = os.path.abspath(f"logview_{datetime.now():%Y%m%d_%H%M%S}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as e:
            self.notify(f"บันทึกไม่สำเร็จ: {e}", severity="error", timeout=4)
            return
        self.notify(f"บันทึกแล้ว: {path}", timeout=5)

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        if not self.paused:
            self.rebuild_view()
        else:
            self.update_status_bar()

    def action_toggle_error(self) -> None:
        self.error_only = not self.error_only
        self.rebuild_view()

    def action_clear_logs(self) -> None:
        self.lines.clear()
        self._incoming.clear()
        self._view().clear()
        self.update_status_bar()

    def action_open_search(self) -> None:
        search_box = self.query_one("#search-input", Input)
        search_box.value = self.keyword
        search_box.add_class("visible")
        search_box.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.keyword = event.value.strip()
        event.input.remove_class("visible")
        self._view().focus()
        self.rebuild_view()

    def on_key(self, event) -> None:
        if event.key != "escape":
            return
        search_box = self.query_one("#search-input", Input)
        view = self._view()
        if search_box.has_focus:
            search_box.value = ""
            self.keyword = ""
            search_box.remove_class("visible")
            view.focus()
            self.rebuild_view()
            event.stop()
        elif view.has_selection or view._dragging:
            view.stop_drag()
            view.clear_selection()
            event.stop()


# ---------------------------------------------------------------- entry
def setup_piped_stdin():
    """แยกท่อ Pipe ออกจาก stdin แล้วคืนค่าคีย์บอร์ด/เมาส์ให้ Terminal (คืน stream, pipe_inode)"""
    if sys.stdin.isatty():
        return None, None
    try:
        pipe_fd = os.dup(0)
        pipe_inode = None
        if os.name != "nt":
            try:
                pipe_inode = os.fstat(pipe_fd).st_ino
            except OSError:
                pass
        piped_stream = os.fdopen(pipe_fd, "r", encoding="utf-8", errors="replace")
        tty_path = "CONIN$" if os.name == "nt" else "/dev/tty"
        tty_fd = os.open(tty_path, os.O_RDWR if os.name == "nt" else os.O_RDONLY)
        os.dup2(tty_fd, 0)
        os.close(tty_fd)
        if os.name == "nt":
            import ctypes
            import msvcrt

            ctypes.windll.kernel32.SetStdHandle(-10, msvcrt.get_osfhandle(0))
        return piped_stream, pipe_inode
    except OSError:
        return None, None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="logview",
        description="TUI Log viewer: ไฟล์ / pipe / --run / --demo",
    )
    parser.add_argument("file", nargs="?", help="ไฟล์ Log ที่ต้องการติดตามสด")
    parser.add_argument(
        "-r", "--run", nargs=argparse.REMAINDER, metavar="CMD",
        help="รันคำสั่งแล้วแสดงผล เช่น --run node app.js",
    )
    parser.add_argument("--demo", action="store_true", help="โหมดสาธิต")
    args = parser.parse_args(argv)
    if args.run is not None and not args.run:
        parser.error("--run ต้องตามด้วยคำสั่งที่จะรัน")
    return args


if __name__ == "__main__":
    cli = parse_args(sys.argv[1:])

    piped, pipe_inode = setup_piped_stdin()
    if piped and (cli.file or cli.run or cli.demo):
        piped.close()
        cleanup_pipe_writers(pipe_inode)
        piped = None
        pipe_inode = None

    try:
        LogViewerApp(
            file_path=cli.file,
            run_cmd=" ".join(cli.run) if cli.run else None,
            piped_stream=piped,
            demo=cli.demo,
        ).run()
    finally:
        cleanup_pipe_writers(pipe_inode)