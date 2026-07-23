import os
import uuid
import json
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
    MessageEvent, ImageMessage, FileMessage, TextMessage, TextSendMessage, FlexSendMessage,
    QuickReply, QuickReplyButton, MessageAction,
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

# --- ระบบจัดการ Session รายการสะสมของผู้ใช้ ---
def get_user_session_path(user_id: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"session_{user_id}.json")

def load_user_session(user_id: str) -> dict:
    path = get_user_session_path(user_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"items": [], "pay_to": "", "date": "", "voucher_no": ""}

def save_user_session(user_id: str, session_data: dict):
    path = get_user_session_path(user_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False)

def clear_user_session(user_id: str):
    path = get_user_session_path(user_id)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass

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
        json_bytes = base64.urlsafe_b64decode(d.encode('utf-8'))
        data = json.loads(json_bytes.decode('utf-8'))
        
        voucher_id = data.get("voucher_no", "VOUCHER")
        filename = f"{voucher_id}.pdf"
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        create_payment_voucher_pdf(filepath, data)
        
        return FileResponse(filepath, media_type="application/pdf", filename=filename)
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
    user_id = event.source.user_id

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
        TextSendMessage(text="⏳ กำลังอ่านข้อมูลใบเสร็จด้วย AI กรุณารอสักครู่ครับ...")
    )

    try:
        # 1. ดึงไฟล์รูปภาพ/เอกสารจาก LINE API
        message_content = line_bot_api.get_message_content(message_id)
        file_bytes = b""
        for chunk in message_content.iter_content():
            file_bytes += chunk

        # 2. OCR ด้วย Gemini API
        extracted_data = extract_receipt_data(file_bytes, mime_type=mime_type)

        # 3. สะสมรายการเข้าใน Session ของผู้ใช้
        session = load_user_session(user_id)
        new_item = extracted_data.get("items", [{}])[0]
        session["items"].append(new_item)

        if not session.get("pay_to"):
            session["pay_to"] = extracted_data.get("pay_to", "")
        if not session.get("date"):
            session["date"] = extracted_data.get("date", "")
        if not session.get("voucher_no"):
            session["voucher_no"] = extracted_data.get("voucher_no", "")

        save_user_session(user_id, session)

        count = len(session["items"])
        last_item_text = new_item.get("particulars", "รายการใหม่")
        last_item_net = new_item.get("total", 0.0)
        total_accumulated = sum(item.get("total", 0.0) for item in session["items"])

        # 4. ส่งข้อความสรุปรายการสะสม พร้อม Quick Reply ให้ผู้ใช้เลือกว่าจะเพิ่มอีก หรือ สิ้นสุดสร้าง PDF
        reply_text = (
            f"📥 บันทึกรายการที่ {count} เรียบร้อยแล้ว!\n"
            f"• รายการ: {last_item_text}\n"
            f"• ยอดรวมรายการนี้: {last_item_net:,.2f} THB\n\n"
            f"📊 ยอดสะสมรวมขณะนี้ ({count} รายการ): {total_accumulated:,.2f} THB\n\n"
            f"❓ มีใบเสร็จ/ใบแจ้งหนี้อื่นที่จะรวมจ่ายในใบสำคัญจ่ายเดียวกันอีกไหมครับ?"
        )

        quick_reply = QuickReply(
            items=[
                QuickReplyButton(action=MessageAction(label="✅ ออก PDF (สิ้นสุด)", text="สร้าง PDF")),
                QuickReplyButton(action=MessageAction(label="➕ เพิ่มรายการอีก", text="เพิ่มรายการอีก")),
                QuickReplyButton(action=MessageAction(label="🔄 ยกเลิกรายการ", text="ยกเลิก"))
            ]
        )

        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=reply_text, quick_reply=quick_reply)
        )

    except Exception as e:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=f"❌ เกิดข้อผิดพลาดในการประมวลผลใบเสร็จ: {str(e)}")
        )

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    user_text = event.message.text.strip().lower()

    if user_text in ["สร้าง pdf", "สร้างpdf", "สิ้นสุดรายการ", "ใช่", "เสร็จแล้ว", "เสร็จ", "ออกใบสำคัญจ่าย"]:
        session = load_user_session(user_id)
        items = session.get("items", [])

        if not items:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="⚠️ ยังไม่มีรายการใบเสร็จสะสมในระบบ กรุณาถ่ายรูปหรือส่งไฟล์ใบเสร็จเข้ามาก่อนครับ")
            )
            return

        # สร้างเลขที่ Voucher หากไม่มี
        voucher_id = session.get("voucher_no")
        if not voucher_id or str(voucher_id).strip() in ["", "-", "None"]:
            voucher_id = f"PV-{uuid.uuid4().hex[:6].upper()}"

        combined_data = {
            "voucher_no": voucher_id,
            "date": session.get("date", ""),
            "pay_to": session.get("pay_to", ""),
            "items": items,
            "net_pay": sum(item.get("total", 0.0) for item in items)
        }

        # สร้างลิงก์ดาวน์โหลด On-the-Fly (รองรับ Vercel Serverless 100%)
        encoded_data = base64.urlsafe_b64encode(json.dumps(combined_data).encode('utf-8')).decode('utf-8')
        pdf_url = f"{BASE_URL.rstrip('/')}/pdf?d={encoded_data}"

        pay_to = combined_data.get("pay_to", "-")
        net_pay = combined_data.get("net_pay", 0.0)
        item_count = len(items)

        flex_message = FlexSendMessage(
            alt_text=f"สร้าง Payment Voucher {voucher_id} ({item_count} รายการ) สำเร็จแล้ว",
            contents=BubbleContainer(
                header=BoxComponent(
                    layout="vertical",
                    contents=[
                        TextComponent(text="✅ สร้าง Payment Voucher สำเร็จ", weight="bold", color="#1DB446", size="md"),
                        TextComponent(text=f"เลขที่: {voucher_id} ({item_count} รายการ)", size="xs", color="#aaaaaa")
                    ]
                ),
                body=BoxComponent(
                    layout="vertical",
                    contents=[
                        TextComponent(text=f"จ่ายให้: {pay_to}", weight="bold", size="sm"),
                        TextComponent(text=f"ยอดจ่ายสุทธิรวม: {net_pay:,.2f} THB", size="lg", weight="bold", color="#111111")
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

        line_bot_api.reply_message(event.reply_token, flex_message)
        clear_user_session(user_id)

    elif user_text in ["เพิ่มรายการอีก", "เพิ่มรายการ", "ไม่", "ยัง"]:
        session = load_user_session(user_id)
        count = len(session.get("items", []))
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"📸 รับทราบครับ (ขณะนี้สะสมอยู่ {count} รายการ)\n\nกรุณาถ่ายรูปหรือส่งไฟล์ใบเสร็จใบถัดไปมาได้เลยครับ ระบบจะนำไปใส่ในบรรทัดที่ {count + 1} ให้ทันที")
        )

    elif user_text in ["ยกเลิก", "เริ่มใหม่", "ลบ", "reset"]:
        clear_user_session(user_id)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🔄 ยกเลิกรายการสะสมเรียบร้อยแล้วครับ สามารถถ่ายรูปหรือส่งไฟล์ใบเสร็จเพื่อเริ่มใหม่ได้ทันที")
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
