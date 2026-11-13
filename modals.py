#!/usr/bin/env python3
"""หน้าต่าง Pop-up เลือกรูปแบบการแบ่งหน้าจอ"""
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class LayoutSelectModal(ModalScreen[str]):
    """กล่องสี่เหลี่ยมเด้งถามผู้ใช้ว่าจะแบ่งช่องหรือรวมหน้าจอเดียว"""

    CSS = """
    LayoutSelectModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.65);
    }
    #layout-dialog {
        width: 62;
        height: auto;
        border: double $accent;
        background: $surface;
        padding: 1 2;
    }
    #dialog-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #dialog-desc {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }
    .layout-btn {
        width: 100%;
        margin-bottom: 1;
    }
    #dialog-hint {
        text-align: center;
        color: $text-disabled;
        margin-top: 1;
    }
    """

    def __init__(self, source_names: list[str], current_mode: str = "grid4") -> None:
        super().__init__()
        self.source_names = source_names
        self.current_mode = current_mode

    def compose(self) -> ComposeResult:
        count = len(self.source_names)
        preview = ", ".join(self.source_names[:4])
        if count > 4:
            preview += f" (+อีก {count - 4})"

        with Vertical(id="layout-dialog"):
            yield Static(f"ตรวจพบ Log หลายแหล่ง ({count} รายการ)", id="dialog-title")
            yield Static(f"รายการ: {preview}", id="dialog-desc")
            yield Button(
                "[1] แบ่งหน้าจอ 4 ช่อง (Grid 2x2) — แยกดูอิสระ",
                id="btn-grid4",
                variant="primary",
                classes="layout-btn",
            )
            yield Button(
                f"[2] แบ่งช่องตามจำนวน ({min(count, 4)} ช่องอัตโนมัติ)",
                id="btn-auto",
                variant="default",
                classes="layout-btn",
            )
            yield Button(
                "[3] รวมหน้าจอเดียว (Combined 1 ช่อง)",
                id="btn-single",
                variant="default",
                classes="layout-btn",
            )
            yield Static("กดเลข 1-3 หรือคลิกเลือก (กด G หรือ L เพื่อเปลี่ยนทีหลังได้ตลอด)", id="dialog-hint")

    def on_mount(self) -> None:
        self.query_one("#btn-grid4", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-grid4":
            self.dismiss("grid4")
        elif btn_id == "btn-auto":
            self.dismiss("auto")
        else:
            self.dismiss("single")

    def on_key(self, event: events.Key) -> None:
        if event.key == "1":
            self.dismiss("grid4")
            event.stop()
        elif event.key == "2":
            self.dismiss("auto")
            event.stop()
        elif event.key == "3":
            self.dismiss("single")
            event.stop()
        elif event.key == "escape":
            self.dismiss(self.current_mode)
            event.stop()