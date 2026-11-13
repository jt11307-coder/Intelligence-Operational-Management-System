"""PDF, workbook, CSV, and PowerPoint exports."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from pptx import Presentation
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from wpd_compstat.reporting.packet import ReportPacket
from wpd_compstat.security.redact import csv_formula_safe


def export_pdf(packet: ReportPacket, path: Path) -> Path:
    styles = getSampleStyleSheet()
    document = SimpleDocTemplate(str(path), pagesize=letter, title=packet.title)
    story = [
        Paragraph(_xml(packet.title), styles["Title"]),
        Paragraph(_xml(f"Generated {packet.generated_at}. Period {packet.period}."), styles["Normal"]),
        Spacer(1, 8),
    ]
    for note in packet.qualifications:
        story.append(Paragraph(_xml(note), styles["Italic"]))
    for section in packet.sections:
        story.append(Spacer(1, 10))
        story.append(Paragraph(_xml(section.title), styles["Heading2"]))
        for line in section.prose:
            story.append(Paragraph(_xml(line), styles["Normal"]))
        for table in section.tables:
            story.append(Paragraph(_xml(table.title), styles["Heading3"]))
            for row in table.rows:
                story.append(Paragraph(_xml(" | ".join(row)), styles["Normal"]))
    document.build(story)
    return path


def export_pptx(packet: ReportPacket, path: Path) -> Path:
    presentation = Presentation()
    title_slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    title_slide.shapes.title.text = packet.title
    title_slide.placeholders[1].text = f"{packet.period}\nGenerated {packet.generated_at}"
    for section in packet.sections:
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = section.title
        body = slide.placeholders[1].text_frame
        body.text = section.prose[0] if section.prose else "Not documented."
        for line in section.prose[1:8]:
            paragraph = body.add_paragraph()
            paragraph.text = line
    presentation.save(path)
    return path


def export_xlsx(packet: ReportPacket, path: Path) -> Path:
    workbook = Workbook()
    cover = workbook.active
    cover.title = "Cover"
    cover["A1"] = packet.title
    cover["A2"] = packet.generated_at
    cover["A3"] = packet.period
    for index, note in enumerate(packet.qualifications, start=5):
        cover.cell(index, 1, csv_formula_safe(note))
    for section_index, section in enumerate(packet.sections, start=1):
        sheet = workbook.create_sheet(f"{section_index:02d}"[:31])
        sheet["A1"] = section.title
        row_number = 3
        for line in section.prose:
            sheet.cell(row_number, 1, csv_formula_safe(line))
            row_number += 1
        for table in section.tables:
            row_number += 1
            for column, header in enumerate(table.headers, start=1):
                sheet.cell(row_number, column, header)
            for record in table.rows:
                row_number += 1
                for column, value in enumerate(record, start=1):
                    sheet.cell(row_number, column, csv_formula_safe(value))
    workbook.save(path)
    return path


def export_csv(packet: ReportPacket, path: Path) -> Path:
    lines = ["section,line"]
    for section in packet.sections:
        for line in section.prose:
            lines.append(_csv(section.title) + "," + _csv(line))
        for table in section.tables:
            lines.append(_csv(section.title) + "," + _csv(" | ".join(table.headers)))
            for record in table.rows:
                lines.append(_csv(section.title) + "," + _csv(" | ".join(record)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def _xml(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _csv(value: str) -> str:
    safe = csv_formula_safe(value).replace('"', '""')
    return f'"{safe}"'
