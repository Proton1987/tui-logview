#!/usr/bin/env python3
"""จัดการสี Log, ข้อความ, Clipboard ข้ามระบบ และค้นหาโปรเซส PM2"""
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time

if "NO_COLOR" not in os.environ:
    os.environ.setdefault("COLORTERM", "truecolor")

from rich.cells import cell_len
from rich.text import Text
from textual.app import App

MAX_BUFFER_LINES = 2000
TAIL_BYTES = 65536
READ_CHUNK_BYTES = 4 * 1024 * 1024

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
NON_SGR_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-ln-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
WORD_RE = re.compile(r"[\w./:\-@\\]+", re.UNICODE)

TS_RE = re.compile(
    r"^(\[?\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\]?|\[?\d{2}:\d{2}:\d{2}(?:\.\d+)?\]?)\s*(.*)"
)
TAG_RE = re.compile(r"^(\[[^\]\r\n]{1,32}\])\s*(.*)")
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

BADGE_PALETTE = [
    "bold bright_cyan",
    "bold bright_magenta",
    "bold bright_green",
    "bold bright_yellow",
    "bold bright_blue",
    "bold white",
]


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


def style_log_line(
    raw_line: str,
    keyword: str = "",
    prefix: str = "",
    prefix_style: str = "bold cyan",
) -> Text:
    """ลงสี Log อัตโนมัติ พร้อมใส่ป้ายชื่อแหล่งที่มาได้เมื่อดูรวมหลายตัว"""
    clean = clean_line(raw_line)
    text = Text()

    if prefix:
        text.append(f"[{prefix}] ", style=prefix_style)

    if "\x1b[" in clean:
        text.append_text(Text.from_ansi(NON_SGR_RE.sub("", clean)))
    else:
        rest = clean
        ts_match = TS_RE.match(rest)
        if ts_match:
            text.append(ts_match.group(1) + " ", style="dim cyan")
            rest = ts_match.group(2)

        tag_match = TAG_RE.match(rest)
        if tag_match:
            text.append(tag_match.group(1) + " ", style="bold magenta")
            rest = tag_match.group(2)

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
    if cell_x <= 0:
        return 0
    acc = 0.0
    for i, ch in enumerate(plain):
        w = cell_len(ch)
        if cell_x < acc + w / 2:
            return i
        acc += w
    return len(plain)


# ---------------------------------------------------------------- Clipboard
def _win_set_clipboard(text: str) -> bool:
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


# ---------------------------------------------------------------- Process & PM2 Helpers
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


def discover_pm2_apps() -> list[dict]:
    """ดึงรายชื่อโปรเซสทั้งหมดที่รันอยู่ใน PM2"""
    try:
        res = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True,
            text=True,
            timeout=2.5,
            shell=(os.name == "nt"),
        )
        if res.returncode != 0 or not res.stdout.strip():
            return []
        raw_json = res.stdout.strip()
        start_idx = raw_json.find("[")
        if start_idx == -1:
            return []
        items = json.loads(raw_json[start_idx:])
        apps = []
        for item in items:
            name = item.get("name")
            pm_id = item.get("pm_id")
            status = item.get("pm2_env", {}).get("status", "")
            if name is not None:
                apps.append({"id": pm_id, "name": str(name), "status": status})
        return apps
    except Exception:
        return []


def is_generic_pm2_logs_cmd(cmd: str) -> bool:
    """เช็กว่าเป็นคำสั่งดู PM2 แบบรวมทุกตัว (เช่น 'pm2 logs' หรือ 'pm2 logs --raw') หรือไม่"""
    tokens = cmd.strip().split()
    if len(tokens) < 2 or tokens[0] != "pm2" or tokens[1] not in ("logs", "log"):
        return False
    # ถ้าหลังคำว่า logs ไม่มีชื่อโปรเซส (มีแต่ option ที่ขึ้นต้นด้วย - หรือว่างเปล่า)
    rest = tokens[2:]
    return all(t.startswith("-") for t in rest)


def infer_source_name(kind: str, target: str) -> str:
    if kind == "file":
        return os.path.basename(target) or target
    if kind == "run":
        tokens = target.strip().split()
        if len(tokens) >= 3 and tokens[0] == "pm2" and tokens[1] in ("logs", "log"):
            for t in tokens[2:]:
                if not t.startswith("-"):
                    return t
        if len(tokens) >= 2 and tokens[0] in ("node", "python", "python3", "npm", "yarn"):
            return os.path.basename(tokens[-1])
        return target[:24]
    return target