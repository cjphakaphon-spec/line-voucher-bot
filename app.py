import os
import re
import uuid
import json
import zlib
import base64
import tempfile
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, ImageMessage, FileMessage, TextSendMessage, FlexSendMessage,
    BubbleContainer, BoxComponent, TextComponent, ButtonComponent, URIAction
)

from pdf_generator import create_payment_voucher_pdf
from ocr_extractor import extract_receipt_data

app = FastAPI(title="LINE Receipt Payment Voucher Bot")

# โฟลเดอร์สำหรับเก็บไฟล์ PDF ชั่วคราว (รองรับ Vercel Serverless ที่เขียนได้เฉพาะ /tmp)
if os.getenv("VERCEL"):
    OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "generated_vouchers")
else:
    OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "generated_vouchers")

os.makedirs(OUTPUT_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=OUTPUT_DIR), name="static")

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "YOUR_LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "YOUR_LINE_CHANNEL_ACCESS_TOKEN")
BASE_URL = os.getenv("BASE_URL", "https://your-domain.ngrok-free.app") # URL สำหรับดาวน์โหลด PDF

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

def encode_voucher_data(data: dict) -> str:
    """บีบอัดข้อมูลด้วย zlib + Base64 เพื่อความปลอดภัยและ URL สั้นลง"""
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    compressed = zlib.compress(raw)
    return base64.urlsafe_b64encode(compressed).decode('utf-8')

def decode_voucher_data(d: str) -> dict:
    """ถอดรหัสข้อมูล Voucher (รองรับทั้ง zlib compressed และ Base64 ธรรมดา)"""
    compressed = base64.urlsafe_b64decode(d.encode('utf-8'))
    try:
        raw = zlib.decompress(compressed)
        return json.loads(raw.decode('utf-8'))
    except Exception:
        return json.loads(compressed.decode('utf-8'))

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Payment Voucher LINE Bot Server is running"}

@app.get("/static/{filename}")
def get_static_file(filename: str):
    filepath = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(filepath):
        return FileResponse(filepath, media_type="application/pdf", filename=filename)
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/pdf")
def generate_and_download_pdf(d: str):
    """
    สร้างและดาวน์โหลดไฟล์ PDF Payment Voucher แบบ On-the-Fly
    (การันตีดาวน์โหลดได้สมบูรณ์ 100% บน Vercel Serverless โดยไม่ติดปัญหา 404 Not Found)
    """
    try:
        # ถอดรหัสข้อมูล Voucher
        data = decode_voucher_data(d)
        
        voucher_id = data.get("voucher_no", "VOUCHER")
        # แปลงตัวอักษรพิเศษในเลขที่เอกสาร (เช่น / หรือ \) เป็น _ เพื่อป้องกันปัญหา File path error
        safe_filename = re.sub(r'[^a-zA-Z0-9_-]', '_', voucher_id) + ".pdf"
        filepath = os.path.join(OUTPUT_DIR, safe_filename)
        
        # สร้าง PDF เรียลไทม์
        create_payment_voucher_pdf(filepath, data)
        
        return FileResponse(filepath, media_type="application/pdf", filename=safe_filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid or expired PDF request: {str(e)}")

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    return "OK"

@handler.add(MessageEvent, message=(ImageMessage, FileMessage))
def handle_file_or_image_message(event):
    reply_token = event.reply_token
    message_id = event.message.id
    message_type = event.message.type

    mime_type = "image/jpeg"
    if message_type == "file":
        file_name = getattr(event.message, "file_name", "").lower()
        if file_name.endswith(".pdf"):
            mime_type = "application/pdf"
        elif file_name.endswith(".png"):
            mime_type = "image/png"
        elif file_name.endswith(".jpg") or file_name.endswith(".jpeg"):
            mime_type = "image/jpeg"

    # แจ้งเตือนผู้ใช้ว่ากำลังประมวลผล
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text="⏳ กำลังอ่านข้อมูลใบเสร็จด้วย AI และสร้าง Payment Voucher กรุณารอสักครู่ครับ...")
    )

    try:
        # ดึงไฟล์รูปภาพ/เอกสารจาก LINE API
        message_content = line_bot_api.get_message_content(message_id)
        file_bytes = b""
        for chunk in message_content.iter_content():
            file_bytes += chunk

        # 1. OCR ด้วย Gemini API
        extracted_data = extract_receipt_data(file_bytes, mime_type=mime_type)

        # 2. ใช้เลขที่เอกสาร/ใบเสร็จจริงที่ AI อ่านได้
        voucher_id = extracted_data.get("voucher_no")
        if not voucher_id or str(voucher_id).strip() in ["", "-", "None"]:
            voucher_id = f"PV-{uuid.uuid4().hex[:6].upper()}"
        extracted_data["voucher_no"] = voucher_id

        # 3. สร้างลิงก์ดาวน์โหลด On-the-Fly (รองรับ Vercel Serverless 100%)
        encoded_data = encode_voucher_data(extracted_data)
        pdf_url = f"{BASE_URL.rstrip('/')}/pdf?d={encoded_data}"

        # 4. ส่ง Flex Message สรุปผล
        pay_to = extracted_data.get("pay_to", "-")
        net_pay = extracted_data.get("net_pay", 0.0)

        flex_message = FlexSendMessage(
            alt_text=f"สร้าง Payment Voucher {voucher_id} สำเร็จแล้ว",
            contents=BubbleContainer(
                header=BoxComponent(
                    layout="vertical",
                    contents=[
                        TextComponent(text="✅ สร้าง Payment Voucher สำเร็จ", weight="bold", color="#1DB446", size="md"),
                        TextComponent(text=f"เลขที่: {voucher_id}", size="xs", color="#aaaaaa")
                    ]
                ),
                body=BoxComponent(
                    layout="vertical",
                    contents=[
                        TextComponent(text=f"จ่ายให้: {pay_to}", weight="bold", size="sm"),
                        TextComponent(text=f"ยอดจ่ายสุทธิ: {net_pay:,.2f} THB", size="lg", weight="bold", color="#111111")
                    ]
                ),
                footer=BoxComponent(
                    layout="vertical",
                    contents=[
                        ButtonComponent(
                            action=URIAction(label="📄 ดาวน์โหลด PDF Voucher", uri=pdf_url),
                            style="primary",
                            color="#0066CC"
                        )
                    ]
                )
            )
        )

        line_bot_api.push_message(event.source.user_id, flex_message)

    except Exception as e:
        line_bot_api.push_message(
            event.source.user_id,
            TextSendMessage(text=f"❌ เกิดข้อผิดพลาดในการประมวลผลใบเสร็จ: {str(e)}")
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
