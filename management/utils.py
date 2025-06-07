# management/utils.py
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from django.utils import timezone


def generate_remittance_pdf(remittances, start_date=None, end_date=None):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    # Header
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, 750, "Remittance Report")

    # Date range
    p.setFont("Helvetica", 12)
    date_range = ""
    if start_date and end_date:
        date_range = f"From {start_date} to {end_date}"
    elif start_date:
        date_range = f"From {start_date}"
    elif end_date:
        date_range = f"Up to {end_date}"
    p.drawString(50, 730, date_range)

    # Table data
    data = [['Date', 'Unit PO', 'Driver', 'Remit Amount', 'Savings']]
    total_remit = 0
    total_savings = 0

    for remit in remittances:
        data.append([
            remit.date.strftime("%Y-%m-%d"),
            remit.unit.unit_PO,
            remit.driver.driver_name,
            f"₱{remit.remit_amount:.2f}",
            f"₱{remit.savings_amount:.2f}"
        ])
        total_remit += remit.remit_amount
        total_savings += remit.savings_amount

    # Add totals row
    data.append(['Total', '', '',
                 f"₱{total_remit:.2f}",
                 f"₱{total_savings:.2f}"])

    # Create table
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (-2, 0), (-1, -1), 'RIGHT'),
    ]))

    # Draw table
    table.wrapOn(p, 400, 600)
    table.drawOn(p, 50, 650)

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer