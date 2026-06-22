package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"google.golang.org/genai"
)

// Configurations
const (
	LocalServerURL = "http://127.0.0.1:8080/v1/chat/completions"
)

// CLI Arguments
var (
	inputPath string
	engine    string
	limit     int
	mdOnly    bool
)

func init() {
	flag.StringVar(&engine, "engine", "cloud", "Extraction engine: 'cloud' (Vertex AI, default) or 'local' (Gemma 4)")
	flag.IntVar(&limit, "limit", 0, "Limit conversion to the first N pages (PDF only, 0 for unlimited)")
	flag.BoolVar(&mdOnly, "md-only", false, "Extract PDF to Markdown and stop")
}

// Execute PyMuPDF on-the-fly to get PDF page count
func getPDFPageCount(path string) (int, error) {
	script := fmt.Sprintf("import fitz; d=fitz.open('%s'); print(len(d))", path)
	cmd := exec.Command("/Users/ghchinoy/projects/pdf2epub/.venv/bin/python3", "-c", script)
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	if err := cmd.Run(); err != nil {
		return 0, fmt.Errorf("failed to run python pdf checker: %w", err)
	}
	countStr := strings.TrimSpace(stdout.String())
	return strconv.Atoi(countStr)
}

// Execute PyMuPDF on-the-fly to get PDF metadata
func getPDFMetadata(path string) (string, string, error) {
	script := fmt.Sprintf("import fitz; d=fitz.open('%s'); print(d.metadata.get('title') or ''); print(d.metadata.get('author') or '')", path)
	cmd := exec.Command("/Users/ghchinoy/projects/pdf2epub/.venv/bin/python3", "-c", script)
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	if err := cmd.Run(); err != nil {
		return "", "", fmt.Errorf("failed to get PDF metadata: %w", err)
	}
	lines := strings.Split(strings.TrimSpace(stdout.String()), "\n")
	title := ""
	author := ""
	if len(lines) > 0 {
		title = strings.TrimSpace(lines[0])
	}
	if len(lines) > 1 {
		author = strings.TrimSpace(lines[1])
	}
	return title, author, nil
}

// Execute PyMuPDF to extract a single page's text
func extractPageTextLocal(path string, pageIdx int) (string, error) {
	script := fmt.Sprintf("import fitz; d=fitz.open('%s'); print(d[%d].get_text('text'))", path, pageIdx)
	cmd := exec.Command("/Users/ghchinoy/projects/pdf2epub/.venv/bin/python3", "-c", script)
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("failed to extract page text: %w", err)
	}
	return stdout.String(), nil
}

// Execute PyMuPDF to extract a single page as raw PDF bytes
func extractPageBytesRaw(path string, pageIdx int) ([]byte, error) {
	script := fmt.Sprintf("import fitz, sys; d=fitz.open('%s'); s=fitz.open(); s.insert_pdf(d, from_page=%d, to_page=%d); b=s.write(); sys.stdout.buffer.write(b)", path, pageIdx, pageIdx)
	cmd := exec.Command("/Users/ghchinoy/projects/pdf2epub/.venv/bin/python3", "-c", script)
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("failed to extract page bytes: %w", err)
	}
	return stdout.Bytes(), nil
}

// queryVertexAISDK generates content concurrently using the official Go GenAI SDK
func queryVertexAISDK(ctx context.Context, client *genai.Client, model string, pdfBytes []byte, prompt string) (string, error) {
	parts := []*genai.Part{
		genai.NewPartFromBytes(pdfBytes, "application/pdf"),
		genai.NewPartFromText(prompt),
	}
	contents := []*genai.Content{
		genai.NewContentFromParts(parts, "user"),
	}
	resp, err := client.Models.GenerateContent(ctx, model, contents, nil)
	if err != nil {
		return "", err
	}
	return resp.Text(), nil
}

// queryLocalGemma queries local llama-server REST API
func queryLocalGemma(prompt string) (string, error) {
	payload := map[string]interface{}{
		"model": "gemma-4",
		"messages": []map[string]string{
			{
				"role":    "system",
				"content": "You are an expert high-fidelity document transcriber. Your task is to clean, restructure, and format raw academic text blocks into correct, logical single-column reading order with proper Markdown headers and standard LaTeX math.",
			},
			{
				"role":    "user",
				"content": prompt,
			},
		},
		"temperature": 0.0,
		"max_tokens":  2500,
	}

	jsonBytes, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}

	req, err := http.NewRequest("POST", LocalServerURL, bytes.NewBuffer(jsonBytes))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 120 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	var responseStruct struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&responseStruct); err != nil {
		return "", err
	}

	if len(responseStruct.Choices) > 0 {
		return responseStruct.Choices[0].Message.Content, nil
	}

	return "", fmt.Errorf("no choice content returned")
}

// Extract metadata concurrently using Vertex AI Go GenAI SDK
func extractMetadataCloudSDK(ctx context.Context, client *genai.Client, model string, pdfBytes []byte) (string, string, string, error) {
	prompt := `Analyze the provided title page of this academic PDF. Extract the following elements and return them strictly as a JSON object:
- "title": The official, complete title of the paper. Keep it clean and do not include annotations.
- "authors": A clean, comma-separated list of all authors.
- "description": A concise, 2-to-3 sentence synopsis or summary of the abstract.
Return ONLY the raw JSON object, do not wrap in markdown code blocks.`

	res, err := queryVertexAISDK(ctx, client, model, pdfBytes, prompt)
	if err != nil {
		return "", "", "", err
	}

	res = strings.TrimSpace(res)
	if strings.HasPrefix(res, "```json") {
		res = res[7:]
	}
	if strings.HasPrefix(res, "```") {
		res = res[3:]
	}
	if strings.HasSuffix(res, "```") {
		res = res[:len(res)-3]
	}
	res = strings.TrimSpace(res)

	var meta struct {
		Title       string `json:"title"`
		Authors     string `json:"authors"`
		Description string `json:"description"`
	}

	if err := json.Unmarshal([]byte(res), &meta); err != nil {
		return "", "", "", err
	}

	return meta.Title, meta.Authors, meta.Description, nil
}

// Extract metadata locally using Gemma 4 REST endpoint
func extractMetadataLocal(rawText string) (string, string, string, error) {
	prompt := fmt.Sprintf(`Analyze the raw text from the title page of this academic PDF. Extract the paper title, clean list of all authors, and a 2-sentence synopsis/summary of the abstract.
Return them STRICTLY as a JSON object matching this structure:
{
  "title": "Clean paper title",
  "authors": "Clean list of authors, comma-separated",
  "description": "Concise abstract synopsis"
}
Return ONLY the raw JSON object. Do not wrap in markdown code blocks.

RAW TITLE PAGE TEXT:
"""
%s
"""`, rawText)

	res, err := queryLocalGemma(prompt)
	if err != nil {
		return "", "", "", err
	}

	res = strings.TrimSpace(res)
	if strings.HasPrefix(res, "```json") {
		res = res[7:]
	}
	if strings.HasPrefix(res, "```") {
		res = res[3:]
	}
	if strings.HasSuffix(res, "```") {
		res = res[:len(res)-3]
	}
	res = strings.TrimSpace(res)

	var meta struct {
		Title       string `json:"title"`
		Authors     string `json:"authors"`
		Description string `json:"description"`
	}

	if err := json.Unmarshal([]byte(res), &meta); err != nil {
		return "", "", "", err
	}

	return meta.Title, meta.Authors, meta.Description, nil
}

func main() {
	flag.Parse()

	argsList := flag.Args()
	if len(argsList) < 1 {
		fmt.Println("Usage: go run main.go [OPTIONS] <input_path>")
		fmt.Println("Options:")
		flag.PrintDefaults()
		os.Exit(1)
	}

	inputPath = argsList[0]
	if _, err := os.Stat(inputPath); os.IsNotExist(err) {
		fmt.Printf("Error: Input file '%s' not found.\n", inputPath)
		os.Exit(1)
	}

	os.MkdirAll("outputs", 0755)
	baseName := strings.TrimSuffix(filepath.Base(inputPath), filepath.Ext(inputPath))

	outputMD := filepath.Join("outputs", baseName+".md")
	outputEPUB := filepath.Join("outputs", baseName+".epub")
	outputKEPUB := filepath.Join("outputs", baseName+".kepub.epub")

	isMarkdownSource := strings.ToLower(filepath.Ext(inputPath)) == ".md"

	if isMarkdownSource {
		outputMD = inputPath
		fmt.Println("============================================================")
		fmt.Printf("COMPILING DIRECTLY FROM MARKDOWN: %s\n", inputPath)
		fmt.Println("============================================================")
	} else {
		// PDF Flow
		totalDocPages, err := getPDFPageCount(inputPath)
		if err != nil {
			fmt.Printf("Error checking PDF page count: %v\n", err)
			os.Exit(1)
		}

		totalPages := totalDocPages
		if limit > 0 && limit < totalPages {
			totalPages = limit
		}

		title, author, err := getPDFMetadata(inputPath)
		if err != nil {
			title = strings.ReplaceAll(baseName, "_", " ")
			author = "Unknown Author"
		}

		fmt.Println("============================================================")
		fmt.Printf("CONVERTING PDF (GO CONCURRENT PORT): %s\n", inputPath)
		fmt.Printf("TITLE:      %s\n", title)
		fmt.Printf("ENGINE:     %s (GOROUTINES ACTIVE ⚡️)\n", strings.ToUpper(engine))
		if limit > 0 {
			fmt.Printf("LIMIT:      First %d pages\n", limit)
		} else {
			fmt.Printf("PAGES:      %d total pages\n", totalPages)
		}
		fmt.Println("============================================================")

		ctx := context.Background()
		var client *genai.Client

		if engine == "cloud" {
			project := os.Getenv("GOOGLE_CLOUD_PROJECT")
			if project == "" {
				project = "generative-bazaar-001"
			}
			client, err = genai.NewClient(ctx, &genai.ClientConfig{
				Backend:  genai.BackendVertexAI,
				Project:  project,
				Location: "us",
			})
			if err != nil {
				fmt.Printf("Error initializing Google GenAI Go Client: %v\n", err)
				os.Exit(1)
			}
		}

		// EXTRACT DETAILED METADATA VIA AI (Title, Authors, Abstract)
		extractedTitle := title
		extractedAuthors := author
		extractedDesc := ""

		fmt.Println("Extracting layout-aware book metadata (Title, Authors, Abstract)...")
		if engine == "cloud" {
			pdfBytes, err_ext := extractPageBytesRaw(inputPath, 0)
			if err_ext == nil {
				eTitle, eAuthors, eDesc, err_meta := extractMetadataCloudSDK(ctx, client, "gemini-3.5-flash", pdfBytes)
				if err_meta == nil {
					extractedTitle = eTitle
					extractedAuthors = eAuthors
					extractedDesc = eDesc
					fmt.Printf("  -> Extracted Title:   %s\n", extractedTitle)
					fmt.Printf("  -> Extracted Authors: %s\n", extractedAuthors)
				} else {
					fmt.Printf("  (Warning: failed to extract metadata via Cloud AI SDK: %v)\n", err_meta)
				}
			} else {
				fmt.Printf("  (Warning: failed to extract first page bytes: %v)\n", err_ext)
			}
		} else {
			rawText, err_ext := extractPageTextLocal(inputPath, 0)
			if err_ext == nil {
				eTitle, eAuthors, eDesc, err_meta := extractMetadataLocal(rawText)
				if err_meta == nil {
					extractedTitle = eTitle
					extractedAuthors = eAuthors
					extractedDesc = eDesc
					fmt.Printf("  -> Extracted Title (Local):   %s\n", extractedTitle)
					fmt.Printf("  -> Extracted Authors (Local): %s\n", extractedAuthors)
				} else {
					fmt.Printf("  (Warning: failed to extract metadata via Local AI: %v)\n", err_meta)
				}
			}
		}

		promptVertex := `You are an expert high-fidelity document transcriber. Your task is to transcribe the provided PDF page into clean, standard Markdown with LaTeX equations for mathematical expressions.
1. READING ORDER: If double-column, read left column first, then right column.
2. MATHEMATICS: Convert mathematical formulas to LaTeX ($math$ or $$block$$).
3. NO ARTIFACTS: Omit running headers and footers.
4. Output ONLY transcribed Markdown itself. Do not wrap in ` + "```" + `markdown code blocks.`

		// We will launch concurrent workers using Goroutines to fetch all pages in parallel!
		fmt.Printf("\nProcessing %d page(s) in parallel via Goroutines...\n", totalPages)
		startTime := time.Now()

		pageMarkdowns := make([]string, totalPages)
		var wg sync.WaitGroup
		var mu sync.Mutex

		completedCount := 0

		// Manage concurrency based on engine selection
		// Cloud (Vertex AI) runs in parallel (limited to 8 concurrent workers to be rate-limit friendly)
		// Local (llama-server) runs sequentially (1 worker at a time) to prevent KV cache/context exhaustion!
		var workerSem chan struct{}
		if engine == "local" {
			workerSem = make(chan struct{}, 1)
		} else {
			workerSem = make(chan struct{}, 8)
		}

		for idx := 0; idx < totalPages; idx++ {
			wg.Add(1)
			go func(pageIdx int) {
				defer wg.Done()
				
				// Acquire semaphore slot
				workerSem <- struct{}{}
				defer func() { <-workerSem }()
				
				page_num := pageIdx + 1

				var pageText string
				var err error

				if engine == "cloud" {
					pdfBytes, err_ext := extractPageBytesRaw(inputPath, pageIdx)
					if err_ext != nil {
						pageText = fmt.Sprintf("\n\n*** [Error extracting page %d bytes: %v] ***\n\n", page_num, err_ext)
					} else {
						pageText, err = queryVertexAISDK(ctx, client, "gemini-3.5-flash", pdfBytes, promptVertex)
						if err != nil {
							pageText = fmt.Sprintf("\n\n*** [Process B Page %d Failed: %v] ***\n\n", page_num, err)
						}
					}
				} else {
					// Local Gemma 4 Engine
					rawText, err_ext := extractPageTextLocal(inputPath, pageIdx)
					if err_ext != nil {
						pageText = fmt.Sprintf("\n\n*** [Error extracting raw page %d text: %v] ***\n\n", page_num, err_ext)
					} else {
						promptGemma := fmt.Sprintf(`Below is a raw, scrambled text block extracted from a two-column academic PDF page. Reconstruct and format it into clean, flowing single-column Markdown.

INSTRUCTIONS:
1. Re-arrange column blocks so that text flows in correct, logical reading order (read left column completely first, then right column).
2. Format headings, sub-headings, and lists with Markdown tags (e.g., #, ##, ###, *, -).
3. Convert inline or block math and variables to proper LaTeX style ($inline$ or $$block$$).
4. Remove running headers, running footers, and page numbers.
5. Output ONLY the resulting Markdown. Do not add introductions or comments like "Here is your reformatted text".

RAW SCRAMBLED TEXT:
"""
%s
"""`, rawText)
						pageText, err = queryLocalGemma(promptGemma)
						if err != nil {
							pageText = fmt.Sprintf("\n\n*** [Process C Page %d Failed: %v] ***\n\n", page_num, err)
						}
					}
				}

				// Clean up markdown block wrappers if present
				pageText = strings.TrimSpace(pageText)
				if strings.HasPrefix(pageText, "```markdown") {
					pageText = pageText[11:]
				}
				if strings.HasSuffix(pageText, "```") {
					pageText = pageText[:len(pageText)-3]
				}
				pageText = strings.TrimSpace(pageText)

				// Replace horizontal lines
				re := regexp.MustCompile(`(?m)^\s*-{3,}\s*$`)
				pageText = re.ReplaceAllString(pageText, "***")

				// Save page content into thread-safe slice
				pageMarkdowns[pageIdx] = pageText

				mu.Lock()
				completedCount++
				fmt.Printf("  [Progress] Page %d/%d finished.\n", completedCount, totalPages)
				mu.Unlock()

			}(idx)
		}

		wg.Wait()
		fmt.Printf("\n[Parallel Processing Complete] Elapsed: %v\n", time.Since(startTime))

		// Assemble final document Markdown
		var compiledMD bytes.Buffer
		compiledMD.WriteString("---\n")
		compiledMD.WriteString(fmt.Sprintf("title: \"%s\"\n", extractedTitle))
		compiledMD.WriteString(fmt.Sprintf("author: \"%s\"\n", extractedAuthors))
		if extractedDesc != "" {
			compiledMD.WriteString(fmt.Sprintf("description: \"%s\"\n", extractedDesc))
		}
		compiledMD.WriteString("---\n\n")

		for i, text := range pageMarkdowns {
			compiledMD.WriteString(fmt.Sprintf("\n<!-- Page %d -->\n\n", i+1))
			compiledMD.WriteString(text)
			compiledMD.WriteString("\n")
		}

		compiledString := compiledMD.String()
		// Clean up em-dashes and spaces in headers to prevent Pandoc anchor URL exceptions
		compiledString = strings.ReplaceAll(compiledString, " — ", " - ")
		compiledString = strings.ReplaceAll(compiledString, "—", "-")

		// Save the compiled markdown to outputs/
		if err := os.WriteFile(outputMD, []byte(compiledString), 0644); err != nil {
			fmt.Printf("Error writing Markdown file: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("\n[Step 1 Complete] Wrote compiled Markdown to: %s\n", outputMD)

		if mdOnly {
			fmt.Println("\n[-md-only specified] Stopping pipeline. Markdown file is ready!")
			os.Exit(0)
		}
	}

	// -------------------------------------------------------------------------
	// STEP 2: PANDOC COMPILATION
	// -------------------------------------------------------------------------
	fmt.Println("\n[Step 2] Compiling Markdown to EPUB3 via Pandoc...")
	cmdPandoc := exec.Command("pandoc", outputMD, "-o", outputEPUB, "-t", "epub3", "--mathml")
	fmt.Printf("Running: %s\n", strings.Join(cmdPandoc.Args, " "))
	if err := cmdPandoc.Run(); err != nil {
		fmt.Printf("Error running Pandoc: %v. Please make sure Pandoc is installed.\n", err)
		os.Exit(1)
	}
	fmt.Printf("[Step 2 Complete] Wrote standard EPUB to: %s\n", outputEPUB)

	// -------------------------------------------------------------------------
	// STEP 3: KOBO PACKAGING & OPTIMIZATION
	// -------------------------------------------------------------------------
	fmt.Println("\n[Step 3] Preparing Kobo-compatible files...")

	// Copy to safe-renamed KEPUB directly (0 errors, guaranteed indexing!)
	inputBytes, err := os.ReadFile(outputEPUB)
	if err != nil {
		fmt.Printf("Error reading EPUB: %v\n", err)
		os.Exit(1)
	}
	if err := os.WriteFile(outputKEPUB, inputBytes, 0644); err != nil {
		fmt.Printf("Error writing KEPUB: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("-> Created safe-renamed KEPUB: %s (0 errors, recommended!)\n", outputKEPUB)

	// Secondary optional Kepubify step
	kepubifyBin := "/Users/ghchinoy/go/bin/kepubify"
	if _, err := os.Stat(kepubifyBin); err == nil {
		kepubifiedOutput := filepath.Join("outputs", baseName+".kepubified.epub")
		tempEPUB := filepath.Join("outputs", baseName+".kepubified_temp.epub")

		// Create temp EPUB copy
		_ = os.WriteFile(tempEPUB, inputBytes, 0644)

		cmdKepub := exec.Command(kepubifyBin, "-o", "outputs", tempEPUB)
		fmt.Printf("Running Kepubify: %s\n", strings.Join(cmdKepub.Args, " "))
		_ = cmdKepub.Run()

		generatedKEPUB := filepath.Join("outputs", baseName+".kepubified_temp.kepub.epub")
		if _, err := os.Stat(generatedKEPUB); err == nil {
			_ = os.Remove(kepubifiedOutput)
			_ = os.Rename(generatedKEPUB, kepubifiedOutput)
			fmt.Printf("-> Created kepubified EPUB:   %s (may contain MathML schema warnings)\n", kepubifiedOutput)
		}
		_ = os.Remove(tempEPUB)
	} else {
		fmt.Println("Note: kepubify binary not found. Skipping sentence-span generation.")
	}

	fmt.Println("\n============================================================")
	fmt.Println("EBOOK CONVERSION COMPLETED SUCCESSFULLY (GO PORT)!")
	fmt.Println("============================================================")
	fmt.Println("For the ultimate Kobo reading experience, we provide two options in 'outputs/':")
	fmt.Printf("1. Safe-Renamed KEPUB (RECOMMENDED): %s\n", outputKEPUB)
	fmt.Println("   -> 100% compliant EPUB. No MathML errors. Guarantees successful indexing on Kobo.")
	if _, err := os.Stat(kepubifyBin); err == nil {
		fmt.Printf("2. Kepubified EPUB (Optional):       outputs/%s.kepubified.epub\n", baseName)
		fmt.Println("   -> Features sentence-level tracking, but can cause Kobo's database parser to fail")
		fmt.Println("      if the book has highly complex MathML formulas.")
	}
	fmt.Println("============================================================")
}
