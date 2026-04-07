# TikTok Chat Reader - Render Ready

เวอร์ชันนี้จัดโครงใหม่ให้พร้อมขึ้น Render / Railway ง่ายขึ้น:
- ไฟล์อยู่ที่ root ตรงๆ ไม่ซ้อนโฟลเดอร์
- มี `.python-version` ล็อก Python 3.11
- มี `render.yaml` ให้
- เพิ่ม `/api/health`
- เลื่อน import `TikTokLive` ไปตอนกดเริ่มอ่าน เพื่อลดโอกาสแอปล่มตั้งแต่ตอนบูต

## รันในเครื่อง
```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

## Render
ถ้าไม่ใช้ Blueprint ให้ตั้งค่า:
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`

## ข้อสำคัญ
- เวอร์ชันนี้ให้เสียงออกจากเบราว์เซอร์ของเครื่องที่เปิดเว็บ
- ถ้า Render deploy ผ่านแล้ว แต่กดเริ่มอ่านไม่ได้ ให้เช็กว่า TikTok ID กำลังไลฟ์อยู่จริง
- `TikTokLive` เป็นไลบรารี unofficial ถ้า TikTok เปลี่ยนระบบ อาจต้องอัปเดตแพ็กเกจ
