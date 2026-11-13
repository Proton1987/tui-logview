<div align="center">

# 🖥️ LogViewer (`tui-logview`)

**โปรแกรมดู Log สดบน Terminal (TUI) แบบแบ่งหลายหน้าต่าง รองรับภาษาไทย อีโมจิ และรวมจอข้าม Terminal**
**A multi-pane live log viewer for the terminal (TUI) with Thai & emoji support and cross-terminal merging**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Textual](https://img.shields.io/badge/TUI-Textual-blueviolet)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

🌐 **กดที่ 🇹🇭 ไทย / 🇬🇧 English ใต้หัวข้อแต่ละหมวดเพื่อสลับภาษา** · **Click 🇹🇭 / 🇬🇧 under each heading to switch language**

</div>

---

## ✨ ภาพรวมหน้าจอ / Screen Overview

<details open>
<summary><b>🇹🇭 ไทย</b></summary>

ตัวอย่างหน้าจอโหมดแบ่ง 4 ช่อง (Grid 2x2) แต่ละช่องคือ Log หนึ่งแหล่ง แถบสถานะด้านบนบอกโหมดที่เปิดอยู่ และแถบล่างแสดงคีย์ลัด

</details>

<details>
<summary><b>🇬🇧 English</b></summary>

Example of the 4-pane layout (Grid 2x2). Each pane is one log source, the top status bar shows the active modes, and the bottom bar lists the key bindings.

</details>

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ LogViewer (4 sources)                                             09:15:42 │
│ ● LIVE [GRID] [WRAP] [JSON] [🔔] | Active: line-bot | Sources: 4           │
├─────────────────────────────────────┬──────────────────────────────────────┤
│ [1] thlive-bot (412 lines)          │ [2] line-bot (528 lines)             │
│ 09:15:40 INF ✅ เชื่อมต่อห้องสำเร็จ  │ 09:15:41 [telegram] ERR Bad Request  │
│ 09:15:41 INF 📩 ส่งข้อความเรียบร้อย  │ 09:15:42 WRN ⚠️ ลองส่งซ้ำแบบข้อความดิบ  │
├─────────────────────────────────────┼──────────────────────────────────────┤
│ [3] cf-tunnel (150 lines)           │ [4] cf-tunnel-2 (150 lines)          │
│ 09:15:30 INF Registered tunnel sin17│ 09:15:35 INF Registered tunnel bkk06 │
└─────────────────────────────────────┴──────────────────────────────────────┘
│ Space Pause/Live  / Filter  e Error Only  w Wrap  j JSON  b Alert  q Quit  │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 ความสามารถหลัก / Key Features

<details open>
<summary><b>🇹🇭 ไทย</b></summary>

* **🪟 แบ่งหน้าจอสูงสุด 4 ช่อง (`Grid 2x2`)** — เมื่อเปิด Log ตั้งแต่ 2 ตัวขึ้นไป จะมีหน้าต่างเด้งถามทันทีว่าจะ **แบ่ง 4 ช่อง**, **แบ่งตามจำนวน** หรือ **รวม 1 ช่อง** และสลับเปลี่ยนรูปแบบได้ตลอดเวลา
* **🔗 รวมหน้าต่างข้าม Terminal (Cross-Terminal IPC)** — เปิด `logview` ค้างไว้ 1 หน้าต่าง แล้วสั่งเปิดไฟล์หรือรันคำสั่งเพิ่มจากอีก Terminal ข้อมูลจะวิ่งเข้ามารวมในจอเดิมทันที ไม่เปิดหน้าต่างซ้อนให้เปลืองแรม
* **🇹🇭 รองรับภาษาไทยและอีโมจิ 100%** — จัดกลุ่มพยัญชนะ สระลอย วรรณยุกต์ และอีโมจิผสม (Grapheme Clustering) ทำให้ลากเมาส์คลุม ดับเบิลคลิก หรือค้นหาคำภาษาไทยได้แม่นยำ สระไม่แหว่งและอีโมจิไม่แตก
* **🖱️ ลากเมาส์คลุม = คัดลอกทันที** — ลากคลุมข้อความแล้วปล่อยเมาส์ ระบบจะก๊อปปี้ลง Clipboard ให้อัตโนมัติ (รองรับทั้ง Windows, Linux `xclip`/`wl-copy` และคัดลอกข้าม SSH ผ่าน OSC 52)
* **🎨 แยกสี Log อัตโนมัติ + คลี่ JSON (`j`)** — ลงสีตามระดับข้อความ (`ERR`, `WARN`, `INF`, `OK`, เวลา ISO8601, แท็ก `[...]`, คำไทย เช่น *พัง / เตือน / สำเร็จ* และอีโมจิ `❌ ⚠️ ✅`) พร้อมปุ่มคลี่ข้อความ JSON ให้อ่านง่าย
* **🔍 ค้นหาและซ่อนคำที่ไม่ต้องการ (`!`)** — กรองหาเฉพาะคำที่ต้องการ หรือพิมพ์ `!คำที่ไม่เอา` เพื่อซ่อน Log ขยะที่วิ่งถี่ๆ
* **🔔 แจ้งเตือนเมื่อเจอ Error (`b`)** — ส่งเสียงเตือนและกะพริบแถบสีแดงด้านบนทันทีเมื่อมี Error เด้งเข้ามา
* **🧹 ปิดโปรเซสสะอาดไม่ค้างทับจอ** — เมื่อกด `q` ออกจากโปรแกรม ระบบจะปิดโปรเซสลูกและโปรเซสต้นทางของท่อ Pipe (`pm2 logs` ฯลฯ) ให้อัตโนมัติ

</details>

<details>
<summary><b>🇬🇧 English</b></summary>

* **🪟 Up to 4 panes (`Grid 2x2`)** — when you open 2 or more logs, a dialog pops up asking whether to use a **4-pane grid**, **one pane per source**, or a **single combined pane**. You can switch layouts at any time.
* **🔗 Cross-terminal merging (IPC)** — keep one `logview` window open, then open more files or run more commands from another terminal. Their output flows into the existing window instantly, so you never end up with piles of stacked windows eating RAM.
* **🇹🇭 Full Thai & emoji support** — consonants, floating vowels, tone marks and composite emoji are handled as grapheme clusters, so mouse selection, double-click and searching Thai words stay accurate: no broken vowels, no split emoji.
* **🖱️ Drag to select = instant copy** — select text with the mouse and release; it is copied to the clipboard automatically (Windows, Linux `xclip`/`wl-copy`, and copying over SSH via OSC 52).
* **🎨 Automatic log colouring + JSON expand (`j`)** — colours by severity (`ERR`, `WARN`, `INF`, `OK`, ISO 8601 timestamps, `[...]` tags, Thai keywords such as *พัง / เตือน / สำเร็จ*, and emoji like `❌ ⚠️ ✅`), plus a key to expand JSON payloads into readable form.
* **🔍 Search and hide (`!`)** — show only the lines you want, or type `!word` to hide noisy log spam that scrolls too fast.
* **🔔 Error alert (`b`)** — rings the terminal bell and flashes the top status bar red the moment an error arrives.
* **🧹 Clean shutdown, no leftovers** — pressing `q` also terminates child processes and the upstream process of a pipe (`pm2 logs`, etc.), so nothing keeps writing over your screen.

</details>

---

## 📦 การติดตั้ง / Installation

<details open>
<summary><b>🇹🇭 ไทย</b></summary>

### 🐧 Linux (Debian / Ubuntu) — คำสั่งเดียวจบ

```bash
git clone https://github.com/Proton1987/tui-logview.git ~/tui-logview && bash ~/tui-logview/install.sh
```

สคริปต์ `install.sh` จะจัดการให้ครบทั้ง 5 ขั้นตอนอัตโนมัติ:
1. ติดตั้งแพ็กเกจระบบ (`python3-venv`, `xclip`, `xdg-utils`, ฟอนต์ไทย `fonts-thai-tlwg` และฟอนต์อีโมจิ `fonts-noto-color-emoji`)
2. สร้างสภาพแวดล้อม Python (`.venv`) และติดตั้ง `requirements.txt`
3. สร้างคำสั่งลัดกลาง `/usr/local/bin/logview` (เรียกใช้งานได้จากทุกโฟลเดอร์)
4. ตั้งค่าให้ **ดับเบิลคลิกไฟล์ `.log`** ใน File Manager แล้วเปิดด้วย `LogViewer` ทันที
5. ตั้งค่าให้คำสั่ง **`pm2 logs`** ใน Terminal เด้งเปิดผ่าน `LogViewer` อัตโนมัติ *(หากต้องการใช้ `pm2 logs` แบบดั้งเดิมชั่วคราว ให้พิมพ์ `command pm2 logs`)*

### 🪟 Windows

```cmd
git clone https://github.com/Proton1987/tui-logview.git
cd tui-logview
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python logview.py --demo
```

*(หากต้องการตั้งค่าดับเบิลคลิกไฟล์ `.log` บน Windows ให้สร้างไฟล์ `logview.cmd` ที่มีคำสั่ง `@"%~dp0.venv\Scripts\python.exe" "%~dp0logview.py" %*` แล้วคลิกขวาที่ไฟล์ `.log` > Open with > เลือกไฟล์ `logview.cmd`)*

</details>

<details>
<summary><b>🇬🇧 English</b></summary>

### 🐧 Linux (Debian / Ubuntu) — one command

```bash
git clone https://github.com/Proton1987/tui-logview.git ~/tui-logview && bash ~/tui-logview/install.sh
```

`install.sh` automatically performs all 5 steps:
1. Installs system packages (`python3-venv`, `xclip`, `xdg-utils`, Thai font `fonts-thai-tlwg` and emoji font `fonts-noto-color-emoji`)
2. Creates a Python virtual environment (`.venv`) and installs `requirements.txt`
3. Creates a global shortcut `/usr/local/bin/logview` (usable from any folder)
4. Makes **double-clicking a `.log` file** in your file manager open it with `LogViewer`
5. Makes the **`pm2 logs`** command in the terminal open through `LogViewer` automatically *(to use the original `pm2 logs` temporarily, type `command pm2 logs`)*

### 🪟 Windows

```cmd
git clone https://github.com/Proton1987/tui-logview.git
cd tui-logview
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python logview.py --demo
```

*(To open `.log` files by double-click on Windows, create a `logview.cmd` file containing `@"%~dp0.venv\Scripts\python.exe" "%~dp0logview.py" %*`, then right-click a `.log` file > Open with > choose `logview.cmd`.)*

</details>

---

## 💡 ตัวอย่างการใช้งานจริง / Usage Examples

<details open>
<summary><b>🇹🇭 ไทย</b></summary>

**1. ทดลองใช้งานครั้งแรก**
```bash
logview --demo
```

**2. ดูโปรเซสทั้งหมดจาก PM2 พร้อมกัน**
```bash
logview --pm2
# หรือพิมพ์คำสั่ง PM2 ตามปกติ (บน Linux ที่รัน install.sh แล้ว)
pm2 logs
```
*(โปรแกรมจะตรวจจับโปรเซสทั้งหมดใน PM2 และเด้งหน้าต่างถามว่าต้องการแบ่ง 4 ช่องหรือไม่)*

**3. ดูเฉพาะโปรเซสที่ต้องการ หรือรันคำสั่งใดๆ**
```bash
logview -r "pm2 logs line-bot --raw"
logview -r "node server.js"
logview -r "python3 bot.py"
```
*(ในโหมด `-r` สามารถกดปุ่ม **`r`** เพื่อรีสตาร์ทโปรเซสนั้นได้ทันทีโดยไม่ต้องออกจากโปรแกรม)*

**4. เปิดหลายไฟล์ หรือหลายคำสั่งพร้อมกัน**
```bash
# เปิดติดตามหลายไฟล์พร้อมกัน (เหมือน tail -f หลายจอ)
logview app1.log app2.log error.log

# เปิดรันหลายคำสั่งพร้อมกัน
logview -r "pm2 logs thlive-bot --raw" -r "pm2 logs line-bot --raw"
```

**5. รับข้อมูลจากท่อ Pipe (`|`)**
```bash
pm2 logs --raw | logview
docker logs -f my-container | logview
```

**6. เปิดเพิ่มจากอีก Terminal ให้เด้งเข้ามารวมในจอเดิม**
1. **Terminal ที่ 1:** เปิดดูตัวหลักค้างไว้
   ```bash
   logview -r "pm2 logs thlive-bot --raw"
   ```
2. **Terminal ที่ 2:** สั่งเปิดอีกตัวเพิ่มตามปกติ
   ```bash
   logview -r "pm2 logs line-bot --raw"
   ```
   > **ผลลัพธ์:** Terminal ที่ 2 จะส่งงานเข้าไปใน Terminal ที่ 1 แล้วปิดตัวเองอัตโนมัติ จากนั้น Terminal ที่ 1 จะเด้งกล่องถามว่าต้องการแบ่งหน้าจอเป็น 2/4 ช่องหรือไม่

</details>

<details>
<summary><b>🇬🇧 English</b></summary>

**1. First try**
```bash
logview --demo
```

**2. Watch every PM2 process at once**
```bash
logview --pm2
# or just type the usual PM2 command (on Linux, after running install.sh)
pm2 logs
```
*(It detects all PM2 processes and pops up a dialog asking whether to use the 4-pane layout.)*

**3. Watch one specific process, or run any command**
```bash
logview -r "pm2 logs line-bot --raw"
logview -r "node server.js"
logview -r "python3 bot.py"
```
*(In `-r` mode, press **`r`** to restart that process instantly without leaving the program.)*

**4. Open several files or commands at once**
```bash
# follow several files at once (like tail -f on multiple screens)
logview app1.log app2.log error.log

# run several commands at once
logview -r "pm2 logs thlive-bot --raw" -r "pm2 logs line-bot --raw"
```

**5. Read from a pipe (`|`)**
```bash
pm2 logs --raw | logview
docker logs -f my-container | logview
```

**6. Add more logs from another terminal into the existing window**
1. **Terminal 1:** keep your main viewer open
   ```bash
   logview -r "pm2 logs thlive-bot --raw"
   ```
2. **Terminal 2:** open another one as usual
   ```bash
   logview -r "pm2 logs line-bot --raw"
   ```
   > **Result:** Terminal 2 hands the job over to Terminal 1 and exits by itself. Terminal 1 then pops up a dialog asking whether to split the screen into 2 or 4 panes.

</details>

---

## ⚙️ ตัวเลือกคำสั่งทั้งหมด / CLI Options

<details open>
<summary><b>🇹🇭 ไทย</b></summary>

| คำสั่ง / Option | คำอธิบาย | ตัวอย่าง |
| :--- | :--- | :--- |
| `<file1> [file2...]` | เปิดอ่านไฟล์ Log แบบติดตามสด (`tail -f`) ระบุได้หลายไฟล์ | `logview out.log err.log` |
| `-r "<cmd>"` / `--run "<cmd>"` | รันคำสั่งและแสดงผล (ใส่ `-r` ซ้ำหลายครั้งได้) | `logview -r "node app.js"` |
| `--pm2` | ค้นหาโปรเซสทั้งหมดใน PM2 และเปิดดูพร้อมกัน | `logview --pm2` |
| `--layout <mode>` | กำหนดรูปแบบหน้าจอทันทีโดยไม่ต้องเด้งถาม (`grid4`, `auto`, `single`) | `logview --pm2 --layout grid4` |
| `--wrap` | เปิดการตัดบรรทัดอัตโนมัติตั้งแต่เริ่มต้น | `logview --pm2 --wrap` |
| `--alert` | เปิดเสียงและแถบสีแดงแจ้งเตือนเมื่อเจอ Error ตั้งแต่เริ่มต้น | `logview --pm2 --alert` |
| `--new` | บังคับเปิดหน้าต่างใหม่แยกต่างหาก (ไม่ส่งไปรวมกับหน้าต่างเดิม) | `logview --new app.log` |
| `--demo` | เปิดโหมดจำลองข้อมูล Log สำหรับทดสอบสีและการคัดลอก | `logview --demo` |

</details>

<details>
<summary><b>🇬🇧 English</b></summary>

| Command / Option | Description | Example |
| :--- | :--- | :--- |
| `<file1> [file2...]` | Follow one or more log files live (`tail -f`) | `logview out.log err.log` |
| `-r "<cmd>"` / `--run "<cmd>"` | Run a command and show its output (repeat `-r` for several) | `logview -r "node app.js"` |
| `--pm2` | Discover every PM2 process and open them all together | `logview --pm2` |
| `--layout <mode>` | Set the layout immediately without the dialog (`grid4`, `auto`, `single`) | `logview --pm2 --layout grid4` |
| `--wrap` | Start with automatic line wrapping enabled | `logview --pm2 --wrap` |
| `--alert` | Start with the error bell and red flash enabled | `logview --pm2 --alert` |
| `--new` | Force a separate new window (do not merge into an existing one) | `logview --new app.log` |
| `--demo` | Run with simulated log data to test colours and copying | `logview --demo` |

</details>

---

## 🎮 คู่มือการควบคุม / Controls (Mouse & Keyboard)

<details open>
<summary><b>🇹🇭 ไทย</b></summary>

### 🖱️ การใช้เมาส์

| การกระทำ | ผลลัพธ์ |
| :--- | :--- |
| **ลากคลุมข้อความ** | คัดลอกลง Clipboard ทันทีที่ปล่อยเมาส์ *(ลากเลยขอบบน/ล่างเพื่อเลื่อนจออัตโนมัติ)* |
| **ดับเบิลคลิก** | เลือกทั้งคำ (รองรับคำไทยและ URL) พร้อมคัดลอกทันที |
| **ทริปเปิลคลิก** | เลือกทั้งบรรทัด พร้อมคัดลอกทันที |
| **คลิกซ้าย 1 ครั้ง** | ยกเลิกการคลุมข้อความ / เลือกโฟกัสช่องนั้น |
| **ดับเบิลคลิกที่แถบชื่อช่อง** | ขยายช่องนั้นเต็มจอ (`Zoom`) / ดับเบิลคลิกซ้ำเพื่อกลับไปแบ่งช่อง |

### ⌨️ คีย์ลัดทั้งหมด

**1. การจัดหน้าจอและสลับช่อง**

| ปุ่ม | หน้าที่การทำงาน |
| :--- | :--- |
| **`l`** | เปิดหน้าต่างเลือกรูปแบบหน้าจอ (`Grid 4 ช่อง` / `แบ่งตามจำนวน` / `รวม 1 ช่อง`) |
| **`g`** | สลับเร็วระหว่าง **โหมดแบ่งช่อง (Grid)** กับ **รวมหน้าจอเดียว (1-View)** |
| **`z`** | ขยายช่องที่กำลังโฟกัสให้เต็มจอ (`Zoom`) / กดซ้ำเพื่อกลับไปแบ่งช่อง |
| **`1` - `4`** หรือ **`Tab`** | เลือกสลับโฟกัสไปยังช่องที่ 1–4 |
| **`x`** | ปิดเฉพาะช่องที่กำลังโฟกัสอยู่ |

**2. การค้นหา กรอง และควบคุม Log**

| ปุ่ม | หน้าที่การทำงาน |
| :--- | :--- |
| **`/`** | เปิดช่องค้นหาและกรองข้อความ *(ดูวิธีพิมพ์ด้านล่าง)* กด `Esc` เพื่อล้าง |
| **`e`** | สลับโหมดดูเฉพาะบรรทัดที่เป็น **ERROR** อย่างเดียว |
| **`w`** | สลับ **ตัดบรรทัดอัตโนมัติ (Line Wrap)** สำหรับช่องแคบในโหมดแบ่ง 4 ช่อง |
| **`j`** | สลับ **คลี่ข้อความ JSON (Pretty-Print)** จัดย่อหน้าและลงสีให้อ่านง่าย |
| **`b`** | สลับ **แจ้งเตือนเมื่อเจอ Error (Alert Bell)** ส่งเสียงเตือนและกะพริบแถบสถานะแดง |
| **`Space`** | หยุดหน้าจอชั่วคราว (`PAUSED`) / กดซ้ำเพื่อกลับไปวิ่งสด (`LIVE`) |
| **`r`** | รีสตาร์ทโปรเซสที่กำลังรันอยู่ *(ในโหมด `-r` / `--pm2`)* |
| **`a`** | คัดลอก Log ทั้งหมดในช่องที่เลือกอยู่ลง Clipboard |
| **`s`** | บันทึก Log เป็นไฟล์ `.txt` ลงในโฟลเดอร์ปัจจุบัน |
| **`c`** | ล้างข้อความ Log บนหน้าจอ |
| **`q`** | ออกจากโปรแกรมและปิดโปรเซสลูกทั้งหมด |

> **💡 เทคนิคการพิมพ์ในช่องค้นหา (`/`):**
> * พิมพ์ `ออเดอร์` — แสดงเฉพาะบรรทัดที่มีคำว่า `ออเดอร์`
> * พิมพ์ `!ping` — **ซ่อน** บรรทัดที่มีคำว่า `ping` ออกไปทั้งหมด
> * พิมพ์ `webhook !healthcheck` — แสดงเฉพาะบรรทัดที่มี `webhook` **แต่ไม่มี** `healthcheck`

</details>

<details>
<summary><b>🇬🇧 English</b></summary>

### 🖱️ Mouse

| Action | Result |
| :--- | :--- |
| **Drag to select** | Copies to the clipboard as soon as you release the button *(drag past the top/bottom edge to auto-scroll)* |
| **Double-click** | Selects the whole word (Thai words and URLs supported) and copies it |
| **Triple-click** | Selects the whole line and copies it |
| **Single left click** | Clears the selection / focuses that pane |
| **Double-click a pane title bar** | Zooms that pane to full screen / double-click again to return to the grid |

### ⌨️ All key bindings

**1. Layout and pane switching**

| Key | Action |
| :--- | :--- |
| **`l`** | Open the layout dialog (`4-pane grid` / `one pane per source` / `single combined pane`) |
| **`g`** | Quickly toggle between **Grid mode** and **single combined view (1-View)** |
| **`z`** | Zoom the focused pane to full screen / press again to return to the grid |
| **`1` - `4`** or **`Tab`** | Move focus to pane 1–4 |
| **`x`** | Close only the focused pane |

**2. Search, filter and log control**

| Key | Action |
| :--- | :--- |
| **`/`** | Open the search/filter box *(see syntax below)*; press `Esc` to clear |
| **`e`** | Toggle showing only **ERROR** lines |
| **`w`** | Toggle **line wrap**, handy for narrow panes in the 4-pane layout |
| **`j`** | Toggle **JSON pretty-print** with indentation and colours |
| **`b`** | Toggle the **error alert bell**: rings the bell and flashes the status bar red |
| **`Space`** | Pause the screen (`PAUSED`) / press again to resume live (`LIVE`) |
| **`r`** | Restart the running process *(in `-r` / `--pm2` mode)* |
| **`a`** | Copy all logs of the selected pane to the clipboard |
| **`s`** | Save the log to a `.txt` file in the current folder |
| **`c`** | Clear the log text on screen |
| **`q`** | Quit and terminate all child processes |

> **💡 Search box tips (`/`):**
> * Type `order` — show only lines containing `order`
> * Type `!ping` — **hide** every line containing `ping`
> * Type `webhook !healthcheck` — show lines containing `webhook` **but not** `healthcheck`

</details>

---

## 📁 โครงสร้างไฟล์ในโปรเจกต์ / Project Structure

<details open>
<summary><b>🇹🇭 ไทย</b></summary>

```text
tui-logview/
├── logview.py       # ไฟล์หลัก: รับคำสั่ง CLI จัดการแหล่งข้อมูล และจัดวางหน้าจอ
├── log_parser.py    # แยกสี Log จัดกลุ่มอักขระไทย/อีโมจิ (Grapheme) JSON และ Clipboard
├── log_widget.py    # วิดเจ็ตแสดงผลแบบ Virtual Scroll, Line Wrap และกล่องแยกช่อง (LogPane)
├── modals.py        # หน้าต่าง Pop-up เลือกรูปแบบหน้าจอ
├── ipc_bridge.py    # ระบบส่งข้อมูลข้าม Terminal ผ่าน Local Socket
├── install.sh       # สคริปต์ติดตั้งครบวงจรสำหรับ Linux (แพ็กเกจ + ฟอนต์ + .venv + PM2 hook)
├── requirements.txt # รายการไลบรารี Python (textual)
└── LICENSE          # สัญญาอนุญาต MIT
```

</details>

<details>
<summary><b>🇬🇧 English</b></summary>

```text
tui-logview/
├── logview.py       # Entry point: CLI parsing, source management and screen layout
├── log_parser.py    # Log colouring, Thai/emoji grapheme handling, JSON and clipboard
├── log_widget.py    # Virtual-scroll log widget, line wrap and the pane box (LogPane)
├── modals.py        # Pop-up dialog for choosing the screen layout
├── ipc_bridge.py    # Cross-terminal messaging over a local socket
├── install.sh       # All-in-one Linux installer (packages + fonts + .venv + PM2 hook)
├── requirements.txt # Python dependencies (textual)
└── LICENSE          # MIT license
```

</details>

---

## 📄 สัญญาอนุญาต / License

<details open>
<summary><b>🇹🇭 ไทย</b></summary>

เผยแพร่ภายใต้สัญญาอนุญาต [MIT License](LICENSE) — สามารถนำไปใช้งาน แก้ไข และพัฒนาต่อได้อย่างอิสระ

</details>

<details>
<summary><b>🇬🇧 English</b></summary>

Released under the [MIT License](LICENSE). You are free to use, modify and build on it.

</details>