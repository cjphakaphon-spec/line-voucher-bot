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

กรุณาวิเคราะห์เอกสารใบเสร็จ/ใบกำกับภาษีที่แนบมานี้ (ทั้งรูปภาพและไฟล์ PDF) สังเกตทั้งตัวอักษรพิมพ์และข้อความโน้ตที่เขียนด้วยลายมือบนรูปภาพ แล้วสกัดข้อมูลลงในรูปแบบ JSON ต่อไปนี้เท่านั้น (ไม่ต้องมีคำอธิบายเพิ่มเติม นอกเหนือจาก JSON):

{
  "pay_to": "ชื่อบริษัท/ผู้ขาย/ซัพพลายเออร์ที่ออกใบเสร็จ (Pay to)",
  "voucher_no": "เลขที่ใบเสร็จ/เลขที่ใบกำกับภาษี/เลขที่เอกสารที่ปรากฏในใบเสร็จจริง (เช่น INV-1234, IV-2569/001 ถ้าไม่พบให้ใส่ \"\")",
  "date": "วันที่ในเอกสาร (รูปแบบ DD/MM/YYYY)",
  "particulars": "สรุปรายการสินค้า/บริการ หรือชื่อรายการหลัก",
  "amount": ยอดเงินก่อน VAT (ตัวเลข float เช่น 1000.00),
  "vat": ยอดภาษีมูลค่าเพิ่ม 7% (ตัวเลข float เช่น 70.00 ถ้าไม่มีให้ใส่ 0.00),
  "wh_tax": ยอดภาษีหัก ณ ที่จ่าย (ตัวเลข float เช่น 30.00 ถ้าไม่มีให้ใส่ 0.00),
  "total": ยอดเงินรวมสุทธิหลังหัก ณ ที่จ่าย (ตัวเลข float เช่น 1040.00 = amount + vat - wh_tax),
  "net_pay": ยอดเงินจ่ายจริง/สุทธิ (ตัวเลข float เช่น 1040.00)
}

กฎเพิ่มเติมสำหรับการประมวลผลข้อมูลและโน้ตลายมือ:
1. การตรวจจับโน้ตลายมือ (Handwritten Notes):
   - สังเกตข้อความลายมือหรือโน้ตที่เขียนเพิ่มเติมบนเอกสาร หากมีข้อความระบุเกี่ยวกับการหัก ณ ที่จ่าย (เช่น "หัก ณ ที่จ่าย 3%", "หัก 3%", "W/H 3%", หรือระบุยอดตัวเลขหัก ณ ที่จ่าย) ให้สกัดค่านั้นลงในช่อง `wh_tax`
   - หากระบุเป็นเปอร์เซ็นต์ (เช่น หัก 3% หรือ 1%) ให้คำนวณยอด `wh_tax` จากยอดเงินก่อน VAT (`amount`) ตัวอย่างเช่น: ยอดก่อน VAT = 1,000 บาท หัก 3% จะได้ `wh_tax = 30.00`
2. การคำนวณยอดเงินรวม (Total) และสุทธิ (Net Pay):
   - ยอดเงินรวมในช่อง Total (`total`) = ยอดก่อน VAT (`amount`) + ภาษีมูลค่าเพิ่ม (`vat`) - ภาษีหัก ณ ที่จ่าย (`wh_tax`)
   - ยอดเงินจ่ายจริง (`net_pay`) = ยอดเงินรวม (`total`)
3. การระวังแยกแยะตัวอักษร IV กับ N ของเลขที่เอกสาร (voucher_no):
   - หากเป็นเอกสารประเภท ใบกำกับภาษี / ใบแจ้งหนี้ (Tax Invoice / Invoice) แล้วพบรหัสขึ้นต้นด้วย N ตามด้วยตัวเลขชิดกัน (เช่น N6900249) ให้สังเกตขีดและเส้นของตัวอักษรอย่างละเอียด หากต้นฉบับคือ IV (Invoice) ให้คืนค่าเป็น "IV6900249"
   - หากเอกสารนั้นมี Prefix ตัว N จริงๆ หรือเป็นเอกสารประเภท Note / Delivery Note / Form N ให้คงค่า "N..." ไว้ตามต้นฉบับจริง ห้ามเปลี่ยนเป็น IV
4. ตรวจสอบพรีฟิกซ์เอกสารมาตรฐานทางบัญชี เช่น IV, INV, TAX, RE, RC, PV, NO, NOTE, DN
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
    รองรับการคำนวณยอดในช่อง Total ให้หักลบยอด W/H Tax อัตโนมัติ
    """
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
        
    if not api_key:
        raise ValueError("กรุณากำหนด GEMINI_API_KEY ในระบบ หรือส่งผ่านอาร์กิวเมนต์")

    models_to_try = ["gemini-flash-lite-latest", "gemini-flash-latest"]
    last_error = None

    for attempt in range(1, 3):
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
                    
                    amount = float(data.get("amount", 0.0))
                    vat = float(data.get("vat", 0.0))
                    wh_tax = float(data.get("wh_tax", 0.0))
                    
                    # คำนวณ Total = Amount + VAT - W/H Tax ตามต้องการ
                    total = amount + vat - wh_tax
                    net_pay = float(data.get("net_pay", total))
                    
                    return {
                        "voucher_no": clean_vno,
                        "date": data.get("date", ""),
                        "pay_to": data.get("pay_to", ""),
                        "items": [
                            {
                                "date": data.get("date", ""),
                                "particulars": data.get("particulars", "ชำระค่าสินค้า/บริการ ตามใบเสร็จ"),
                                "amount": amount,
                                "vat": vat,
                                "wh_tax": wh_tax,
                                "total": total
                            }
                        ],
                        "net_pay": net_pay
                    }
                except Exception as e:
                    last_error = e
                    continue
        except ImportError:
            pass

        # 2. HTTP REST Fallback
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

                    amount = float(data.get("amount", 0.0))
                    vat = float(data.get("vat", 0.0))
                    wh_tax = float(data.get("wh_tax", 0.0))
                    
                    # คำนวณ Total = Amount + VAT - W/H Tax ตามต้องการ
                    total = amount + vat - wh_tax
                    net_pay = float(data.get("net_pay", total))

                    return {
                        "voucher_no": clean_vno,
                        "date": data.get("date", ""),
                        "pay_to": data.get("pay_to", ""),
                        "items": [
                            {
                                "date": data.get("date", ""),
                                "particulars": data.get("particulars", "ชำระค่าสินค้า/บริการ"),
                                "amount": amount,
                                "vat": vat,
                                "wh_tax": wh_tax,
                                "total": total
                            }
                        ],
                        "net_pay": net_pay
                    }
            except Exception as e:
                last_error = e
                continue

        time.sleep(5)

    raise Exception(f"ไม่สามารถประมวลผลด้วย Gemini API ได้: {last_error}")
