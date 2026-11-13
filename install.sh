#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[1/5] ติดตั้งแพ็กเกจระบบ (Clipboard + ฟอนต์ไทย/อีโมจิ + xdg-utils)..."
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3-venv xclip xdg-utils fonts-noto-color-emoji fonts-thai-tlwg
fi

echo "[2/5] สร้างสภาพแวดล้อม Python และติดตั้ง requirements.txt..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "[3/5] สร้างคำสั่งลัดกลาง /usr/local/bin/logview..."
sudo tee /usr/local/bin/logview > /dev/null << EOF
#!/usr/bin/env bash
exec "$APP_DIR/.venv/bin/python" "$APP_DIR/logview.py" "\$@"
EOF
sudo chmod +x /usr/local/bin/logview

echo "[4/5] ตั้งค่า LogViewer เป็นโปรแกรมเริ่มต้นสำหรับเปิดไฟล์ .log..."
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/logview.desktop" << EOF
[Desktop Entry]
Name=LogViewer (TUI)
Comment=Real-time TUI Log Viewer
Exec=/usr/local/bin/logview %F
Icon=utilities-terminal
Terminal=true
Type=Application
Categories=Utility;System;Monitor;
MimeType=text/x-log;application/x-log;
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi
if command -v xdg-mime >/dev/null 2>&1; then
    xdg-mime default logview.desktop text/x-log
    xdg-mime default logview.desktop application/x-log
fi

echo "[5/5] ตั้งค่าให้คำสั่ง pm2 logs เปิดผ่าน LogViewer อัตโนมัติ..."
BASHRC="$HOME/.bashrc"
touch "$BASHRC"
if ! grep -q "# >>> logview-pm2-hook >>>" "$BASHRC"; then
    cat >> "$BASHRC" << 'EOF'

# >>> logview-pm2-hook >>>
pm2() {
    if [[ "$1" == "logs" || "$1" == "log" ]] && [[ -t 1 ]] && command -v logview >/dev/null 2>&1; then
        shift
        local has_target=0
        for arg in "$@"; do
            [[ "$arg" != -* ]] && has_target=1 && break
        done
        if [[ $has_target -eq 0 ]]; then
            logview --pm2
        else
            logview -r "pm2 logs $* --raw"
        fi
    else
        command pm2 "$@"
    fi
}
# <<< logview-pm2-hook <<<
EOF
fi

echo "✅ ติดตั้งและตั้งค่าเริ่มต้นเสร็จสมบูรณ์! (พิมพ์ source ~/.bashrc หรือเปิด Terminal ใหม่เพื่อเริ่มใช้งาน)"