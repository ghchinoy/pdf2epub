# pdf2epub
> Convert multi-column, math-heavy academic PDFs into beautiful, reflowable EPUB and KEPUB ebooks optimized for your Kobo eReader.

This utility addresses the classic problem of reading scientific papers (like those from arXiv) on e-readers. Instead of struggling with horizontal panning on rigid PDFs or dealing with scrambled text from simple converters, `pdf2epub` leverages **multimodal cloud-AI (Vertex AI & Gemini)** and **Pandoc** to rebuild the document's structure, transcribe mathematical expressions into LaTeX, compile them to native **MathML**, and package them for Kobo's high-performance rendering engine.

To learn more about the technical background and a comparative analysis of local programmatic tools versus our Cloud-AI pipeline, see the **[Evaluation & Research Report](docs/pdf_to_epub_evaluation.md)**.

---

## Workspace Directory Structure

To keep your working tree clean and organized, the utility separates input files from output artifacts:

```
├── bin/                         # Compiled concurrent Go binary (ignored by git)
├── docs/                        # Architectural write-ups and evaluation reports
├── evals/                       # Benchmark evaluation scripts, ground truths, and reports
├── go_port/                     # High-performance parallel Go source files
├── sources/                     # Place your raw, unprocessed PDFs here (ignored by git)
├── outputs/                     # Generated Markdown, EPUB, and KEPUB files (ignored by git)
├── convert_pdf2epub.py          # Self-contained Python CLI conversion utility
├── Makefile                     # Workspace build and cleanup orchestration
└── README.md                    # This document
```

### Keeping it Tidy
*   📥 **`sources/`:** Simply drop any PDF you want to convert into this folder. No need to rename them.
*   📤 **`outputs/`:** The pipeline automatically writes all intermediate Markdown, standard EPUB, and optimized `.kepub.epub` files here. You can wipe this folder at any time without losing your source documents or core code.

---

## Setup Instructions

### 1. Prerequisites
Ensure you have **Python 3.10+**, **Homebrew**, and **Go** installed on your macOS machine.

Install **Pandoc** (used for compiling Markdown to EPUB3) via Homebrew:
```bash
brew install pandoc
```

Ensure **Kepubify** is installed and accessible (default pipeline expectation is `/Users/ghchinoy/go/bin/kepubify`):
```bash
# If you need to install it:
go install github.com/pgaskin/kepubify/v4@latest
```

### 2. Python Virtual Environment Setup
You can set up your environment using standard Python tools or the blazing-fast Rust-based package manager [**`uv`**](https://github.com/astral-sh/uv).

#### Option A: Using `uv` (Recommended ⚡️)
Create and populate your virtual environment in seconds:
```bash
# Create a virtual environment
uv venv

# Install dependencies
uv pip install pymupdf pdfplumber google-genai
```
With `uv` installed, you can skip virtual environments entirely and run the pipeline on-the-fly using `uv run`:
```bash
uv run convert_pdf2epub.py sources/AGI2ASI_2606.12683v1.pdf --limit 3
```

#### Option B: Using standard Python tools
```bash
# Create the virtual environment
python3 -m venv .venv

# Install required packages (pymupdf, google-genai, etc.)
.venv/bin/pip install pymupdf pdfplumber google-genai
```

### 3. Authentication (Vertex AI)
The default Cloud engine utilizes Google Vertex AI for layout-aware parsing. It will automatically detect your configured Application Default Credentials. Ensure your environment has the correct project variables defined:
```bash
export GOOGLE_CLOUD_PROJECT="generative-bazaar-001"
```

---

## How to Use the Pipeline

We provide a unified conversion script, `convert_pdf2epub.py`, which integrates both Cloud AI and Local Gemma 4 engines, automates the extraction and Pandoc compilation, and optimizes the final ebook using `kepubify`.

### Command Line Arguments
*   **`pdf_path`** (Positional): The path to your raw source PDF file.
*   **`--engine`**: Choose your layout extraction model.
    *   `cloud` (Default): Uses Vertex AI `gemini-3.5-flash` in the `us` region. Beautiful layouts and LaTeX.
    *   `local`: Uses a hybrid pipeline. Extracts raw text locally via PyMuPDF and cleans/reconstructs it using your local **Gemma 4 Edge** model running on `llama-server` (at `http://localhost:8080`).
*   **`--limit <num>`**: Limit extraction to the first `N` pages (excellent for testing!).

---

### 🧪 Run a Fast Integration Test (First 3 Pages)
Before converting a massive paper, run a page-limited test to verify layout and see the quality:
```bash
# Using uv:
uv run convert_pdf2epub.py sources/AGI2ASI_2606.12683v1.pdf --limit 3

# Using standard virtual environment:
.venv/bin/python3 convert_pdf2epub.py sources/AGI2ASI_2606.12683v1.pdf --limit 3
```

### 📖 Full Document Conversion (Cloud Engine)
To convert a complete paper from start to finish using the default Cloud engine:
```bash
# Using uv:
uv run convert_pdf2epub.py sources/AGI2ASI_2606.12683v1.pdf

# Using standard virtual environment:
.venv/bin/python3 convert_pdf2epub.py sources/AGI2ASI_2606.12683v1.pdf
```

### 📴 Full Document Conversion (Local Gemma 4 Engine)
Ensure your local `llama-server` is running, then pass the `--engine local` flag:
```bash
# Using uv:
uv run convert_pdf2epub.py sources/AGI2ASI_2606.12683v1.pdf --engine local

# Using standard virtual environment:
.venv/bin/python3 convert_pdf2epub.py sources/AGI2ASI_2606.12683v1.pdf --engine local
```

All conversion products will be placed in the `outputs/` folder.

---

## ⚡️ High-Performance Concurrent Go Port

For large books or maximum speed, we have provided a **fully concurrent Go port** inside `go_port/`. 

By utilizing Go's lightweight **Goroutines**, the Go port dispatches and transcribes all pages **completely in parallel**, delivering a **3x–4x speedup** on Apple Silicon (Metal-accelerated) over sequential Python processing.

### 1. Compile the Go Port
Symmetrically compile the binary using our root `Makefile`:
```bash
make build
```
This places the static, compiled binary into `bin/convert_pdf2epub_go`.

### 2. Run the Go Port
The Go binary supports identical CLI parameters and flags to the Python script:
```bash
# Convert in parallel using Cloud AI (Vertex AI):
bin/convert_pdf2epub_go sources/AGI2ASI_2606.12683v1.pdf

# Convert in parallel offline using Local Gemma 4:
bin/convert_pdf2epub_go -engine local sources/AGI2ASI_2606.12683v1.pdf

# Run a concurrent limit-pages test:
bin/convert_pdf2epub_go -limit 3 sources/AGI2ASI_2606.12683v1.pdf
```

---

## 🛠️ Makefile Orchestration Reference

The root `Makefile` provides helpful, easy-to-use targets to orchestrate development:

*   **`make build`** - Compiles the Go concurrent binary into `bin/convert_pdf2epub_go`.
*   **`make eval`** - Executes our 5-page multi-process benchmarking and quality-evaluation suite.
*   **`make setup`** - Initializes the Python virtual environment and installs package dependencies.
*   **`make clean`** - Safely wipes compiled binaries, temporary outputs, and logs.
*   **`make help`** - Displays help documentation for the Makefile.

---

## 🔍 Kobo Reader Diagnostics Utility

If you copied your converted ebooks onto your Kobo but they are not appearing in your library, we have provided an automated on-device diagnostic utility:

```bash
# Symmetrically execute using uv or python:
uv run evals/diagnose_kobo.py

# Or:
.venv/bin/python3 evals/diagnose_kobo.py
```

### What this tool does:
1.  **Auto-Detects Your Kobo:** Programmatically scans `/Volumes/` to locate any connected Kobo device on macOS.
2.  **Scans Onboard Storage:** Verifies that your compiled `.epub` or `.kepub.epub` files are physically present on the Kobo's onboard user partition.
3.  **Inspects Kobo Database:** Opens the hidden SQLite database (`.kobo/KoboReader.sqlite`) on your Kobo, checking if the files have been successfully indexed, and reads their exact title, author, and MIME-type metadata.
4.  **Analyzes Device Logs:** Parses `.kobo/KoboReader.log` and `.kobo/syslog` to extract recent XML parsing or cataloging errors.

---

## Kobo User Experience (UX)

When you load the generated `outputs/<filename>.kepub.epub` onto your Kobo (using tools like Calibre or by dragging and dropping via USB), Kobo activates its WebKit-based **Access Reader** rather than the standard Adobe RMSDK reader.

This delivers a superior reading experience:
1.  **Native MathML Rendering:** Mathematical equations, formulas, and symbols are compiled as vector-based MathML. They scale perfectly with your book's font size, remaining crisp and perfectly readable.
2.  **In-Page Footnote Popups:** Tapping on a footnote reference (e.g., `[1]`) displays the footnote contents in a clean popup bubble at the bottom of the screen instead of awkwardly jumping to the end of the chapter.
3.  **High-Performance Page Turns:** Page flips are significantly faster and consume less battery.
4.  **Chapter Metrics:** Activates Kobo's advanced reading statistics, showing exactly how many minutes remain in the current chapter and the overall book.
