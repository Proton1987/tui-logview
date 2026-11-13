<div align="center">

# 🖥️ LogViewer (`tui-logview`)

**โปรแกรมดู Log สดบน Terminal (TUI) แบบแบ่งหลายหน้าต่าง รองรับภาษาไทย อีโมจิ และรวมจอข้าม Terminal**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Textual](https://img.shields.io/badge/TUI-Textual-blueviolet)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

</div>

---

## ✨ ภาพรวมหน้าจอ (ตัวอย่างโหมดแบ่ง 4 ช่อง)

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ LogViewer (4 sources)                                             09:15:42 │
│ ● LIVE [GRID] | Active: line-bot | Sources: 4 (1,240 lines)                │
├─────────────────────────────────────┬──────────────────────────────────────┤
│ [1] thlive-bot (412 lines)          │ [2] line-bot (528 lines)             │
│ 09:15:40 INF ✅ เชื่อมต่อห้องสำเร็จ  │ 09:15:41 [telegram] ERR Bad Request  │
│ 09:15:41 INF 📩 ส่งข้อความเรียบร้อย  │ 09:15:42 WRN ⚠️ ลองส่งซ้ำแบบข้อความดิบ  │
├─────────────────────────────────────┼──────────────────────────────────────┤
│ [3] cf-tunnel (150 lines)           │ [4] cf-tunnel-2 (150 lines)          │
│ 09:15:30 INF Registered tunnel sin17│ 09:15:35 INF Registered tunnel bkk06 │
└─────────────────────────────────────┴──────────────────────────────────────┘
│ Space Pause/Live  / Filter  e Error Only  l Layout  g Grid/1-View  q Quit  │
└────────────────────────────────────────────────────────────────────────────┘