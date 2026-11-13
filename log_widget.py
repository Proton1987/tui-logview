#!/usr/bin/env python3
"""วิดเจ็ตแสดง Log แบบ Virtual Scroll และระบบช่องแยก (LogPane) รองรับสระซ้อนภาษาไทยและอีโมจิ"""
import bisect
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Static

from log_parser import (
    MAX_BUFFER_LINES,
    WORD_RE,
    col_from_cell,
    snap_range_to_graphemes,
)

AUTOSCROLL_HZ = 30
AUTOSCROLL_MAX_LINES = 12
SELECTION_STYLE = "bold white on #2563eb"


class StatusBar(Static):
    allow_select = False


class PaneHeader(Static):
    allow_select = False


class LogView(ScrollView, can_focus=True):
    """พื้นที่แสดงผล Log แบบ Virtual Rendering พร้อมระบบลากคลุมข้อความ"""

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

    class Activated(Message):
        def __init__(self, pane_id: str) -> None:
            super().__init__()
            self.pane_id = pane_id

    def __init__(self, pane_id: str = "main", **kwargs) -> None:
        super().__init__(**kwargs)
        self.pane_id = pane_id
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
                plain = text.plain
                total = len(plain)
                start = c1 if row == i1 else 0
                end = c2 if row == i2 else total
                start, end = min(start, total), min(end, total)
                start, end = snap_range_to_graphemes(plain, start, end)
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
            line = self._copy[i1]
            s, e = snap_range_to_graphemes(line, c1, c2)
            return line[s:e]

        first_line = self._copy[i1]
        s1, _ = snap_range_to_graphemes(first_line, c1, len(first_line))
        last_line = self._copy[i2]
        _, e2 = snap_range_to_graphemes(last_line, 0, c2)

        parts = [first_line[s1:]]
        parts.extend(self._copy[i1 + 1 : i2])
        parts.append(last_line[:e2])
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

    def on_focus(self) -> None:
        self.post_message(self.Activated(self.pane_id))

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.post_message(self.Activated(self.pane_id))
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
                    s, e = snap_range_to_graphemes(plain, m.start(), m.end())
                    self._anchor, self._cursor = (pos[0], s), (pos[0], e)
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


class LogPane(Vertical):
    """กล่องแสดงผล 1 ช่อง (มีแถบชื่อด้านบน + พื้นที่แสดง Log ด้านล่าง)"""

    class HeaderDoubleClicked(Message):
        def __init__(self, pane_id: str) -> None:
            super().__init__()
            self.pane_id = pane_id

    def __init__(self, pane_id: str, title: str, show_header: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.pane_id = pane_id
        self.pane_title = title
        self.show_header = show_header

    def compose(self) -> ComposeResult:
        if self.show_header:
            yield PaneHeader(self.pane_title, id=f"hdr-{self.pane_id}", classes="pane-header")
        yield LogView(pane_id=self.pane_id, id=f"view-{self.pane_id}", classes="pane-logview")

    @property
    def log_view(self) -> LogView:
        return self.query_one(f"#view-{self.pane_id}", LogView)

    def set_header_text(self, text: str) -> None:
        if self.show_header:
            try:
                self.query_one(f"#hdr-{self.pane_id}", PaneHeader).update(text)
            except Exception:
                pass

    def on_click(self, event: events.Click) -> None:
        self.log_view.focus()
        if getattr(event, "chain", 1) >= 2 and event.y == 0 and self.show_header:
            self.post_message(self.HeaderDoubleClicked(self.pane_id))