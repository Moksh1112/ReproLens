import hashlib
import json
try:
    import fitz
    import pdfplumber
except ImportError:
    fitz = None
    pdfplumber = None

import re
import urllib.request
import urllib.error
import os
import ssl

def resolve_paper_source(source: str, cache_dir: str) -> str:
    """
    Resolves an arXiv identifier or URL to a local PDF path.
    If the source is already a local path, returns it unchanged.
    """
    match = re.search(r'(?:arxiv:|^|arxiv\.org/(?:abs|pdf)/)(\d{4,5}\.\d{4,5}(?:v\d+)?)', source, re.IGNORECASE)
    
    # Check if the string matches an arxiv pattern precisely, so we don't accidentally match filenames
    is_arxiv = False
    if match:
        extracted = match.group(1)
        # If the input was just the ID, or "arxiv:ID", or URL
        if source.strip().lower() == extracted or \
           source.strip().lower() == f"arxiv:{extracted}" or \
           "arxiv.org" in source.lower():
            is_arxiv = True

    if is_arxiv:
        arxiv_id = match.group(1)
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        local_path = os.path.join(cache_dir, f"{arxiv_id}.pdf")
        
        if not os.path.exists(local_path):
            os.makedirs(cache_dir, exist_ok=True)
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
                req = urllib.request.Request(pdf_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx) as response, open(local_path, 'wb') as out_file:
                    out_file.write(response.read())
            except urllib.error.URLError as e:
                raise ValueError(f"Failed to download arXiv paper {arxiv_id}: {e}")
                
        return local_path
        
    return source

def parse_pdf(file_path: str) -> dict:
    """
    Parses a PDF file to extract text, sections, and tables.
    Requires PyMuPDF (fitz) and pdfplumber.
    """

    # Calculate stable content hash
    hasher = hashlib.sha256()
    with open(file_path, 'rb') as f:
        hasher.update(f.read())
    content_hash = hasher.hexdigest()

    sections = []
    tables = []

    # Extract text and basic sections using PyMuPDF
    doc = fitz.open(file_path)
    
    paper_date = None
    if len(doc) > 0:
        import re
        from datetime import datetime
        first_page_text = doc[0].get_text("text")
        # Try to find arXiv date string: arXiv:XXXX.XXXXX [category] DD MMM YYYY
        arxiv_match = re.search(r"arXiv:\d{4}\.\d{4,5}v\d+\s+\[.*?\]\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", first_page_text)
        if arxiv_match:
            try:
                paper_date = datetime.strptime(arxiv_match.group(1), "%d %b %Y").isoformat() + "Z"
            except ValueError:
                pass
        else:
            # Try to find general publish date pattern like "Published: DD Month YYYY"
            pub_match = re.search(r"Published:\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", first_page_text, re.IGNORECASE)
            if pub_match:
                try:
                    # %B for full month name
                    paper_date = datetime.strptime(pub_match.group(1).title(), "%d %B %Y").isoformat() + "Z"
                except ValueError:
                    try:
                        # Fallback to %b for short month
                        paper_date = datetime.strptime(pub_match.group(1).title(), "%d %b %Y").isoformat() + "Z"
                    except ValueError:
                        pass

    full_text = ""
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        full_text += text + "\n"
        
        # Simple heuristic: split by double newlines for sections
        parts = text.split("\n\n")
        for i, part in enumerate(parts):
            if part.strip():
                # Treat short lines as possible titles
                title = part.strip().split("\n")[0] if len(part.strip()) < 100 else f"Page {page_num+1} Part {i}"
                sections.append({
                    "title": title,
                    "text": part.strip(),
                    "page": page_num + 1
                })

    # Extract tables using pdfplumber
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages):
            extracted_tables = page.extract_tables()
            for j, table in enumerate(extracted_tables):
                tables.append({
                    "table_id": f"table_{i+1}_{j+1}",
                    "page": i + 1,
                    "content": table
                })

    return {
        "content_hash": content_hash,
        "paper_date": paper_date,
        "sections": sections,
        "tables": tables
    }
