# OCR-LLM-Local

Lightweight, 100% local OCR tool powered by GLM-OCR (0.9B parameters). Converts scanned documents, forms, receipts, and images into clean Markdown and structured JSON without external cloud dependencies.

## Key Features
- **Strictly Local & Offline**: Operates against local inference backends (llama.cpp or Ollama) with no external data transmission.
- **Dual Interfaces**: 
  - **CLI**: Scriptable single-file and recursive batch processing.
  - **GUI**: Desktop window with native drag-and-drop and live preview.
- **Robust Ingestion**: Direct PDF rendering via pypdfium2 and image validation via Pillow.

## Quickstart

### 1. Start Local Inference Server (llama.cpp)
Run the pre-converted GGUF model with GPU offloading:
```powershell
llama-server -hf ggml-org/GLM-OCR-GGUF --port 8080 -ngl 99 -c 8192 --parallel 1
```

### 2. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 3. Usage
**CLI Mode:**
```powershell
# Single document OCR (Markdown output to stdout)
python -m cli.main document.png

# Batch process directory of PDFs and images
python -m cli.main ./scans/ -o ./output/ -f both --recursive
```

**GUI Mode:**
```powershell
python -m gui.app
```

## Known Limitations & FAQ

### Currency Symbol Handling (`$`)
When currency amounts are formatted without whitespace (e.g. `$123.45` or `$1,200.00`), GLM-OCR's tokenizer parses the `$` directly adjacent to digits as an unclosed inline LaTeX math formula delimiter, which the model's post-processing formula filter strips from the transcribed text (e.g. outputting `.45` or `,200.00`). If amounts are separated by whitespace (e.g. `$ 123.45`) or written with currency codes (`USD 123.45`, `EUR 50.00`), they transcribe 100% accurately. Users should always verify dollar amounts in extracted financial documents, particularly receipts and invoices.

### Resolution & Latency
Default PDF rasterization is set to 100 DPI (~2.7s per page on RTX 3050-class GPUs, ~1.7 MP) to ensure sharp character fidelity while maintaining sub-3s processing times. Higher resolution (150 DPI, ~3.8 MP) increases visual patch prompt tokens to ~4,000+, resulting in ~5.5s per page. Lower resolution (72 DPI) achieves ~1.5s per page but introduces character-level errors on fine print (e.g. "Tkinler").
