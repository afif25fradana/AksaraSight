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
`powershell
llama-server -hf ggml-org/GLM-OCR-GGUF --port 8080 -ngl 99
`

### 2. Install Dependencies
`powershell
pip install -r requirements.txt
`

### 3. Usage
**CLI Mode:**
`powershell
# Single document OCR (Markdown output to stdout)
python -m cli.main document.png

# Batch process directory of PDFs and images
python -m cli.main ./scans/ -o ./output/ -f both --recursive
`

**GUI Mode:**
`powershell
python -m gui.app
`
