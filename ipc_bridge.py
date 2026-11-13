#!/usr/bin/env python3
"""ระบบเชื่อมต่อข้าม Terminal (เปิด logview จากหน้าต่างอื่นให้เด้งมารวมในหน้าต่างที่เปิดอยู่)"""
import hmac
import json
import os
import secrets
import socket
import threading
from typing import Callable

STATE_FILE = os.path.join(os.path.expanduser("~"), ".logview_ipc.json")


def _read_state() -> dict | None:
    try:
        if not os.path.exists(STATE_FILE):
            return None
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_state(port: int, token: str) -> None:
    data = {"pid": os.getpid(), "port": port, "token": token}
    try:
        # สิทธิ์ 600: token นี้สั่งรันคำสั่งบนเครื่องได้ ห้ามให้ผู้ใช้อื่นอ่าน
        fd = os.open(STATE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        if os.name != "nt":
            os.chmod(STATE_FILE, 0o600)
    except Exception:
        pass


def remove_state_if_owner() -> None:
    state = _read_state()
    if state and state.get("pid") == os.getpid():
        try:
            os.remove(STATE_FILE)
        except OSError:
            pass


def try_forward_to_existing(payloads: list[dict], piped_stream=None) -> bool:
    """เช็กว่ามีหน้าต่าง logview เปิดอยู่แล้วหรือไม่ ถ้ามีให้ส่งคำสั่ง/ไฟล์/ท่อ Pipe เข้าไปรวมทันที"""
    state = _read_state()
    if not state:
        return False

    port = state.get("port")
    token = state.get("token")
    pid = state.get("pid")
    if not port or not token or pid == os.getpid():
        return False

    # 1. ส่งรายการไฟล์หรือคำสั่ง (--run)
    for item in payloads:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.4) as sock:
                msg = {"token": token, **item}
                sock.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
                ack = sock.recv(1024).decode("utf-8", errors="replace")
                if '"ok": true' not in ack and '"ok":true' not in ack:
                    return False
        except Exception:
            return False

    # 2. ถ้าเปิดแบบต่อท่อ Pipe (เช่น cmd | logview) ให้ส่งข้อความสดข้ามไปเรื่อยๆ จนจบ
    if piped_stream is not None:
        try:
            sock = socket.create_connection(("127.0.0.1", int(port)), timeout=0.5)
            header = {
                "token": token,
                "action": "stream_pipe",
                "name": f"pipe-{os.getpid()}",
            }
            sock.sendall((json.dumps(header, ensure_ascii=False) + "\n").encode("utf-8"))
            ack = sock.recv(1024).decode("utf-8", errors="replace")
            if '"ok": true' not in ack and '"ok":true' not in ack:
                sock.close()
                return False

            print("ส่งท่อ Log ไปยังหน้าต่าง LogViewer ที่เปิดอยู่แล้ว (กด Ctrl+C เพื่อหยุดส่ง)...")
            for line in piped_stream:
                sock.sendall(line.encode("utf-8", errors="replace"))
            sock.close()
            return True
        except Exception:
            return False

    return len(payloads) > 0


class IPCServer:
    """ตัวรับคำสั่งจาก Terminal อื่นในเครื่องเดียวกัน"""

    def __init__(self, on_message: Callable[[dict, socket.socket | None], None]) -> None:
        self.on_message = on_message
        self.token = secrets.token_hex(8)
        self._sock: socket.socket | None = None
        self._running = False

    def start(self) -> None:
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", 0))
            srv.listen(16)
            port = srv.getsockname()[1]
            self._sock = srv
            self._running = True
            _write_state(port, self.token)
            threading.Thread(target=self._accept_loop, daemon=True).start()
        except Exception:
            pass

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        remove_state_if_owner()

    def _accept_loop(self) -> None:
        while self._running and self._sock:
            try:
                conn, _ = self._sock.accept()
                threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()
            except OSError:
                break

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            buf = b""
            while b"\n" not in buf and len(buf) < 65536:
                chunk = conn.recv(4096)
                if not chunk:
                    conn.close()
                    return
                buf += chunk

            line, rest = buf.split(b"\n", 1)
            msg = json.loads(line.decode("utf-8", errors="replace"))
            if not hmac.compare_digest(str(msg.get("token", "")), self.token):
                conn.close()
                return

            conn.sendall(b'{"ok": true}\n')
            action = msg.get("action")
            if action == "stream_pipe":
                # ส่งต่อ socket ให้ตัวอ่าน Stream อ่านต่อเนื่องจนกว่าอีกฝั่งจะปิด
                self.on_message({**msg, "_initial_bytes": rest}, conn)
            else:
                conn.close()
                self.on_message(msg, None)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass