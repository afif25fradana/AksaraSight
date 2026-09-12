"""Benchmark sample_contract.pdf across multiple DPI settings on live llama-server."""

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.client import VisionClient
from core.pipeline import ingest

def run_benchmark():
    client = VisionClient()
    pdf_path = Path("sample_contract.pdf").resolve()
    
    dpis = [150, 120, 100, 72]
    results = []

    print("=" * 80)
    print(f"BENCHMARKING FULL-PAGE PDF: {pdf_path.name}")
    print("=" * 80)

    for dpi in dpis:
        pages = list(ingest(pdf_path, dpi=dpi))
        print(f"\n--- Testing DPI = {dpi} ({pages[0].width}x{pages[0].height} px, {pages[0].width*pages[0].height/1e6:.2f} MP) ---")
        
        # Warm-up run on page 1
        client.complete(pages[0].image_b64)
        
        page_stats = []
        for p in pages:
            text, raw, latency = client.complete(p.image_b64)
            timings = raw.get("timings", {})
            usage = raw.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            prompt_ms = timings.get("prompt_ms", 0.0)
            predicted_ms = timings.get("predicted_ms", 0.0)
            
            page_stats.append({
                "page_num": p.page_num,
                "width": p.width,
                "height": p.height,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "prompt_ms": prompt_ms,
                "predicted_ms": predicted_ms,
                "server_total_ms": prompt_ms + predicted_ms,
                "client_latency_s": latency,
                "text_snippet": text[:120].replace("\n", " "),
                "full_text": text,
            })
            print(f"  Page {p.page_num}: Client={latency:.2f}s | Server={prompt_ms+predicted_ms:.0f}ms (prompt={prompt_ms:.0f}ms, gen={predicted_ms:.0f}ms) | {prompt_tokens} prompt tok, {completion_tokens} gen tok")

        results.append({
            "dpi": dpi,
            "dimensions": f"{pages[0].width}x{pages[0].height}",
            "pages": page_stats
        })

    with open("dpi_benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\nBenchmark saved to dpi_benchmark_results.json")

if __name__ == "__main__":
    run_benchmark()
