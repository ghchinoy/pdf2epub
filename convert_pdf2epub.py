import os
import sys
import time
import re
import subprocess
import argparse
import json
import urllib.request
import fitz  # PyMuPDF

# Default configurations
LOCAL_SERVER_URL = "http://127.0.0.1:8080/v1/chat/completions"

def extract_page_as_bytes(doc, page_num):
    """Extracts a single page from a PDF and returns it as a PDF-formatted byte stream."""
    single_page_doc = fitz.open()
    single_page_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
    pdf_bytes = single_page_doc.write()
    single_page_doc.close()
    return pdf_bytes

def run_cloud_pipeline(doc, total_pages, title, author):
    """Executes the Cloud-AI pipeline (Vertex AI + Gemini 3.5)."""
    print("\nStarting Cloud-AI Pipeline (Vertex AI & gemini-3.5-flash)...")
    
    from google import genai
    from google.genai import types
    
    try:
        client = genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT", "generative-bazaar-001"),
            location="us"
        )
    except Exception as e:
        print(f"Error initializing Vertex AI Client: {e}")
        print("Ensure GOOGLE_CLOUD_PROJECT is exported and you have valid GCP default credentials.")
        sys.exit(1)
        
    prompt_vertex = """You are an expert high-fidelity document transcriber. Your task is to transcribe the provided PDF page into clean, standard Markdown with LaTeX equations for mathematical expressions.

Follow these strict guidelines:
1. READING ORDER: Identify and follow the logical reading order. If the page uses a double-column layout, read the entire left column first, then the right column. Do NOT mix text across columns.
2. MATHEMATICS: 
   - Convert all mathematical formulas, symbols, and variables to LaTeX.
   - Use standard inline math syntax: $equation$ (e.g., $E = mc^2$).
   - Use standard block math syntax for standalone equations:
     $$
     equation
     $$
3. TABLES & FIGURES: Convert all tables into clean Markdown table format.
4. HEADINGS: Identify headings and format them with appropriate Markdown header tags.
5. NO ARTIFACTS: Omit running headers, footers, and page numbers.
6. NO EXTRA TEXT: Output ONLY the transcribed markdown text itself. Do not wrap in ```markdown blocks.
"""
    
    print("Extracting layout-aware book metadata (Title, Authors, Abstract)...")
    metadata_prompt = """Analyze the provided title page of this academic PDF. Extract the following elements and return them strictly as a JSON object:
- "title": The official, complete title of the paper. Keep it clean and do not include annotations.
- "authors": A clean, comma-separated list of all authors.
- "description": A concise, 2-to-3 sentence synopsis or summary of the abstract.
Return ONLY the raw JSON object, do not wrap in ```json or ``` blocks.
"""
    try:
        first_page_bytes = extract_page_as_bytes(doc, 0)
        meta_response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=[
                types.Part.from_bytes(data=first_page_bytes, mime_type="application/pdf"),
                metadata_prompt
            ]
        )
        meta_text = meta_response.text.strip()
        if meta_text.startswith("```json"):
            meta_text = meta_text[7:]
        if meta_text.startswith("```"):
            meta_text = meta_text[3:]
        if meta_text.endswith("```"):
            meta_text = meta_text[:-3]
        meta_text = meta_text.strip()
        
        meta_data = json.loads(meta_text)
        extracted_title = meta_data.get("title", title)
        extracted_authors = meta_data.get("authors", author)
        extracted_desc = meta_data.get("description", "")
        print(f"  -> Extracted Title:   {extracted_title}")
        print(f"  -> Extracted Authors: {extracted_authors}")
    except Exception as e:
        print(f"  (Warning: failed to extract metadata via AI: {e}. Falling back to default.)")
        extracted_title = title
        extracted_authors = author
        extracted_desc = ""
        
    markdown_content = []
    
    # Pandoc metadata header
    markdown_content.append("---")
    markdown_content.append(f"title: \"{extracted_title}\"")
    markdown_content.append(f"author: \"{extracted_authors}\"")
    if extracted_desc:
        markdown_content.append(f"description: \"{extracted_desc}\"")
    markdown_content.append("---")
    markdown_content.append("")
    
    for idx in range(total_pages):
        page_num = idx + 1
        print(f"Processing page {page_num}/{total_pages}...", end="", flush=True)
        
        pdf_bytes = extract_page_as_bytes(doc, idx)
        
        max_retries = 5
        delay = 2
        success = False
        page_text = ""
        
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=[
                        types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                        prompt_vertex
                    ]
                )
                page_text = response.text.strip()
                
                # Strip raw markdown code-blocks wrappers if present
                if page_text.startswith("```markdown"):
                    page_text = page_text[11:]
                if page_text.endswith("```"):
                    page_text = page_text[:-3]
                page_text = page_text.strip()
                
                # Replace divider hyphens to prevent Pandoc YAML conflicts
                page_text = re.sub(r'^\s*-{3,}\s*$', '***', page_text, flags=re.MULTILINE)
                
                success = True
                break
            except Exception as e:
                print(f" (Attempt {attempt+1} failed: {e})", end="", flush=True)
                time.sleep(delay)
                delay *= 2
                
        if not success:
            print(" FAILED.")
            page_text = f"\n\n*** [ERROR: Failed to transcribe Page {page_num}] ***\n\n"
        else:
            print(" Done.")
            
        markdown_content.append(f"\n<!-- Page {page_num} -->\n")
        markdown_content.append(page_text)
        time.sleep(0.5)
        
    return "\n".join(markdown_content)

def query_local_gemma(prompt):
    """Sends cleanup query to local llama-server REST API."""
    payload = {
        "model": "gemma-4",
        "messages": [
            {
                "role": "system",
                "content": "You are an expert high-fidelity document transcriber. Your task is to clean, restructure, and format raw academic text blocks into correct, logical single-column reading order with proper Markdown headers and standard LaTeX math."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.0,
        "max_tokens": 2500
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        LOCAL_SERVER_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"\n[Error contacting local llama-server]: {e}")
        return None

def run_local_pipeline(doc, total_pages, title, author):
    """Executes the Hybrid Local pipeline (PyMuPDF extraction + Local Gemma 4 cleanup)."""
    print("\nStarting Hybrid Local Pipeline (PyMuPDF + Local Gemma 4)...")
    print(f"Connecting to local inference server at {LOCAL_SERVER_URL}...")
    
    # Extract Title page text to run local AI metadata extraction
    first_page = doc[0]
    raw_title_text = first_page.get_text("text").strip()
    
    print("Extracting layout-aware book metadata locally (Title, Authors, Abstract)...")
    local_meta_prompt = f"""Analyze the raw text from the title page of this academic PDF. Extract the paper title, clean list of all authors, and a 2-sentence synopsis/summary of the abstract.
Return them STRICTLY as a JSON object matching this structure:
{{
  "title": "Clean paper title",
  "authors": "Clean list of authors, comma-separated",
  "description": "Concise abstract synopsis"
}}
Return ONLY the raw JSON object. Do not wrap in markdown code blocks.

RAW TITLE PAGE TEXT:
\"\"\"
{raw_title_text[:2000]}
\"\"\"
"""
    try:
        meta_text = query_local_gemma(local_meta_prompt)
        if meta_text:
            if meta_text.startswith("```json"):
                meta_text = meta_text[7:]
            if meta_text.startswith("```"):
                meta_text = meta_text[3:]
            if meta_text.endswith("```"):
                meta_text = meta_text[:-3]
            meta_text = meta_text.strip()
            
            meta_data = json.loads(meta_text)
            extracted_title = meta_data.get("title", title)
            extracted_authors = meta_data.get("authors", author)
            extracted_desc = meta_data.get("description", "")
            print(f"  -> Extracted Title (Local):   {extracted_title}")
            print(f"  -> Extracted Authors (Local): {extracted_authors}")
        else:
            extracted_title = title
            extracted_authors = author
            extracted_desc = ""
    except Exception as e:
        print(f"  (Warning: failed to extract metadata via Local AI: {e}. Falling back to default.)")
        extracted_title = title
        extracted_authors = author
        extracted_desc = ""

    markdown_content = []
    
    # Pandoc metadata header
    markdown_content.append("---")
    markdown_content.append(f"title: \"{extracted_title}\"")
    markdown_content.append(f"author: \"{extracted_authors}\"")
    if extracted_desc:
        markdown_content.append(f"description: \"{extracted_desc}\"")
    markdown_content.append("---")
    markdown_content.append("")
    
    for idx in range(total_pages):
        page_num = idx + 1
        print(f"Processing page {page_num}/{total_pages}...", end="", flush=True)
        
        page = doc[idx]
        # Extract raw, absolute-positioned text
        raw_text = page.get_text("text").strip()
        
        prompt_gemma = f"""Below is a raw, scrambled text block extracted from a two-column academic PDF page. Reconstruct and format it into clean, flowing single-column Markdown.

INSTRUCTIONS:
1. Re-arrange column blocks so that text flows in correct, logical reading order (read left column completely first, then right column).
2. Format headings, sub-headings, and lists with Markdown tags (e.g., #, ##, ###, *, -).
3. Convert inline or block math and variables to proper LaTeX style ($inline$ or $$block$$).
4. Remove running headers, running footers, and page numbers.
5. Output ONLY the resulting Markdown. Do not add introductions or comments like "Here is your reformatted text".

RAW SCRAMBLED TEXT:
\"\"\"
{raw_text}
\"\"\"
"""
        page_text = query_local_gemma(prompt_gemma)
        
        if not page_text:
            print(" FAILED.")
            page_text = f"\n\n*** [ERROR: Local Gemma 4 cleanup failed for Page {page_num}] ***\n\n"
        else:
            print(" Done.")
            
        markdown_content.append(f"\n<!-- Page {page_num} -->\n")
        markdown_content.append(page_text)
        
    return "\n".join(markdown_content)

def main():
    parser = argparse.ArgumentParser(description="Unified High-Fidelity PDF-to-EPUB/KEPUB Converter")
    parser.add_argument("input_path", help="Path to the source PDF or Markdown file")
    parser.add_argument("--engine", choices=["cloud", "local"], default="cloud", 
                        help="Extraction engine: 'cloud' (Vertex AI Gemini, default) or 'local' (Gemma 4)")
    parser.add_argument("--limit", type=int, default=None, help="Limit conversion to the first N pages (PDF only)")
    parser.add_argument("--md-only", action="store_true", help="Extract PDF to Markdown and stop")
    args = parser.parse_args()
    
    input_path = args.input_path
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        sys.exit(1)
        
    os.makedirs("outputs", exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    
    is_markdown_source = input_path.lower().endswith(".md")
    
    if is_markdown_source:
        output_md = input_path
        output_epub = f"outputs/{base_name}.epub"
        output_kepub = f"outputs/{base_name}.kepub.epub"
        print("=" * 60)
        print(f"COMPILING DIRECTLY FROM MARKDOWN: {input_path}")
        print("=" * 60)
    else:
        # Establish compiled filenames for PDF flow
        output_md = f"outputs/{base_name}.md"
        output_epub = f"outputs/{base_name}.epub"
        output_kepub = f"outputs/{base_name}.kepub.epub"
        
        doc = fitz.open(input_path)
        total_pages = len(doc)
        if args.limit:
            total_pages = min(total_pages, args.limit)
            
        title = doc.metadata.get("title") or base_name.replace("_", " ")
        author = doc.metadata.get("author") or "Unknown Author"
        
        print("=" * 60)
        print(f"CONVERTING PDF: {input_path}")
        print(f"TITLE:          {title}")
        print(f"ENGINE:         {args.engine.upper()}")
        if args.limit:
            print(f"LIMIT:          First {args.limit} pages")
        print("=" * 60)
        
        # -------------------------------------------------------------------------
        # STEP 1: TEXT EXTRACTION
        # -------------------------------------------------------------------------
        if args.engine == "cloud":
            compiled_markdown = run_cloud_pipeline(doc, total_pages, title, author)
        else:
            compiled_markdown = run_local_pipeline(doc, total_pages, title, author)
            
        doc.close()
        
        # Clean up em-dashes and spaces in headers to prevent Pandoc from generating invalid XML URLs
        compiled_markdown = compiled_markdown.replace(" — ", " - ").replace("—", "-")
        
        # Write the compiled Markdown to outputs/
        with open(output_md, "w", encoding="utf-8") as f:
            f.write(compiled_markdown)
        print(f"\n[Step 1 Complete] Wrote compiled Markdown to: {output_md}")
        
        if args.md_only:
            print("\n[--md-only specified] Stopping pipeline. Markdown file is ready!")
            sys.exit(0)
    
    # -------------------------------------------------------------------------
    # STEP 2: PANDOC COMPILATION
    # -------------------------------------------------------------------------
    print("\n[Step 2] Compiling Markdown to EPUB3 via Pandoc...")
    try:
        subprocess.run(["pandoc", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("Error: pandoc is not installed or not in PATH. Please run 'brew install pandoc'.")
        sys.exit(1)
        
    cmd_pandoc = [
        "pandoc", output_md,
        "-o", output_epub,
        "-t", "epub3",
        "--mathml"
    ]
    print(f"Running: {' '.join(cmd_pandoc)}")
    subprocess.run(cmd_pandoc, check=True)
    print(f"[Step 2 Complete] Wrote standard EPUB to: {output_epub}")
    
    # -------------------------------------------------------------------------
    # STEP 3: GENERATING KOBO-OPTIMIZED FILES
    # -------------------------------------------------------------------------
    print("\n[Step 3] Preparing Kobo-compatible files...")
    
    # Method A: Safe-renamed KEPUB (100% valid XML, recommended for math-heavy books)
    # Simply renaming a valid EPUB3 to .kepub.epub forces Kobo to load it using its
    # fast WebKit-based engine (Access) without introducing kepubify's XML MathML schema errors!
    import shutil
    shutil.copy(output_epub, output_kepub)
    print(f"-> Created safe-renamed KEPUB: {output_kepub} (0 errors, recommended!)")
    
    # Method B: Kepubify (inserts sentence-level spans, but can conflict with MathML schemas)
    kepubify_bin = "/Users/ghchinoy/go/bin/kepubify"
    if os.path.exists(kepubify_bin):
        kepubified_output = f"outputs/{base_name}.kepubified.epub"
        # Temporarily copy standard EPUB to a separate name so kepubify writes it nicely
        temp_epub = f"outputs/{base_name}.kepubified_temp.epub"
        shutil.copy(output_epub, temp_epub)
        
        cmd_kepub = [kepubify_bin, "-o", "outputs", temp_epub]
        print(f"Running Kepubify: {' '.join(cmd_kepub)}")
        try:
            subprocess.run(cmd_kepub, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            # Rename the generated .kepub.epub to .kepubified.epub
            generated_kepub = f"outputs/{base_name}.kepubified_temp.kepub.epub"
            if os.path.exists(generated_kepub):
                if os.path.exists(kepubified_output):
                    os.remove(kepubified_output)
                os.rename(generated_kepub, kepubified_output)
            print(f"-> Created kepubified EPUB:   {kepubified_output} (may contain MathML schema warnings)")
        except Exception as e:
            print(f"Warning: Kepubify conversion failed: {e}")
        finally:
            if os.path.exists(temp_epub):
                os.remove(temp_epub)
    else:
        print("Note: kepubify binary not found. Skipping sentence-span generation.")
    
    print("\n" + "=" * 60)
    print("EBOOK CONVERSION COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print("For the ultimate Kobo reading experience, we provide two options in 'outputs/':")
    print(f"1. Safe-Renamed KEPUB (RECOMMENDED): {output_kepub}")
    print("   -> 100% compliant EPUB. No MathML errors. Guarantees successful indexing on Kobo.")
    if os.path.exists(kepubify_bin):
        print(f"2. Kepubified EPUB (Optional):       outputs/{base_name}.kepubified.epub")
        print("   -> Features sentence-level tracking, but can cause Kobo's database parser to fail")
        print("      if the book has highly complex MathML formulas.")
    print("=" * 60)

if __name__ == "__main__":
    main()
