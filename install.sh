#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[1/3] ติดตั้งแพ็กเกจระบบ (Clipboard + ฟอนต์ไทย/อีโมจิ)..."
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3-venv xclip fonts-noto-color-emoji fonts-thai-tlwg
fi

echo "[2/3] สร้างสภาพแวดล้อม Python และติดตั้ง requirements.txt..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "[3/3] สร้างคำสั่งลัดกลาง /usr/local/bin/logview..."
sudo tee /usr/local/bin/logview > /dev/null << EOF
#!/usr/bin/env bash
exec "$APP_DIR/.venv/bin/python" "$APP_DIR/logview.py" "\$@"
EOF
sudo chmod +x /usr/local/bin/logview

echo "✅ ติดตั้งเสร็จสมบูรณ์! พิมพ์คำสั่ง logview เพื่อใช้งานได้ทันที"