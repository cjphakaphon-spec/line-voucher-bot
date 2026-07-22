import os
import sys
from ocr_extractor import extract_receipt_data
from pdf_generator import create_payment_voucher_pdf

def test_process_receipt(image_path: str):
    """
    ทดสอบการอ่านใบเสร็จจากไฟล์รูปภาพในเครื่อง และสร้าง PDF Payment Voucher
    """
    if not os.path.exists(image_path):
        print(f"❌ ไม่พบไฟล์รูปภาพ: {image_path}")
        return

    print(f"📷 กำลังอ่านไฟล์รูปภาพ: {image_path}...")
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    print("🤖 กำลังวิเคราะห์ข้อมูลใบเสร็จด้วย Gemini Vision API...")
    extracted = extract_receipt_data(image_bytes)

    print("\n✅ ข้อมูลที่อ่านได้จาก AI:")
    print(f"  - Pay to: {extracted.get('pay_to')}")
    print(f"  - Date: {extracted.get('date')}")
    print(f"  - Net Pay: {extracted.get('net_pay'):,.2f} THB")

    output_pdf = "test_voucher_result.pdf"
    print(f"\n📄 กำลังสร้างไฟล์ PDF: {output_pdf}...")
    create_payment_voucher_pdf(output_pdf, extracted)
    print(f"🎉 สำเร็จ! สามารถเปิดดูไฟล์ PDF ได้ที่: {os.path.abspath(output_pdf)}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_process_receipt(sys.argv[1])
    else:
        print("💡 วิธีใช้งาน: python test_local.py <path_to_receipt_image.jpg>")
