import os
import json
import time
import base64
import re
import urllib.request
import urllib.error
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

PROMPT_EXTRACT_RECEIPT = """
คุณคือผู้เชี่ยวชาญด้านการบัญชีและการอ่านเอกสารใบเสร็จ/ใบกำกับภาษีภาษาไทยและอังกฤษ

กรุณาวิเคราะห์เอกสารใบเสร็จ/ใบกำกับภาษีที่แนบมานี้ (ทั้งรูปภาพและไฟล์ PDF) แล้วสกัดข้อมูลลงในรูปแบบ JSON ต่อไปนี้เท่านั้น (ไม่ต้องมีคำอธิบายเพิ่มเติม นอกเหนือจาก JSON):

{
  "pay_to": "ชื่อบริษัท/ผู้ขาย/ซัพพลายเออร์ที่ออกใบเสร็จ (Pay to)",
  "voucher_no": "เลขที่ใบเสร็จ/เลขที่ใบกำกับภาษี/เลขที่เอกสารที่ปรากฏในใบเสร็จจริง (เช่น INV-1234, IV-2569/001 ถ้าไม่พบให้ใส่ \"\")",
  "date": "วันที่ในเอกสาร (รูปแบบ DD/MM/YYYY)",
  "particulars": "สรุปรายการสินค้า/บริการ หรือชื่อรายการหลัก",
  "amount": ยอดเงินก่อน VAT (ตัวเลข float เช่น 1000.00),
  "vat": ยอดภาษีมูลค่าเพิ่ม 7% (ตัวเลข float เช่น 70.00 ถ้าไม่มีให้ใส่ 0.00),
  "wh_tax": ยอดภาษีหัก ณ ที่จ่าย (ตัวเลข float ถ้าไม่มีให้ใส่ 0.00),
  "total": ยอดเงินรวมก่อนหัก ณ ที่จ่าย (ตัวเลข float เช่น 1070.00),
  "net_pay": ยอดเงินจ่ายจริง/สุทธิ (ตัวเลข float เช่น 1040.00)
}

กฎเพิ่มเติมสำหรับการระบุเลขที่เอกสาร (voucher_no):
1. การระวังแยกแยะตัวอักษร IV กับ N:
   - หากเป็นเอกสารประเภท ใบกำกับภาษี / ใบแจ้งหนี้ (Tax Invoice / Invoice) แล้วพบรหัสขึ้นต้นด้วย N ตามด้วยตัวเลขชิดกัน (เช่น N6900249) ให้สังเกตขีดและเส้นของตัวอักษรอย่างละเอียด หากต้นฉบับคือ IV (Invoice) ให้คืนค่าเป็น "IV6900249"
   - หากเอกสารนั้นมี Prefix ตัว N จริงๆ หรือเป็นเอกสารประเภท Note / Delivery Note / Form N ให้คงค่า "N..." ไว้ตามต้นฉบับจริง ห้ามเปลี่ยนเป็น IV
2. ตรวจสอบพรีฟิกซ์เอกสารมาตรฐานทางบัญชี เช่น IV, INV, TAX, RE, RC, PV, NO, NOTE, DN
3. หากไม่พบยอด VAT ชัดเจน แต่เป็นใบกำกับภาษี ให้คำนวณ VAT = amount * 0.07 โดยประมาณ
4. หากเป็นบริการ ให้ระบุ W/H Tax 3% หรือตามที่ระบุในเอกสาร
5. ค่าที่เป็นตัวเลขให้ส่งเฉพาะตัวเลข float ห้ามใส่เครื่องหมายจุลภาค (,) หรือสัญลักษณ์สกุลเงิน
"""

def clean_extracted_voucher_no(voucher_no: str) -> str:
    """
    ปรับแต่งเลขที่เอกสารโดยมี Safeguard ไม่ให้กระทบกับเอกสารที่ขึ้นต้นด้วย N จริงๆ
    """
    if not voucher_no:
        return ""
    voucher_no = str(voucher_no).strip()
    
    if re.match(r"^(NOTE|NO|DN|NET|NOTICE|NUMBER|N[-_])", voucher_no, re.IGNORECASE):
        return voucher_no

    if re.match(r"^N\d{5,}$", voucher_no):
        voucher_no = re.sub(r"^N", "IV", voucher_no)
        
    return voucher_no

def extract_receipt_data(file_bytes: bytes, mime_type: str = "image/jpeg", api_key: str = None) -> Dict[str, Any]:
    """
    อ่านข้อมูลใบเสร็จจากรูปภาพหรือไฟล์ PDF โดยใช้ Gemini Vision API
    พร้อมระบบ Retry อัตโนมัติและสลับโมเดลสำรองเมื่อติด Rate Limit (HTTP 429)
    """
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
        
    if not api_key:
        raise ValueError("กรุณากำหนด GEMINI_API_KEY ในระบบ หรือส่งผ่านอาร์กิวเมนต์")

    models_to_try = [
        "gemini-flash-latest",
        "gemini-1.5-flash-latest",
        "gemini-2.0-flash-lite",
        "gemini-pro-latest"
    ]
    
    last_error = None

    # ลองทำซ้ำสูงสุด 3 รอบเผื่อกรณีโดนจำกัด Rate Limit ชั่วคราว
    for attempt in range(3):
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            
            part_content = {
                "mime_type": mime_type if mime_type else "image/jpeg",
                "data": file_bytes
            }

            for model_name in models_to_try:
                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content([PROMPT_EXTRACT_RECEIPT, part_content])
                    text = response.text.strip()
                    
                    if text.startswith("```json"):
                        text = text[7:]
                    if text.startswith("```"):
                        text = text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                        
                    data = json.loads(text.strip())
                    
                    raw_vno = data.get("voucher_no", "")
                    clean_vno = clean_extracted_voucher_no(raw_vno)
                    
                    return {
                        "voucher_no": clean_vno,
                        "date": data.get("date", ""),
                        "pay_to": data.get("pay_to", ""),
                        "items": [
                            {
                                "date": data.get("date", ""),
                                "particulars": data.get("particulars", "ชำระค่าสินค้า/บริการ ตามใบเสร็จ"),
                                "amount": float(data.get("amount", 0.0)),
                                "vat": float(data.get("vat", 0.0)),
                                "wh_tax": float(data.get("wh_tax", 0.0)),
                                "total": float(data.get("total", 0.0))
                            }
                        ],
                        "net_pay": float(data.get("net_pay", float(data.get("total", 0.0)) - float(data.get("wh_tax", 0.0))))
                    }
                except Exception as e:
                    last_error = e
                    if "429" in str(e):
                        time.sleep(2)
                    continue
                    
        except ImportError:
            pass
            
        # HTTP REST Fallback
        b64_data = base64.b64encode(file_bytes).decode('utf-8')
        
        for model_name in models_to_try:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                headers = {'Content-Type': 'application/json'}
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": PROMPT_EXTRACT_RECEIPT},
                                {
                                    "inline_data": {
                                        "mime_type": mime_type if mime_type else "image/jpeg",
                                        "data": b64_data
                                    }
                                }
                            ]
                        }
                    ]
                }
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
                with urllib.request.urlopen(req) as resp:
                    res_json = json.loads(resp.read().decode('utf-8'))
                    text = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
                    
                    if text.startswith("```json"):
                        text = text[7:]
                    if text.startswith("```"):
                        text = text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                        
                    data = json.loads(text.strip())
                    raw_vno = data.get("voucher_no", "")
                    clean_vno = clean_extracted_voucher_no(raw_vno)

                    return {
                        "voucher_no": clean_vno,
                        "date": data.get("date", ""),
                        "pay_to": data.get("pay_to", ""),
                        "items": [
                            {
                                "date": data.get("date", ""),
                                "particulars": data.get("particulars", "ชำระค่าสินค้า/บริการ"),
                                "amount": float(data.get("amount", 0.0)),
                                "vat": float(data.get("vat", 0.0)),
                                "wh_tax": float(data.get("wh_tax", 0.0)),
                                "total": float(data.get("total", 0.0))
                            }
                        ],
                        "net_pay": float(data.get("net_pay", float(data.get("total", 0.0)) - float(data.get("wh_tax", 0.0))))
                    }
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code == 429:
                    time.sleep(2)
                continue
            except Exception as e:
                last_error = e
                continue

        time.sleep(2) # รอ 2 วินาทีก่อนลองรอบถัดไป

    raise Exception(f"ไม่สามารถประมวลผลด้วย Gemini API ได้ (ติด Rate Limit 429 ชั่วคราว): {last_error}")
