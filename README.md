# 🧾 LINE Receipt to Payment Voucher Bot

ระบบ LINE Bot อัตโนมัติสำหรับอ่านข้อมูลรูปภาพใบเสร็จ/ใบกำกับภาษีด้วย **Gemini Vision AI** และแปลงข้อมูลลงในแบบฟอร์ม **Payment Voucher (PDF)** ของบริษัท RYOKUSAN ASIA CO.,LTD.

---

## 📁 โครงสร้างโปรเจกต์

* [pdf_generator.py](file:///c:/Users/User/OneDrive/download/project-vault/Projects/voucher%20maker/pdf_generator.py) : โมดูลสร้างไฟล์ PDF แบบฟอร์ม Payment Voucher
* [ocr_extractor.py](file:///c:/Users/User/OneDrive/download/project-vault/Projects/voucher%20maker/ocr_extractor.py) : โมดูลเชื่อมต่อ Gemini API สกัดข้อมูลใบเสร็จเป็น JSON
* [app.py](file:///c:/Users/User/OneDrive/download/project-vault/Projects/voucher%20maker/app.py) : FastAPI Server รับ Webhook จาก LINE API
* [test_local.py](file:///c:/Users/User/OneDrive/download/project-vault/Projects/voucher%20maker/test_local.py) : สคริปต์ทดสอบอ่านใบเสร็จในเครื่องโดยไม่ต้องผ่าน LINE
* [requirements.txt](file:///c:/Users/User/OneDrive/download/project-vault/Projects/voucher%20maker/requirements.txt) : รายการแพเกจที่ต้องติดตั้ง

---

## 🚀 ขั้นตอนการติดตั้งและการใช้งาน

### 1. ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
```

### 2. ตั้งค่า Environment Variables
คัดลอกไฟล์ `.env.example` เป็น `.env` แล้วระบุค่า API Key:
```env
GEMINI_API_KEY=AIzaSy...
LINE_CHANNEL_SECRET=...
LINE_CHANNEL_ACCESS_TOKEN=...
BASE_URL=https://xxxx.ngrok-free.app
```

### 3. ทดสอบการทำงานในเครื่อง (Local Test)
ทดสอบสร้าง PDF จากข้อมูลจำลอง:
```bash
python pdf_generator.py
```
ทดสอบอ่านรูปใบเสร็จจริง:
```bash
python test_local.py path/to/receipt.jpg
```

### 4. รัน Webhook Server สำหรับ LINE Bot
```bash
python app.py
```
หรือรันผ่าน uvicorn:
```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🔗 การเชื่อมต่อกับ LINE Developers Console
1. นำ URL Server หรือ Ngrok URL ไปใส่ใน **Webhook URL** ของ LINE Messaging API Channel เช่น `https://xxxx.ngrok-free.app/webhook`
2. เปิดใช้งาน **Use webhook** ใน LINE Console
3. ลองถ่ายรูปใบเสร็จส่งเข้าไปในแชท LINE OA ของคุณ ระบบจะอ่านและส่งไฟล์ PDF กลับมาให้โดยอัตโนมัติ
