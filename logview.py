#!/usr/bin/env python3
"""LogViewer - TUI ดู Log สด (รองรับภาษาไทย/อีโมจิ, แบ่ง 4 ช่อง และรวมจากหลาย Terminal)"""
import argparse
import os
import random
import socket
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Footer, Header, Input

from ipc_bridge import IPCServer, try_forward_to_existing
from log_parser import (
    BADGE_PALETTE,
    ERROR_RE,
    MAX_BUFFER_LINES,
    READ_CHUNK_BYTES,
    TAIL_BYTES,
    cleanup_pipe_writers,
    copy_to_clipboard_cross_platform,
    discover_pm2_apps,
    infer_source_name,
    is_generic_pm2_logs_cmd,
    split_lines,
    strip_ansi,
    style_log_line,
    terminate_process_tree,
)
from log_widget import LogPane, LogView, StatusBar
from modals import LayoutSelectModal

DRAIN_INTERVAL = 0.1
INCOMING_LIMIT = 100_000


@dataclass
class SourceStream:
    source_id: str
    name: str
    kind: str  # "file" | "run" | "pipe" | "ipc_pipe" | "demo"
    target: str = ""
    cwd: str = ""
    color_style: str = "bold bright_cyan"
    lines: deque[tuple[int, str]] = field(default_factory=lambda: deque(maxlen=MAX_BUFFER_LINES))
    incoming: deque[str] = field(default_factory=lambda: deque(maxlen=INCOMING_LIMIT))
    file_pos: int = 0
    proc: subprocess.Popen | None = None
    proc_gen: int = 0
    sock: socket.socket | None = None
    active: bool = True


class LogViewerApp(App):
    CSS = """
    #status-bar {
        height: 1;
        background: $boost;
        color: $text;
        padding: 0 1;
    }
    #workspace {
        height: 1fr;
        background: $surface;
    }
    LogPane {
        border: round $primary-darken-2;
        background: $surface;
    }
    LogPane.focused-pane {
        border: round $accent;
    }
    LogPane.no-border {
        border: none;
    }
    .pane-header {
        height: 1;
        background: $boost;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }
    LogPane.focused-pane .pane-header {
        background: $accent-darken-2;
        color: #ffffff;
    }
    .pane-logview {
        height: 1fr;
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
        Binding("l", "open_layout_modal", "Layout"),
        Binding("g", "toggle_grid_single", "Grid/1-View"),
        Binding("z", "toggle_zoom", "Zoom"),
        Binding("tab", "next_pane", "Next Pane", show=False),
        Binding("1", "focus_pane_1", "Pane 1", show=False),
        Binding("2", "focus_pane_2", "Pane 2", show=False),
        Binding("3", "focus_pane_3", "Pane 3", show=False),
        Binding("4", "focus_pane_4", "Pane 4", show=False),
        Binding("r", "restart_process", "Restart"),
        Binding("x", "close_focused_source", "Close Pane", show=False),
        Binding("ctrl+c", "copy_selection", "Copy", priority=True),
        Binding("y", "copy_selection", "Copy", show=False),
        Binding("a", "copy_all", "Copy All"),
        Binding("s", "save_logs", "Save"),
        Binding("c", "clear_logs", "Clear"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        initial_specs: list[dict],
        piped_stream=None,
        demo: bool = False,
        initial_layout: str | None = None,
        enable_ipc: bool = True,
    ) -> None:
        super().__init__()
        self.initial_specs = initial_specs
        self.piped_stream = piped_stream
        self.demo_mode = demo or (not initial_specs and piped_stream is None)
        self.forced_layout = initial_layout
        self.enable_ipc = enable_ipc

        self.sources: list[SourceStream] = []
        self._source_counter = 0
        self._seq = 0
        self._combined_lines: deque[tuple[int, str, str, str]] = deque(maxlen=MAX_BUFFER_LINES)

        self.layout_mode: str = initial_layout or "single"
        self.zoomed_source_id: str | None = None
        self.focused_source_id: str | None = None

        self.paused = False
        self.error_only = False
        self.keyword = ""
        self._proc_lock = threading.Lock()
        self._ipc_server: IPCServer | None = None
        self._prompt_shown_for_count = 1

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield StatusBar("", id="status-bar")
        yield Container(id="workspace")
        yield Input(
            placeholder="พิมพ์คำค้นหา (ไทย/อังกฤษ/อีโมจิ) แล้วกด Enter (Esc เพื่อล้าง)...",
            id="search-input",
        )
        yield Footer()

    def on_mount(self) -> None:
        if self.enable_ipc:
            self._ipc_server = IPCServer(self._on_ipc_message)
            self._ipc_server.start()

        if self.initial_specs:
            for spec in self.initial_specs:
                self._create_source(
                    kind=spec["kind"],
                    target=spec["target"],
                    name=spec.get("name"),
                    cwd=spec.get("cwd", ""),
                    prompt_if_multi=False,
                )
        elif self.piped_stream is not None:
            self._create_source(
                kind="pipe",
                target="stdin",
                name="PIPE",
                stream=self.piped_stream,
                prompt_if_multi=False,
            )
        else:
            self._create_source(
                kind="demo",
                target="demo",
                name="DEMO",
                prompt_if_multi=False,
            )

        if len(self.sources) >= 2 and not self.forced_layout:
            self.layout_mode = "grid4"

        self._rebuild_workspace()
        self.set_interval(DRAIN_INTERVAL, self._drain_all_incoming)
        self.set_interval(0.2, self._poll_all_files)

        if len(self.sources) >= 2 and not self.forced_layout:
            self._prompt_shown_for_count = len(self.sources)
            self.call_after_refresh(self.action_open_layout_modal)

    def on_unmount(self) -> None:
        if self._ipc_server:
            self._ipc_server.stop()
        for src in self.sources:
            self._stop_source(src)

    # ------------------------------------------------------------ Source Management
    def _unique_name(self, base: str) -> str:
        existing = {s.name for s in self.sources}
        if base not in existing:
            return base
        idx = 2
        while f"{base}#{idx}" in existing:
            idx += 1
        return f"{base}#{idx}"

    def _create_source(
        self,
        kind: str,
        target: str,
        name: str | None = None,
        cwd: str = "",
        stream=None,
        sock: socket.socket | None = None,
        initial_bytes: bytes = b"",
        prompt_if_multi: bool = True,
    ) -> SourceStream:
        self._source_counter += 1
        sid = f"src{self._source_counter}"
        display_name = self._unique_name(name or infer_source_name(kind, target))
        badge_color = BADGE_PALETTE[(self._source_counter - 1) % len(BADGE_PALETTE)]

        src = SourceStream(
            source_id=sid,
            name=display_name,
            kind=kind,
            target=target,
            cwd=cwd,
            color_style=badge_color,
            sock=sock,
        )
        self.sources.append(src)
        if self.focused_source_id is None:
            self.focused_source_id = sid

        if kind == "run":
            self._start_subprocess_for(src)
        elif kind == "file":
            self._load_initial_tail_for(src)
        elif kind == "pipe" and stream is not None:
            threading.Thread(
                target=self._read_text_stream_worker, args=(src, stream), daemon=True
            ).start()
        elif kind == "ipc_pipe" and sock is not None:
            threading.Thread(
                target=self._read_ipc_socket_worker,
                args=(src, sock, initial_bytes),
                daemon=True,
            ).start()
        elif kind == "demo":
            self.set_interval(0.7, lambda: self._generate_demo_for(src))

        self._rebuild_workspace()

        if prompt_if_multi and len(self.sources) >= 2 and len(self.sources) > self._prompt_shown_for_count:
            self._prompt_shown_for_count = len(self.sources)
            self.action_open_layout_modal()

        return src

    def _stop_source(self, src: SourceStream) -> None:
        src.active = False
        with self._proc_lock:
            src.proc_gen += 1
            proc = src.proc
            src.proc = None
        if proc:
            terminate_process_tree(proc)
        if src.sock:
            try:
                src.sock.close()
            except Exception:
                pass
            src.sock = None

    def _on_ipc_message(self, msg: dict, conn: socket.socket | None) -> None:
        action = msg.get("action")
        if action == "file":
            path = msg.get("path", "")
            if path:
                self.call_from_thread(
                    self._handle_ipc_add, "file", path, msg.get("name"), "", None, b""
                )
        elif action == "run":
            cmd = msg.get("cmd", "")
            cwd = msg.get("cwd", "")
            if cmd:
                if is_generic_pm2_logs_cmd(cmd):
                    pm2_apps = discover_pm2_apps()
                    if pm2_apps:
                        for idx, app_info in enumerate(pm2_apps):
                            app_name = app_info["name"]
                            self.call_from_thread(
                                self._handle_ipc_add,
                                "run",
                                f"pm2 logs {app_name} --raw",
                                app_name,
                                cwd,
                                None,
                                b"",
                                idx == len(pm2_apps) - 1,
                            )
                        return
                self.call_from_thread(
                    self._handle_ipc_add, "run", cmd, msg.get("name"), cwd, None, b""
                )
        elif action == "stream_pipe" and conn is not None:
            self.call_from_thread(
                self._handle_ipc_add,
                "ipc_pipe",
                "pipe",
                msg.get("name"),
                "",
                conn,
                msg.get("_initial_bytes", b""),
            )

    def _handle_ipc_add(
        self,
        kind: str,
        target: str,
        name: str | None,
        cwd: str,
        sock: socket.socket | None,
        initial_bytes: bytes,
        prompt_if_multi: bool = True,
    ) -> None:
        src = self._create_source(
            kind=kind,
            target=target,
            name=name,
            cwd=cwd,
            sock=sock,
            initial_bytes=initial_bytes,
            prompt_if_multi=prompt_if_multi,
        )
        self.focused_source_id = src.source_id
        self._update_pane_focus_styles()
        self.notify(f"รับ Log เพิ่มเข้ามาแล้ว: {src.name}", timeout=2.5)

    # ------------------------------------------------------------ Subprocess / File / Pipe Workers
    def _start_subprocess_for(self, src: SourceStream) -> None:
        with self._proc_lock:
            src.proc_gen += 1
            gen = src.proc_gen
            old_proc = src.proc
            src.proc = None
        if old_proc:
            terminate_process_tree(old_proc)

        now = datetime.now().strftime("%H:%M:%S")
        src.incoming.append(f"[{now}] INFO  Starting: {src.target}\n")

        def _worker() -> None:
            try:
                env = os.environ.copy()
                env.setdefault("FORCE_COLOR", "1")
                env.setdefault("PYTHONUNBUFFERED", "1")
                env.setdefault("PYTHONIOENCODING", "utf-8")
                env.setdefault("PYTHONUTF8", "1")
                if os.name != "nt":
                    # ป้องกันโปรเซสลูกส่งภาษาไทย/อีโมจิเป็น ASCII ที่พังเป็น ?? หรือ 
                    if "UTF-8" not in env.get("LANG", "").upper():
                        env["LANG"] = "C.UTF-8"
                    if "UTF-8" not in env.get("LC_ALL", "").upper():
                        env["LC_ALL"] = "C.UTF-8"

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
                if src.cwd and os.path.isdir(src.cwd):
                    kwargs["cwd"] = src.cwd
                if os.name != "nt":
                    kwargs["start_new_session"] = True

                proc = subprocess.Popen(src.target, **kwargs)
                with self._proc_lock:
                    if gen != src.proc_gen or not src.active:
                        terminate_process_tree(proc)
                        return
                    src.proc = proc

                if proc.stdout:
                    for line in proc.stdout:
                        if gen != src.proc_gen or not src.active:
                            return
                        src.incoming.append(line)

                code = proc.wait()
                if gen == src.proc_gen and src.active:
                    end_time = datetime.now().strftime("%H:%M:%S")
                    level = "INFO " if code == 0 else "ERROR"
                    src.incoming.append(f"[{end_time}] {level} Process exited with code {code}\n")
            except Exception as e:
                if gen == src.proc_gen and src.active:
                    src.incoming.append(f"[ERROR] รันคำสั่งไม่สำเร็จ: {e}\n")

        threading.Thread(target=_worker, daemon=True).start()

    def _read_text_stream_worker(self, src: SourceStream, stream) -> None:
        try:
            for line in stream:
                if not src.active:
                    break
                src.incoming.append(line)
            if src.active:
                src.incoming.append("[INFO] Stream ended (EOF)\n")
        except Exception:
            pass

    def _read_ipc_socket_worker(
        self, src: SourceStream, sock: socket.socket, initial_bytes: bytes
    ) -> None:
        buf = initial_bytes
        try:
            while src.active:
                while b"\n" in buf:
                    raw_line, buf = buf.split(b"\n", 1)
                    src.incoming.append(raw_line.decode("utf-8", errors="replace") + "\n")
                chunk = sock.recv(4096)
                if not chunk:
                    if buf:
                        src.incoming.append(buf.decode("utf-8", errors="replace") + "\n")
                    break
                buf += chunk
            if src.active:
                src.incoming.append("[INFO] Remote stream closed\n")
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _load_initial_tail_for(self, src: SourceStream) -> None:
        path = src.target
        if not path or not os.path.exists(path):
            src.incoming.append(f"[WARN] กำลังรอไฟล์: {path} ...\n")
            return
        try:
            size = os.path.getsize(path)
            start = max(0, size - TAIL_BYTES)
            with open(path, "rb") as f:
                f.seek(start)
                data = f.read(size - start)
        except OSError as e:
            src.incoming.append(f"[ERROR] เปิดไฟล์ไม่ได้: {e}\n")
            return

        if start > 0:
            nl = data.find(b"\n")
            if nl == -1:
                src.file_pos = size
                return
            data = data[nl + 1 :]
            start += nl + 1

        last = data.rfind(b"\n")
        complete = data[: last + 1] if last != -1 else b""
        src.file_pos = start + len(complete)
        for raw in split_lines(complete.decode("utf-8", errors="replace")):
            self._seq += 1
            src.lines.append((self._seq, raw))
            self._combined_lines.append((self._seq, src.name, src.color_style, raw))

    def _poll_all_files(self) -> None:
        for src in self.sources:
            if src.kind != "file" or not src.active:
                continue
            path = src.target
            if not path or not os.path.exists(path):
                continue
            try:
                size = os.path.getsize(path)
                if size < src.file_pos:
                    src.file_pos = 0
                    src.incoming.append("[INFO] ไฟล์ถูกรีเซ็ต อ่านใหม่จากต้นไฟล์\n")
                if size == src.file_pos:
                    continue
                with open(path, "rb") as f:
                    f.seek(src.file_pos)
                    data = f.read(min(size - src.file_pos, READ_CHUNK_BYTES))
                last = data.rfind(b"\n")
                if last == -1:
                    continue
                complete = data[: last + 1]
                src.file_pos += len(complete)
                src.incoming.extend(split_lines(complete.decode("utf-8", errors="replace")))
            except OSError:
                pass

    def _generate_demo_for(self, src: SourceStream) -> None:
        if not src.active:
            return
        samples = [
            "INFO  ✅ เชื่อมต่อฐานข้อมูลสำเร็จ (14ms)",
            "INFO  📱 ส่งแจ้งเตือนออเดอร์ไปยังลูกค้าเรียบร้อย",
            "WARN  ⚠️ หน่วยความจำใช้งานถึง 78% กำลังเคลียร์แคช",
            "DEBUG Payload verified: checksum=a94f02c",
            "ERROR ❌ เชื่อมต่อ API ภายนอกล้มเหลว (ลองใหม่ 1/3)",
            "INFO  🚀 ประมวลผลคิวงานสำเร็จ 42 รายการ",
        ]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        src.incoming.append(f"{now} {random.choice(samples)}\n")

    # ------------------------------------------------------------ Layout & Rendering
    def _is_multi_pane(self) -> bool:
        return (
            len(self.sources) >= 2
            and self.layout_mode in ("grid4", "auto")
            and self.zoomed_source_id is None
        )

    def _visible_sources(self) -> list[SourceStream]:
        if not self.sources:
            return []
        if self.zoomed_source_id:
            found = [s for s in self.sources if s.source_id == self.zoomed_source_id]
            if found:
                return found
            self.zoomed_source_id = None

        if self.layout_mode == "grid4":
            return self.sources[:4]
        return self.sources

    def _rebuild_workspace(self) -> None:
        workspace = self.query_one("#workspace", Container)
        workspace.remove_children()

        if not self.sources:
            self.update_status_bar()
            return

        if not self._is_multi_pane():
            workspace.styles.layout = "vertical"
            if self.zoomed_source_id:
                src = self._visible_sources()[0]
                pane = LogPane(
                    pane_id=src.source_id,
                    title=f"[ZOOM] {src.name} (กด Z เพื่อกลับไปแบ่งช่อง)",
                    show_header=True,
                )
                workspace.mount(pane)
                items = [
                    self._make_item(seq, raw, prefix="")
                    for seq, raw in src.lines
                    if self.matches_filter(raw)
                ]
                pane.log_view.set_items(items)
                pane.log_view.focus()
            else:
                pane = LogPane(pane_id="combined", title="Combined", show_header=False, classes="no-border")
                workspace.mount(pane)
                show_badge = len(self.sources) >= 2
                items = [
                    self._make_item(
                        seq,
                        raw,
                        prefix=sname if show_badge else "",
                        prefix_style=scolor,
                    )
                    for seq, sname, scolor, raw in self._combined_lines
                    if self.matches_filter(raw)
                ]
                pane.log_view.set_items(items)
                pane.log_view.focus()
        else:
            visible = self._visible_sources()
            count = len(visible)
            cols = 2
            rows = 1 if count <= 2 else (2 if count <= 4 else (count + 1) // 2)

            workspace.styles.layout = "grid"
            workspace.styles.grid_size_columns = cols
            workspace.styles.grid_size_rows = rows
            workspace.styles.grid_gutter = (0, 1)

            panes: list[LogPane] = []
            for idx, src in enumerate(visible, start=1):
                cls = "focused-pane" if src.source_id == self.focused_source_id else ""
                pane = LogPane(
                    pane_id=src.source_id,
                    title=f"[{idx}] {src.name} ({len(src.lines)} lines)",
                    show_header=True,
                    classes=cls,
                )
                panes.append(pane)

            workspace.mount_all(panes)
            for src, pane in zip(visible, panes):
                items = [
                    self._make_item(seq, raw, prefix="")
                    for seq, raw in src.lines
                    if self.matches_filter(raw)
                ]
                pane.log_view.set_items(items)

            active_pane = self._get_focused_pane()
            if active_pane:
                active_pane.log_view.focus()

        self.update_status_bar()

    def _get_focused_source(self) -> SourceStream | None:
        if not self.sources:
            return None
        for s in self.sources:
            if s.source_id == self.focused_source_id:
                return s
        self.focused_source_id = self.sources[0].source_id
        return self.sources[0]

    def _get_focused_pane(self) -> LogPane | None:
        if not self._is_multi_pane():
            panes = list(self.query(LogPane))
            return panes[0] if panes else None
        if self.focused_source_id:
            try:
                return self.query_one(f"#view-{self.focused_source_id}", LogView).parent  # type: ignore
            except Exception:
                pass
        panes = list(self.query(LogPane))
        return panes[0] if panes else None

    def _update_pane_focus_styles(self) -> None:
        if not self._is_multi_pane():
            return
        for pane in self.query(LogPane):
            if pane.pane_id == self.focused_source_id:
                pane.add_class("focused-pane")
            else:
                pane.remove_class("focused-pane")

    def on_log_view_activated(self, event: LogView.Activated) -> None:
        if event.pane_id != "combined":
            self.focused_source_id = event.pane_id
            self._update_pane_focus_styles()
            self.update_status_bar()

    def on_log_pane_header_double_clicked(self, event: LogPane.HeaderDoubleClicked) -> None:
        self.focused_source_id = event.pane_id
        self.action_toggle_zoom()

    # ------------------------------------------------------------ Data Drain & Filter
    def matches_filter(self, line: str) -> bool:
        plain = strip_ansi(line)
        if self.error_only and not ERROR_RE.search(plain):
            return False
        if self.keyword and self.keyword.lower() not in plain.lower():
            return False
        return True

    def _make_item(
        self, seq: int, raw: str, prefix: str = "", prefix_style: str = "bold cyan"
    ) -> tuple[int, Text, str]:
        text = style_log_line(raw, self.keyword, prefix=prefix, prefix_style=prefix_style)
        plain = text.plain
        return seq, text, plain if plain.strip() else ""

    def _drain_all_incoming(self) -> None:
        any_new = False
        combined_items: list[tuple[int, Text, str]] = []
        show_badge = len(self.sources) >= 2

        for idx, src in enumerate(self.sources, start=1):
            if not src.incoming:
                continue
            batch: list[str] = []
            while True:
                try:
                    batch.append(src.incoming.popleft())
                except IndexError:
                    break
            if not batch:
                continue

            any_new = True
            per_pane_items: list[tuple[int, Text, str]] = []
            for raw in batch:
                self._seq += 1
                seq = self._seq
                src.lines.append((seq, raw))
                self._combined_lines.append((seq, src.name, src.color_style, raw))

                if not self.paused and self.matches_filter(raw):
                    if self._is_multi_pane() or self.zoomed_source_id == src.source_id:
                        per_pane_items.append(self._make_item(seq, raw, prefix=""))
                    elif not self._is_multi_pane() and not self.zoomed_source_id:
                        combined_items.append(
                            self._make_item(
                                seq,
                                raw,
                                prefix=src.name if show_badge else "",
                                prefix_style=src.color_style,
                            )
                        )

            if self._is_multi_pane():
                try:
                    view = self.query_one(f"#view-{src.source_id}", LogView)
                    if per_pane_items:
                        view.add_items(per_pane_items)
                    pane = view.parent
                    if isinstance(pane, LogPane):
                        pane.set_header_text(f"[{idx}] {src.name} ({len(src.lines)} lines)")
                except Exception:
                    pass
            elif self.zoomed_source_id == src.source_id and per_pane_items:
                try:
                    self.query_one(f"#view-{src.source_id}", LogView).add_items(per_pane_items)
                except Exception:
                    pass

        if not self._is_multi_pane() and not self.zoomed_source_id and combined_items:
            try:
                self.query_one("#view-combined", LogView).add_items(combined_items)
            except Exception:
                pass

        if any_new:
            self.update_status_bar()

    def update_status_bar(self) -> None:
        state = "⏸ PAUSED" if self.paused else "● LIVE"
        if self.zoomed_source_id:
            layout_tag = " [ZOOM]"
        elif len(self.sources) >= 2:
            layout_tag = " [GRID]" if self.layout_mode in ("grid4", "auto") else " [1-VIEW]"
        else:
            layout_tag = ""

        mode = " [ERROR ONLY]" if self.error_only else ""
        filt = f" | Filter: '{self.keyword}'" if self.keyword else ""
        focus_src = self._get_focused_source()
        focus_info = f" | Active: {focus_src.name}" if (focus_src and len(self.sources) >= 2) else ""
        total_lines = sum(len(s.lines) for s in self.sources)
        total = f" | Sources: {len(self.sources)} ({total_lines} lines)"
        try:
            self.query_one("#status-bar", StatusBar).update(
                f"{state}{layout_tag}{mode}{filt}{focus_info}{total}"
            )
        except Exception:
            pass

        if len(self.sources) >= 2:
            self.title = f"LogViewer ({len(self.sources)} sources)"
        elif self.sources:
            self.title = f"LogViewer - {self.sources[0].name}"

    # ------------------------------------------------------------ Actions & Keybindings
    def action_open_layout_modal(self) -> None:
        if len(self.sources) < 2:
            self.notify("ต้องมี Log อย่างน้อย 2 ตัวขึ้นไปจึงจะแบ่งช่องได้", timeout=2)
            return
        names = [s.name for s in self.sources]
        self.push_screen(LayoutSelectModal(names, self.layout_mode), callback=self._apply_layout_choice)

    def _apply_layout_choice(self, choice: str | None) -> None:
        if not choice:
            return
        self.zoomed_source_id = None
        self.layout_mode = choice
        self._rebuild_workspace()

    def action_toggle_grid_single(self) -> None:
        if len(self.sources) < 2:
            self.notify("มี Log เพียง 1 ตัว (เปิดเพิ่มจากอีก Terminal หรือใช้ --pm2 เพื่อแบ่งช่อง)", timeout=2.5)
            return
        self.zoomed_source_id = None
        self.layout_mode = "single" if self.layout_mode in ("grid4", "auto") else "grid4"
        self._rebuild_workspace()

    def action_toggle_zoom(self) -> None:
        if len(self.sources) < 2:
            return
        if self.zoomed_source_id:
            self.zoomed_source_id = None
        else:
            src = self._get_focused_source()
            if src:
                self.zoomed_source_id = src.source_id
        self._rebuild_workspace()

    def _focus_pane_index(self, idx: int) -> None:
        visible = self._visible_sources()
        if 0 <= idx < len(visible):
            self.focused_source_id = visible[idx].source_id
            self._update_pane_focus_styles()
            try:
                self.query_one(f"#view-{self.focused_source_id}", LogView).focus()
            except Exception:
                pass
            self.update_status_bar()

    def action_focus_pane_1(self) -> None:
        self._focus_pane_index(0)

    def action_focus_pane_2(self) -> None:
        self._focus_pane_index(1)

    def action_focus_pane_3(self) -> None:
        self._focus_pane_index(2)

    def action_focus_pane_4(self) -> None:
        self._focus_pane_index(3)

    def action_next_pane(self) -> None:
        visible = self._visible_sources()
        if len(visible) < 2:
            return
        ids = [s.source_id for s in visible]
        cur = ids.index(self.focused_source_id) if self.focused_source_id in ids else 0
        self._focus_pane_index((cur + 1) % len(visible))

    def action_close_focused_source(self) -> None:
        if len(self.sources) <= 1:
            self.notify("เหลือ Log ช่องสุดท้ายแล้ว (กด q เพื่อปิดโปรแกรม)", timeout=2)
            return
        src = self._get_focused_source()
        if not src:
            return
        self._stop_source(src)
        self.sources = [s for s in self.sources if s.source_id != src.source_id]
        if self.zoomed_source_id == src.source_id:
            self.zoomed_source_id = None
        self.focused_source_id = self.sources[0].source_id
        self._rebuild_workspace()
        self.notify(f"ปิดช่อง {src.name} แล้ว", timeout=2)

    def action_restart_process(self) -> None:
        if self._is_multi_pane() or self.zoomed_source_id:
            src = self._get_focused_source()
            if src and src.kind == "run":
                self.notify(f"กำลังรีสตาร์ท {src.name}...", timeout=1.5)
                self._start_subprocess_for(src)
                return
        run_sources = [s for s in self.sources if s.kind == "run"]
        if not run_sources:
            self.notify('ปุ่ม R ใช้ได้เฉพาะโหมด --run "คำสั่ง"', timeout=2)
            return
        self.notify(f"กำลังรีสตาร์ท {len(run_sources)} โปรเซส...", timeout=1.5)
        for src in run_sources:
            self._start_subprocess_for(src)

    # ------------------------------------------------------------ Selection & Clipboard
    def _get_selected_text(self) -> str:
        try:
            search_box = self.query_one("#search-input", Input)
            if search_box.has_focus:
                return getattr(search_box, "selected_text", "") or ""
            for view in self.query(LogView):
                text = view.get_selected_text()
                if text:
                    return text
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
            self.notify("ลากเมาส์คลุมข้อความก่อน หรือกด a เพื่อคัดลอกทั้งหมด", timeout=2.5)

    def _active_plain_lines(self) -> list[str]:
        if self._is_multi_pane() or self.zoomed_source_id:
            src = self._get_focused_source()
            if not src:
                return []
            return [
                strip_ansi(ln.rstrip("\r\n"))
                for _, ln in src.lines
                if self.matches_filter(ln)
            ]
        return [
            f"[{sname}] {strip_ansi(ln.rstrip(chr(13) + chr(10)))}"
            if len(self.sources) >= 2
            else strip_ansi(ln.rstrip("\r\n"))
            for _, sname, _, ln in self._combined_lines
            if self.matches_filter(ln)
        ]

    def action_copy_all(self) -> None:
        lines = self._active_plain_lines()
        if not lines:
            self.notify("ยังไม่มี Log ให้คัดลอก", timeout=2)
            return
        self._copy_text("\n".join(lines), "ทั้งหมด")

    def action_save_logs(self) -> None:
        lines = self._active_plain_lines()
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
        self.notify(f"บันทึกแล้ว: {path}", timeout=4)

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        if not self.paused:
            self._rebuild_workspace()
        else:
            self.update_status_bar()

    def action_toggle_error(self) -> None:
        self.error_only = not self.error_only
        self._rebuild_workspace()

    def action_clear_logs(self) -> None:
        if self._is_multi_pane() or self.zoomed_source_id:
            src = self._get_focused_source()
            if src:
                src.lines.clear()
                src.incoming.clear()
        else:
            for src in self.sources:
                src.lines.clear()
                src.incoming.clear()
            self._combined_lines.clear()
        self._rebuild_workspace()

    def action_open_search(self) -> None:
        search_box = self.query_one("#search-input", Input)
        search_box.value = self.keyword
        search_box.add_class("visible")
        search_box.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.keyword = event.value.strip()
        event.input.remove_class("visible")
        self._rebuild_workspace()

    def on_key(self, event: events.Key) -> None:
        if event.key != "escape":
            return
        search_box = self.query_one("#search-input", Input)
        if search_box.has_focus:
            search_box.value = ""
            self.keyword = ""
            search_box.remove_class("visible")
            self._rebuild_workspace()
            event.stop()
            return
        for view in self.query(LogView):
            if view.has_selection or view._dragging:
                view.stop_drag()
                view.clear_selection()
                event.stop()
                return


# ---------------------------------------------------------------- Entry & CLI
def setup_piped_stdin():
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
        description="TUI Log Viewer (รองรับภาษาไทย/อีโมจิ, แบ่ง 4 ช่อง และรวมจากหลาย Terminal)",
    )
    parser.add_argument("files", nargs="*", help="ไฟล์ Log ที่ต้องการเปิด (ระบุได้หลายไฟล์)")
    parser.add_argument(
        "-r",
        "--run",
        nargs="+",
        action="append",
        metavar="CMD",
        help='รันคำสั่งแล้วแสดงผล (ใส่ได้หลายครั้ง เช่น -r "cmd1" -r "cmd2")',
    )
    parser.add_argument("--pm2", action="store_true", help="ดึงโปรเซสทั้งหมดจาก PM2 มาแสดงพร้อมกัน")
    parser.add_argument(
        "--layout",
        choices=["grid4", "auto", "single"],
        default=None,
        help="กำหนดรูปแบบหน้าจอทันทีโดยไม่ต้องถาม (grid4 / auto / single)",
    )
    parser.add_argument("--new", action="store_true", help="บังคับเปิดหน้าต่างใหม่แยกต่างหาก")
    parser.add_argument("--demo", action="store_true", help="โหมดสาธิต")
    return parser.parse_args(argv)


def build_initial_specs(cli: argparse.Namespace) -> list[dict]:
    specs: list[dict] = []
    cwd = os.getcwd()

    if cli.pm2:
        pm2_apps = discover_pm2_apps()
        for app_info in pm2_apps:
            app_name = app_info["name"]
            specs.append(
                {
                    "kind": "run",
                    "target": f"pm2 logs {app_name} --raw",
                    "name": app_name,
                    "cwd": cwd,
                }
            )

    if cli.run:
        for cmd_tokens in cli.run:
            cmd = " ".join(cmd_tokens).strip()
            if not cmd:
                continue
            if is_generic_pm2_logs_cmd(cmd):
                pm2_apps = discover_pm2_apps()
                if pm2_apps:
                    for app_info in pm2_apps:
                        app_name = app_info["name"]
                        specs.append(
                            {
                                "kind": "run",
                                "target": f"pm2 logs {app_name} --raw",
                                "name": app_name,
                                "cwd": cwd,
                            }
                        )
                    continue
            specs.append({"kind": "run", "target": cmd, "cwd": cwd})

    for fpath in cli.files:
        abs_path = os.path.abspath(fpath)
        specs.append({"kind": "file", "target": abs_path, "name": os.path.basename(abs_path)})

    return specs


if __name__ == "__main__":
    cli = parse_args(sys.argv[1:])
    specs = build_initial_specs(cli)

    has_pipe = not sys.stdin.isatty() and not specs and not cli.demo

    if not cli.new and not cli.demo:
        ipc_payloads = []
        for s in specs:
            if s["kind"] == "file":
                ipc_payloads.append({"action": "file", "path": s["target"], "name": s["name"]})
            elif s["kind"] == "run":
                ipc_payloads.append(
                    {
                        "action": "run",
                        "cmd": s["target"],
                        "name": s.get("name"),
                        "cwd": s.get("cwd", ""),
                    }
                )

        if has_pipe:
            if try_forward_to_existing([], piped_stream=sys.stdin):
                sys.exit(0)
        elif ipc_payloads:
            if try_forward_to_existing(ipc_payloads):
                print(f"ส่ง Log ({len(ipc_payloads)} รายการ) เข้าไปยังหน้าต่าง LogViewer ที่เปิดอยู่แล้ว")
                sys.exit(0)

    piped, pipe_inode = setup_piped_stdin()
    if piped and (specs or cli.demo):
        piped.close()
        cleanup_pipe_writers(pipe_inode)
        piped = None
        pipe_inode = None

    try:
        LogViewerApp(
            initial_specs=specs,
            piped_stream=piped,
            demo=cli.demo,
            initial_layout=cli.layout,
            enable_ipc=not cli.new,
        ).run()
    finally:
        cleanup_pipe_writers(pipe_inode)