from fpdf import FPDF
import os

pdf = FPDF()
pdf.add_page()
pdf.set_font("helvetica", size=12)

# Add some text
pdf.cell(200, 10, text="Abstract", new_x="LMARGIN", new_y="NEXT", align="L")
pdf.multi_cell(200, 10, text="This is the abstract text.\\nIt has multiple sections and hopefully pdfplumber can read this.", new_x="LMARGIN", new_y="NEXT", align="L")

# Let's add a simple text-based table
pdf.ln(10)
pdf.cell(50, 10, text="Metric", border=1)
pdf.cell(50, 10, text="Value", border=1, new_x="LMARGIN", new_y="NEXT")
pdf.cell(50, 10, text="Accuracy", border=1)
pdf.cell(50, 10, text="95.5", border=1, new_x="LMARGIN", new_y="NEXT")

# Also add a figure caption
pdf.ln(10)
pdf.cell(200, 10, text="Figure 1: This is a figure caption.", new_x="LMARGIN", new_y="NEXT", align="L")

os.makedirs("backend/tests/fixtures", exist_ok=True)
pdf.output("backend/tests/fixtures/test_paper.pdf")
print("PDF fixture generated.")
