# PDF-to-EPUB Process Benchmarking Report (5 Page Run)
**Date:** Sunday, June 21, 2026
**Source Document:** `sources/AGI2ASI_2606.12683v1.pdf`
**Sample Size:** 5 pages (Pages 1 to 5)

## Metrics Table

| Pipeline / Method | Latency (Total seconds) | Jaccard Word Overlap | LaTeX Math Symbols ($) | Document Length (Chars) |
| :--- | :---: | :---: | :---: | :---: |
| **Reference Baseline** | *N/A* | *100.0%* | 66 | 21554 |
| Local Heuristics | 0.03s | 95.2% | 0 | 21447 |
| Vertex AI (Gemini 3.5) | 106.08s | 100.0% (Ref) | 66 | 21554 |
| Hybrid Local (Gemma 4 Edge) | 163.52s | 93.9% | 78 | 20576 |

## Architectural Findings & Analysis

### 1. Local Heuristics (Process A)
*   **Pros:** Sizzling speed (sub-second performance). Direct character maps prevent hallucination.
*   **Cons:** Fails completely on multi-column parsing. Retains zero mathematical structures (scrambles LaTeX entirely). Keeps footer and header noise.

### 2. Cloud Visual AI (Process B)
*   **Pros:** Native multimodal document segmentation. Reads columns, formats complex LaTeX formulas, and generates beautiful structural layouts (like Markdown tables) directly from page bytes.
*   **Cons:** Requires external web requests and GCP project credentials.

### 3. Hybrid Local Gemma 4 (Process C)
*   **Pros:** **100% Free, Private, and Offline.** Provides a massive step-up in quality over pure heuristics by utilizing local Apple Silicon Metal GPU acceleration to rebuild paragraph flow.
*   **Cons:** Since raw local text is extracted left-to-right across columns beforehand, the model must guess the layout boundaries. This can cause text repetition or missed headings if the PDF stream is severely disordered.

## Sample Outputs Comparison (Page 1)

### Ground Truth / Reference Baseline Sample:
```markdown
**Google DeepMind**

# From AGI to ASI

Tim Genewein$^1$, Matija Franklin$^1$, Alexander Lerchner$^1$, Laurent Orseau$^1$, Samuel Albanie$^1$, Adam Bales$^1$, Cole Wyeth$^{1,2}$, Stephanie Chan$^1$, Iason Gabriel$^1$, Joel Z. Leibo$^1$, Allan Dafoe$^1$, Marcus Hutter$^{1,3}$, Thore Graepel$^{1,4}$ and Shane Legg$^1$

$^1$Google DeepMind, $^2$University of Waterloo (work conducted while at Google D...
```

### Local Gemma 4 Output Sample:
```markdown
# From AGI to ASI

**Authors:** Tim Genewein$^1$, Matija Franklin$^1$, Alexander Lerchner$^1$, Laurent Orseau$^1$, Samuel Albanie$^1$, Adam Bales$^1$, Cole Wyeth$^{1,2}$, Stephanie Chan$^1$, Iason Gabriel$^1$, Joel Z. Leibo$^1$, Allan Dafoe$^1$, Marcus Hutter$^{1,3}$, Thore Graepel$^1,4$, and Shane Legg$^1$

$^1$Google DeepMind, $^2$University of Waterloo (work conducted while at Google DeepMind),...
```