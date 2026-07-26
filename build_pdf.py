"""
Convert docs/architecture.md to system_architecture.pdf using ReportLab.
Features professional styling, clean layout, custom tables, code blocks, page numbers, and headers.
"""
import os
import re
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable, Preformatted
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

# ── Numbered Canvas for Page Numbers ──────────────────────────────────────────
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#64748B"))

        # Header (pages after cover/first page)
        if self._pageNumber > 1:
            self.drawString(54, 750, "ARIA BMS v2.0 — System Architecture Specification")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)

        # Footer
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 36, page_str)
        self.drawString(54, 36, "CONFIDENTIAL & PROPRIETARY — ARIA SMART BUILDING SYSTEMS")
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(54, 48, 558, 48)

        self.restoreState()


def md_to_pdf(md_path, pdf_path):
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()

    # Custom styles
    primary_color = colors.HexColor("#0F172A")    # Dark Navy
    accent_color = colors.HexColor("#0284C7")     # Ocean Blue
    code_bg = colors.HexColor("#0F172A")          # Dark slate for code
    table_header_bg = colors.HexColor("#1E293B")  # Slate header

    style_title = ParagraphStyle(
        "DocTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=primary_color,
        alignment=0,
        spaceAfter=15
    )

    style_h2 = ParagraphStyle(
        "DocH2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=accent_color,
        spaceBefore=16,
        spaceAfter=8,
        keepWithNext=True
    )

    style_h3 = ParagraphStyle(
        "DocH3",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#334155"),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )

    style_body = ParagraphStyle(
        "DocBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceAfter=8
    )

    style_bullet = ParagraphStyle(
        "DocBullet",
        parent=style_body,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=4
    )

    style_code = ParagraphStyle(
        "DocCode",
        fontName="Courier",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#38BDF8"),  # Light cyan text
        backColor=code_bg,
        spaceBefore=8,
        spaceAfter=10,
        leftIndent=8,
        rightIndent=8
    )

    style_table_cell = ParagraphStyle(
        "TableCell",
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1E293B")
    )

    style_table_header = ParagraphStyle(
        "TableHeader",
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.white
    )

    story = []

    # Process markdown lines
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Empty line
        if not stripped:
            i += 1
            continue

        # Horizontal Rule
        if stripped == "---":
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E2E8F0"), spaceAfter=12, spaceBefore=12))
            i += 1
            continue

        # H1
        if stripped.startswith("# "):
            title_text = stripped[2:].strip()
            story.append(Paragraph(title_text, style_title))
            story.append(HRFlowable(width="100%", thickness=2, color=accent_color, spaceAfter=15))
            i += 1
            continue

        # H2
        if stripped.startswith("## "):
            h2_text = stripped[3:].strip()
            story.append(Paragraph(h2_text, style_h2))
            i += 1
            continue

        # H3
        if stripped.startswith("### "):
            h3_text = stripped[4:].strip()
            story.append(Paragraph(h3_text, style_h3))
            i += 1
            continue

        # Code block (```)
        if stripped.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            code_text = "\n".join(code_lines)
            
            # Format as Preformatted box
            p_code = Preformatted(code_text, style_code)
            story.append(p_code)
            i += 1
            continue

        # Table (| ... |)
        if stripped.startswith("|"):
            table_data = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row_line = lines[i].strip()
                # Skip divider line (|---|---|)
                if not re.match(r"^\|[\s\-:|]+\|$", row_line):
                    cells = [c.strip() for c in row_line.split("|")[1:-1]]
                    table_data.append(cells)
                i += 1
            
            if table_data:
                # Convert table text to Paragraphs
                formatted_table_data = []
                for row_idx, row in enumerate(table_data):
                    formatted_row = []
                    for cell in row:
                        cell_clean = re.sub(r"`([^`]+)`", r"<b>\1</b>", cell)
                        cell_clean = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", cell_clean)
                        if row_idx == 0:
                            formatted_row.append(Paragraph(cell_clean, style_table_header))
                        else:
                            formatted_row.append(Paragraph(cell_clean, style_table_cell))
                    formatted_table_data.append(formatted_row)
                
                # Calculate column widths evenly
                col_count = len(table_data[0])
                col_width = (504.0) / col_count  # 504 pt = 7 inches total printable width
                col_widths = [col_width] * col_count

                t = Table(formatted_table_data, colWidths=col_widths)
                t_style = [
                    ('BACKGROUND', (0,0), (-1,0), table_header_bg),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                    ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
                    ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#94A3B8")),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ]
                # Alternating row colors
                for r in range(1, len(table_data)):
                    if r % 2 == 0:
                        t_style.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor("#F8FAFC")))
                
                t.setStyle(TableStyle(t_style))
                story.append(Spacer(1, 4))
                story.append(t)
                story.append(Spacer(1, 10))
            continue

        # Bullet list (- or *)
        if stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\.\s", stripped):
            bullet_clean = re.sub(r"^[-*\d\.]+\s+", "", stripped)
            # Formatting (bold & code)
            bullet_clean = re.sub(r"`([^`]+)`", r"<font face='Courier' color='#0284C7'>\1</font>", bullet_clean)
            bullet_clean = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", bullet_clean)
            story.append(Paragraph(f"• {bullet_clean}", style_bullet))
            i += 1
            continue

        # Regular Paragraph
        p_text = re.sub(r"`([^`]+)`", r"<font face='Courier' color='#0284C7'>\1</font>", stripped)
        p_text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", p_text)
        story.append(Paragraph(p_text, style_body))
        i += 1

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated PDF: {pdf_path}")

if __name__ == "__main__":
    md_file = os.path.join("docs", "architecture.md")
    pdf_file = os.path.join(r"C:\Users\annad\.gemini\antigravity\brain\df314746-93ca-4da8-8030-ec12f7027643", "system_architecture.pdf")
    md_to_pdf(md_file, pdf_file)
