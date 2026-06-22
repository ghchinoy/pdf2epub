.PHONY: all build clean eval setup help

# Default target
all: build

# ⚡️ Compile Go Concurrent Pipeline Binary
build:
	@echo "============================================================="
	@echo "BUILDING CONCURRENT GO PORT BINARY"
	@echo "============================================================="
	@mkdir -p bin
	cd go_port && go build -o ../bin/convert_pdf2epub_go main.go
	@echo "-> Successfully compiled to bin/convert_pdf2epub_go 🚀"
	@echo "============================================================="

# 🧪 Run the 5-page Benchmarking Suite
eval:
	@echo "============================================================="
	@echo "RUNNING 5-PAGE MULTI-PROCESS PIPELINE BENCHMARKS"
	@echo "============================================================="
	@if command -v uv >/dev/null 2>&1; then \
		uv run evals/run_evals.py --pages 5; \
	else \
		.venv/bin/python3 evals/run_evals.py --pages 5; \
	fi

# ⚙️ Install Python virtual environment dependencies
setup:
	@echo "============================================================="
	@echo "SETTING UP PYTHON VIRTUAL ENVIRONMENT"
	@echo "============================================================="
	@if command -v uv >/dev/null 2>&1; then \
		uv venv && uv pip install pymupdf pdfplumber google-genai; \
	else \
		python3 -m venv .venv && .venv/bin/pip install pymupdf pdfplumber google-genai; \
	fi
	@echo "-> Setup completed successfully!"
	@echo "============================================================="

# 🧹 Clean compiled binaries, log files, and intermediate outputs
clean:
	@echo "Cleaning compiled binaries and output artifacts..."
	rm -rf bin/
	rm -rf outputs/*
	rm -rf go_port/outputs/
	rm -f llama_server.log
	@echo "Cleanup completed successfully!"

# ❓ Show help information for Makefile targets
help:
	@echo "Available Makefile Targets:"
	@echo "  make build  - Compile Go concurrent pipeline into bin/convert_pdf2epub_go"
	@echo "  make eval   - Execute the 5-page multi-process benchmark evaluation suite"
	@echo "  make setup  - Symmetrically initialize python venv and install dependencies"
	@echo "  make clean  - Safely wipe compiled binaries, intermediate outputs, and logs"
	@echo "  make help   - View this help documentation"
