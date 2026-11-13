#!/usr/bin/env python3
"""จัดการสี Log, ภาษาไทย/อีโมจิ (Grapheme), JSON Pretty-Print, Exclude Filter และ Clipboard"""
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import unicodedata
from typing import Iterator

if "NO_COLOR" not in os.environ:
    os.environ.setdefault("COLORTERM", "truecolor")
os.environ.setdefault("PYTHONUTF8", "1")

for _stream in (sys.stdout, sys.stderr):
    try:
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.cells import cell_len
from rich.text import Text
from textual.app import App

MAX_BUFFER_LINES = 2000
TAIL_BYTES = 65536
READ_CHUNK_BYTES = 4 * 1024 * 1024

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
NON_SGR_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-ln-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
WORD_RE = re.compile(r"[\w\u0E00-\u0E7F./:\-@\\]+", re.UNICODE)

TS_RE = re.compile(
    r"^(\[?\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\]?|\[?\d{2}:\d{2}:\d{2}(?:\.\d+)?\]?)\s*(.*)"
)
TAG_RE = re.compile(r"^(\[[^\]\r\n]{1,32}\])\s*(.*)")
LEVEL_RE = re.compile(
    r"^(ERR(?:OR)?|FATAL|CRITICAL|WRN|WARN(?:ING)?|INF(?:O)?|DBG|DEBUG)\b\s*(.*)",
    re.I,
)

ERROR_RE = re.compile(
    r"ERROR|EXCEPTION|\b(?:ERR|FATAL|CRITICAL|TRACEBACK|FAIL(?:ED|URE)?|ECONNREFUSED|ETIMEDOUT)\b|Bad Request|[❌🚨💥🛑]|พัง|ผิดพลาด|ล้มเหลว|ไม่สำเร็จ|เชื่อมต่อไม่ได้|หมดเวลา",
    re.I,
)
WARN_RE = re.compile(
    r"\b(?:WRN|WARN(?:ING)?|Retrying|disconnected)\b|⚠\uFE0F?|[⏳🟠🟡]|Lost connection|เตือน|ระวัง|ลองใหม่|ชั่วคราว",
    re.I,
)
OK_RE = re.compile(
    r"\b(?:SUCCESS|OK|READY|CONNECTED|LISTENING|Registered)\b|\s200\s|[✅✔✓🟢🎉]|สำเร็จ|เรียบร้อย|พร้อมใช้งาน|เชื่อมต่อแล้ว",
    re.I,
)
DEBUG_RE = re.compile(r"\b(?:DBG|DEBUG)\b", re.I)

JSON_KEY_RE = re.compile(r'("(?:\\.|[^"\\])*")\s*:')
JSON_STR_VAL_RE = re.compile(r':\s*("(?:\\.|[^"\\])*")')
JSON_PRIM_VAL_RE = re.compile(r":\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)\b")

BADGE_PALETTE = [
    "bold bright_cyan",
    "bold bright_magenta",
    "bold bright_green",
    "bold bright_yellow",
    "bold bright_blue",
    "bold white",
]


# ---------------------------------------------------------------- Thai & Emoji Grapheme Helpers
def _is_combining_or_modifier(ch: str) -> bool:
    cp = ord(ch)
    if 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF:
        return True
    if 0x1F3FB <= cp <= 0x1F3FF:
        return True
    if cp in (0x200D, 0x20E3):
        return True
    return unicodedata.category(ch) in ("Mn", "Mc", "Me")


def _is_regional_indicator(ch: str) -> bool:
    return 0x1F1E6 <= ord(ch) <= 0x1F1FF


def iter_graphemes(text: str) -> Iterator[tuple[int, int, str]]:
    """แบ่งข้อความเป็นก้อนอักขระที่แสดงผลจริง (พยัญชนะ+สระ/วรรณยุกต์ไทย และอีโมจิผสม)"""
    n = len(text)
    i = 0
    while i < n:
        start = i
        ch = text[i]
        i += 1

        if _is_regional_indicator(ch) and i < n and _is_regional_indicator(text[i]):
            i += 1
            yield start, i, text[start:i]
            continue

        while i < n:
            nxt = text[i]
            if nxt == "\u200d":
                i += 1
                if i < n:
                    i += 1
                continue
            if _is_combining_or_modifier(nxt):
                i += 1
                continue
            break

        yield start, i, text[start:i]


def snap_range_to_graphemes(plain: str, start: int, end: int) -> tuple[int, int]:
    """ปรับขอบเขตการคลุม/ไฮไลต์ให้ตรงกับก้อนอักขระ ไม่ตัดสระไทยหรืออีโมจิขาดครึ่ง"""
    if start >= end or not plain:
        return start, end
    new_start, new_end = start, end
    for g_start, g_end, _ in iter_graphemes(plain):
        if g_start <= start < g_end:
            new_start = g_start
        if g_start < end <= g_end:
            new_end = g_end
            break
    return new_start, new_end


def col_from_cell(plain: str, cell_x: int) -> int:
    """แปลงตำแหน่งคอลัมน์บนจอ (cell) เป็นตำแหน่งตัวอักษร รองรับสระซ้อนภาษาไทยและอีโมจิกว้าง 2 ช่อง"""
    if cell_x <= 0 or not plain:
        return 0
    acc = 0.0
    for g_start, g_end, cluster in iter_graphemes(plain):
        w = max(cell_len(cluster), 1) if cluster.strip() else cell_len(cluster)
        if cell_x < acc + w / 2:
            return g_start
        acc += w
    return len(plain)


def layout_rich_text_rows(text: Text, wrap_width: int | None = None) -> list[tuple[int, int, Text]]:
    """แบ่ง Rich Text เป็นบรรทัดย่อย (รองรับทั้งขึ้นบรรทัดใหม่ของ JSON และการตัดบรรทัดอัตโนมัติ)"""
    plain = text.plain
    if not plain:
        return [(0, 0, Text(" "))]

    # แยกตาม \n ก่อน (สำหรับ JSON ที่คลี่เป็นหลายบรรทัด)
    segments: list[tuple[int, int]] = []
    start = 0
    for idx, ch in enumerate(plain):
        if ch == "\n":
            segments.append((start, idx))
            start = idx + 1
    segments.append((start, len(plain)))

    rows: list[tuple[int, int, Text]] = []
    for seg_start, seg_end in segments:
        if seg_start == seg_end:
            rows.append((seg_start, seg_end, Text(" ")))
            continue
        if wrap_width is None or wrap_width <= 1:
            rows.append((seg_start, seg_end, text[seg_start:seg_end]))
            continue

        # ตัดบรรทัดตามความกว้างช่องโดยไม่ตัดสระไทยหรืออีโมจิขาดครึ่ง
        sub_plain = plain[seg_start:seg_end]
        cur_start = seg_start
        cur_w = 0
        for g_s, g_e, cluster in iter_graphemes(sub_plain):
            abs_s = seg_start + g_s
            abs_e = seg_start + g_e
            w = max(cell_len(cluster), 1) if cluster.strip() else cell_len(cluster)
            if cur_w + w > wrap_width and cur_start < abs_s:
                rows.append((cur_start, abs_s, text[cur_start:abs_s]))
                cur_start = abs_s
                cur_w = 0
            cur_w += w
        if cur_start < seg_end:
            rows.append((cur_start, seg_end, text[cur_start:seg_end]))

    return rows or [(0, len(plain), text)]


# ---------------------------------------------------------------- Filter & JSON Helpers
def parse_filter_query(query: str) -> tuple[list[str], list[str]]:
    """แยกคำค้นหาปกติ (includes) และคำที่ขึ้นต้นด้วย ! เพื่อซ่อน (excludes)"""
    q = query.strip()
    if not q:
        return [], []
    try:
        tokens = shlex.split(q)
    except ValueError:
        tokens = q.split()

    includes: list[str] = []
    excludes: list[str] = []
    for tok in tokens:
        if tok.startswith("!") and len(tok) > 1:
            excludes.append(tok[1:].lower())
        elif tok != "!":
            includes.append(tok.lower())
    return includes, excludes


def expand_json_in_text(clean: str) -> tuple[str, bool]:
    """ตรวจจับ JSON Object/Array ในบรรทัดแล้วคลี่จัดย่อหน้าให้อ่านง่าย"""
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(clean):
        if ch not in "{[":
            continue
        try:
            parsed, end_idx = decoder.raw_decode(clean, idx)
        except Exception:
            continue
        if isinstance(parsed, (dict, list)) and len(parsed) > 0 and (end_idx - idx) >= 12:
            pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
            prefix_part = clean[:idx].rstrip()
            suffix_part = clean[end_idx:].strip()
            combined = f"{prefix_part}\n{pretty}" if prefix_part else pretty
            if suffix_part:
                combined = f"{combined}\n{suffix_part}"
            return combined, True
    return clean, False


def _style_json_block(text: Text, start_offset: int) -> None:
    """ลงสี Key, String และตัวเลข/Boolean ในบล็อก JSON"""
    plain = text.plain
    sub = plain[start_offset:]
    for m in JSON_KEY_RE.finditer(sub):
        text.stylize("bold bright_cyan", start_offset + m.start(1), start_offset + m.end(1))
    for m in JSON_STR_VAL_RE.finditer(sub):
        text.stylize("green", start_offset + m.start(1), start_offset + m.end(1))
    for m in JSON_PRIM_VAL_RE.finditer(sub):
        text.stylize("bold bright_yellow", start_offset + m.start(1), start_offset + m.end(1))


# ---------------------------------------------------------------- Text & Log Styling
def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def clean_line(raw: str) -> str:
    line = raw.rstrip("\r\n")
    if "\r" in line:
        line = line.rsplit("\r", 1)[-1]
    line = line.replace("\t", "    ").replace("\x00", "")
    return "".join(
        ch for ch in line if ch in ("\x1b", "\n") or unicodedata.category(ch) != "Cc"
    )


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


def _highlight_keywords_unicode(text: Text, include_terms: list[str]) -> None:
    plain = text.plain
    if not plain or not include_terms:
        return
    for term in include_terms:
        if not term:
            continue
        for match in re.finditer(re.escape(term), plain, flags=re.IGNORECASE):
            s, e = snap_range_to_graphemes(plain, match.start(), match.end())
            if e > s:
                text.stylize("bold black on yellow", s, e)


def style_log_line(
    raw_line: str,
    include_terms: list[str] | None = None,
    prefix: str = "",
    prefix_style: str = "bold cyan",
    pretty_json: bool = False,
) -> Text:
    """ลงสี Log อัตโนมัติ รองรับภาษาไทย อีโมจิ JSON Pretty-Print และป้ายชื่อแหล่งที่มา"""
    clean = clean_line(raw_line)
    json_expanded = False
    if pretty_json:
        plain_for_json = strip_ansi(clean)
        expanded, ok = expand_json_in_text(plain_for_json)
        if ok:
            clean = expanded
            json_expanded = True

    text = Text()
    if prefix:
        text.append(f"[{prefix}] ", style=prefix_style)

    body_start = len(text.plain)

    if "\x1b[" in clean and not json_expanded:
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
            text.append(rest, style="white" if json_expanded else _classify_body_style(rest))

        if json_expanded:
            _style_json_block(text, body_start)

    if not text.plain.strip():
        return Text(" ")

    if include_terms:
        _highlight_keywords_unicode(text, include_terms)
    return text


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
            encoding="utf-8",
            errors="replace",
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
    tokens = cmd.strip().split()
    if len(tokens) < 2 or tokens[0] != "pm2" or tokens[1] not in ("logs", "log"):
        return False
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