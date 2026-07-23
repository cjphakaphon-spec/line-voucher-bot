import os
import urllib.request
import tempfile
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def register_fonts():
    """ลงทะเบียนฟอนต์ภาษาไทยสำหรับการใช้งานบน Windows, Linux และ Vercel Serverless"""
    # 1. ตรวจสอบฟอนต์ในโฟลเดอร์ fonts/ ของโปรเจกต์ (การันตี 100% สำหรับ Vercel และ Cloud)
    base_dir = os.path.dirname(__file__)
    bundled_font = os.path.join(base_dir, "fonts", "Sarabun-Regular.ttf")
    bundled_font_bold = os.path.join(base_dir, "fonts", "Sarabun-Bold.ttf")
    
    if os.path.exists(bundled_font) and os.path.exists(bundled_font_bold):
        try:
            pdfmetrics.registerFont(TTFont("Sarabun", bundled_font))
            pdfmetrics.registerFont(TTFont("Sarabun-Bold", bundled_font_bold))
            return "Sarabun", "Sarabun-Bold"
        except Exception as e:
            print(f"Error loading bundled Sarabun font: {e}")

    # 2. ลองตรวจสอบฟอนต์ Windows
    thai_font_paths = [
        ("C:/Windows/Fonts/tahoma.ttf", "Tahoma"),
        ("C:/Windows/Fonts/angsa.ttf", "AngsanaUPC"),
        ("C:/Windows/Fonts/THSarabunNew.ttf", "THSarabunNew")
    ]
    for path, name in thai_font_paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                return name, name
            except Exception:
                pass

    # 3. สำรอง: ดาวน์โหลดไปไว้ในโฟลเดอร์ /tmp (เพื่อหลีกเลี่ยง Read-only filesystem บน Vercel)
    tmp_dir = tempfile.gettempdir()
    local_font = os.path.join(tmp_dir, "Sarabun-Regular.ttf")
    local_font_bold = os.path.join(tmp_dir, "Sarabun-Bold.ttf")
    try:
        if not os.path.exists(local_font):
            urllib.request.urlretrieve("https://raw.githubusercontent.com/google/fonts/main/ofl/sarabun/Sarabun-Regular.ttf", local_font)
        if not os.path.exists(local_font_bold):
            urllib.request.urlretrieve("https://raw.githubusercontent.com/google/fonts/main/ofl/sarabun/Sarabun-Bold.ttf", local_font_bold)
            
        pdfmetrics.registerFont(TTFont("Sarabun", local_font))
        pdfmetrics.registerFont(TTFont("Sarabun-Bold", local_font_bold))
        return "Sarabun", "Sarabun-Bold"
    except Exception as e:
        print(f"Warning: Could not register Thai font: {e}")

    return "Helvetica", "Helvetica-Bold"

def create_payment_voucher_pdf(output_path: str, data: dict):
    """
    สร้างไฟล์ PDF Payment Voucher ตามรูปแบบของ RYOKUSAN ASIA CO.,LTD.
    """
    font_name, font_bold = register_fonts()
    
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )
    
    elements = []
    
    # Styles
    title_style = ParagraphStyle(
        'CompanyTitle',
        fontName=font_bold,
        fontSize=16,
        leading=20,
        alignment=1, # Center
        textColor=colors.black
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        fontName=font_name,
        fontSize=11,
        leading=14,
        alignment=1, # Center
        textColor=colors.black
    )
    normal_style = ParagraphStyle(
        'NormalText',
        fontName=font_name,
        fontSize=10,
        leading=13
    )
    bold_style = ParagraphStyle(
        'BoldText',
        fontName=font_bold,
        fontSize=10,
        leading=13
    )
    
    # 1. Header
    elements.append(Paragraph("<b>RYOKUSAN ASIA CO.,LTD.</b>", title_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph("PAYMENT VOUCHER (Castle Farm)", subtitle_style))
    elements.append(Spacer(1, 15))
    
    # 2. No, Date, Pay to Section
    voucher_no = data.get("voucher_no", "")
    voucher_date = data.get("date", "")
    pay_to = data.get("pay_to", "")
    pay_to_paragraph = Paragraph(pay_to, normal_style)
    
    meta_table = Table(
        [
            [
                Paragraph(f"<b>Pay to:</b>", normal_style),
                pay_to_paragraph,
                Paragraph(f"<b>No:</b> {voucher_no}", normal_style)
            ],
            [
                "",
                "",
                Paragraph(f"<b>Date:</b> {voucher_date}", normal_style)
            ]
        ],
        colWidths=[60, 300, 150]
    )
    
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor("#D9EAD3")),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (2, 0), (2, 0), 0.5, colors.HexColor("#888888")),
        ('LINEBELOW', (2, 1), (2, 1), 0.5, colors.HexColor("#888888")),
    ]))
    
    elements.append(meta_table)
    elements.append(Spacer(1, 15))
    
    # 3. Main Particulars Table
    headers = ["Date", "Particulars", "Amount", "VAT", "W/H Tax", "Total"]
    table_data = [headers]
    
    items = data.get("items", [])
    total_amt = 0.0
    total_vat = 0.0
    total_wh = 0.0
    grand_total = 0.0
    
    for item in items:
        amt = float(item.get("amount", 0.0))
        vat = float(item.get("vat", 0.0))
        wh = float(item.get("wh_tax", 0.0))
        tot = float(item.get("total", amt + vat - wh))
        if wh > 0 and abs(tot - (amt + vat)) < 0.01:
            tot = amt + vat - wh
        
        total_amt += amt
        total_vat += vat
        total_wh += wh
        grand_total += tot
        
        particulars_text = item.get("particulars", "")
        particulars_paragraph = Paragraph(particulars_text, normal_style)
        
        table_data.append([
            "",  # เว้นช่อง Date ในตารางรายการให้เป็น Blank ตามต้องการ
            particulars_paragraph,
            f"{amt:,.2f}" if amt else "-",
            f"{vat:,.2f}" if vat else "-",
            f"{wh:,.2f}" if wh else "-",
            f"{tot:,.2f}" if tot else "-"
        ])
        
    while len(table_data) < 7:
        table_data.append(["", "", "", "", "", ""])
        
    table_data.append([
        "Total",
        "",
        f"{total_amt:,.2f}" if total_amt else "-",
        f"{total_vat:,.2f}" if total_vat else "-",
        f"{total_wh:,.2f}" if total_wh else "-",
        f"{grand_total:,.2f}" if grand_total else "-"
    ])
    
    col_widths = [65, 200, 60, 60, 60, 65]
    particulars_table = Table(table_data, colWidths=col_widths)
    
    particulars_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
        ('FONTNAME', (0, 0), (-1, 0), font_bold),
        ('ALIGN', (0, 0), (1, -1), 'LEFT'),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, -1), (0, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('SPAN', (0, -1), (1, -1)),
        ('FONTNAME', (0, -1), (-1, -1), font_bold),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    
    elements.append(particulars_table)
    elements.append(Spacer(1, 8))
    
    # 4. Net Pay THB Section
    net_pay = data.get("net_pay", grand_total - total_wh)
    net_pay_table = Table(
        [["", f"Net Pay THB:  {net_pay:,.2f}"]],
        colWidths=[250, 260]
    )
    net_pay_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_bold),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('BOX', (1, 0), (1, 0), 1, colors.black),
        ('TOPPADDING', (1, 0), (1, 0), 6),
        ('BOTTOMPADDING', (1, 0), (1, 0), 6),
        ('RIGHTPADDING', (1, 0), (1, 0), 10),
    ]))
    elements.append(net_pay_table)
    elements.append(Spacer(1, 50))
    
    # 5. Signature Section
    sig_data = [
        ["_________________________", "_________________________"],
        ["Prepared by", "Authorized by"],
        ["", ""],
        ["_________________________", "_________________________"],
        ["Paid by", "Received by"]
    ]
    
    sig_table = Table(sig_data, colWidths=[250, 260])
    sig_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    
    elements.append(sig_table)
    
    doc.build(elements)
    return output_path

if __name__ == "__main__":
    sample_data = {
        "voucher_no": "PV-202607-001",
        "date": "22/07/2026",
        "pay_to": "บริษัท อัลฟ่าพัลส์ คอร์ปอเรชั่น จำกัด",
        "items": [
            {
                "date": "17/06/2026",
                "particulars": "ค่าบริการ อุปกรณ์และสินค้า 5 รายการ",
                "amount": 6266.36,
                "vat": 438.64,
                "wh_tax": 0.00,
                "total": 6705.00
            }
        ],
        "net_pay": 6705.00
    }
    create_payment_voucher_pdf("test_voucher_output.pdf", sample_data)
    print("Sample PDF generated at test_voucher_output.pdf")
