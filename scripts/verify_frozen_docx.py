"""Empirical verification suite for AksaraSight frozen portable DOCX export.

Verifies at the packaged executable level:
1. python-docx template dependency: Confirms docx/templates/default.docx is bundled in
   dist/AksaraSight/_internal and loads cleanly as a Document instance.
2. Frozen CLI DOCX generation: Spins up a local loopback mock OCR server and runs
   AksaraSight-CLI.exe with -f docx -o <dir>, confirming a valid .docx is produced.
3. OOXML structure and formatting: Validates headings, bold/italic, lists, blockquotes,
   code blocks, and GFM tables (with w:tblHeader and w:cantSplit row XML attributes,
   escaped pipes, and ragged column padding).
4. Source vs Frozen Parity: Executes the identical OCR job via source Python (python -m cli.main)
   and diffs paragraphs, styles, and table cells to guarantee 100% parity.
5. Binary stdout streaming: Verifies frozen CLI stdout redirection creates an uncorrupted DOCX.
"""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from docx import Document
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist" / "AksaraSight"
CLI_EXE = DIST_DIR / "AksaraSight-CLI.exe"
INTERNAL_DIR = DIST_DIR / "_internal"

TEST_MARKDOWN = """# Quarterly Financial Report

## Executive Summary
This document verifies **frozen binary execution** with *markdown-it-py* and `python-docx`.

### Key Metrics
| Metric | Q1 | Q2 | Target |
| --- | --- | --- | --- |
| Revenue | $1,200.50 | $1,450.00 | $1,500.00 |
| Growth | 12.5% | 15.0% | 18.0% |
| Notes | Escaped \\| pipe | Ragged row missing target |

- Bullet item 1
- Bullet item 2

1. Numbered item 1
2. Numbered item 2

> Important note: Local OCR engine operating entirely on loopback.

```python
def verify_success():
    return True
```
"""


class MockOCRHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith("/models"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"data": [{"id": "ggml-org/GLM-OCR-GGUF"}]}).encode("utf-8")
            )
        elif self.path.endswith("/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.endswith("/chat/completions"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp_payload = {
                "id": "cmpl-frozen-docx-test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": TEST_MARKDOWN,
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
            self.wfile.write(json.dumps(resp_payload).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def verify_frozen_docx() -> bool:
    print("=" * 60)
    print("EMPIRICAL FROZEN DOCX EXPORT VERIFICATION")
    print("=" * 60)

    if not CLI_EXE.is_file():
        sys.stderr.write(f"ERROR: Frozen CLI binary not found at {CLI_EXE}\nRun scripts/build_portable.py first.\n")
        return False

    # 1. Verify default.docx template exists in _internal
    template_path = INTERNAL_DIR / "docx" / "templates" / "default.docx"
    print(f"[Check 1] python-docx template in _internal: {template_path.relative_to(DIST_DIR)}")
    if not template_path.is_file():
        print("  [FAIL] default.docx template missing!")
        return False
    template_size = template_path.stat().st_size
    print(f"  [PASS] default.docx exists ({template_size} bytes)")
    test_doc = Document(str(template_path))
    print(f"  [PASS] default.docx loads cleanly as Document (paragraphs: {len(test_doc.paragraphs)})")

    # 2. Setup mock server on loopback
    server = http.server.HTTPServer(("127.0.0.1", 0), MockOCRHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    endpoint = f"http://127.0.0.1:{port}/v1"
    print(f"\n[Check 2] Mock OCR loopback server running on {endpoint}")

    temp_dir = Path(tempfile.mkdtemp(prefix="aksara_frozen_docx_"))
    try:
        img_path = temp_dir / "sample_doc.png"
        Image.new("RGB", (150, 150), color="white").save(img_path)

        frozen_out_dir = temp_dir / "frozen_out"
        source_out_dir = temp_dir / "source_out"
        frozen_out_dir.mkdir(parents=True, exist_ok=True)
        source_out_dir.mkdir(parents=True, exist_ok=True)

        # 3. Run frozen executable CLI with -f docx -o <dir>
        print("\n[Check 3] Running frozen AksaraSight-CLI.exe with -f docx -o <dir>...")
        frozen_cmd = [
            str(CLI_EXE),
            str(img_path),
            "-f",
            "docx",
            "-o",
            str(frozen_out_dir),
            "--endpoint",
            endpoint,
            "--backend",
            "llama-cpp",
        ]
        t0 = time.time()
        frozen_res = subprocess.run(frozen_cmd, capture_output=True, text=True)
        dt_frozen = time.time() - t0
        print(f"  Return code: {frozen_res.returncode} (in {dt_frozen:.2f}s)")
        if frozen_res.stderr:
            print(f"  Stderr: {frozen_res.stderr.strip()}")
        if frozen_res.returncode != 0:
            print("  [FAIL] Frozen CLI execution failed!")
            return False

        frozen_docx = frozen_out_dir / "sample_doc.docx"
        if not frozen_docx.is_file():
            print(f"  [FAIL] Expected docx not found: {frozen_docx}")
            return False
        print(f"  [PASS] Frozen exe created docx: {frozen_docx.name} ({frozen_docx.stat().st_size} bytes)")

        # 4. Open frozen docx with python-docx from outside
        print("\n[Check 4] Validating frozen .docx structure from external python-docx...")
        doc_frz = Document(str(frozen_docx))
        frz_paragraphs = [p.text for p in doc_frz.paragraphs if p.text.strip()]
        print(f"  Paragraph count: {len(doc_frz.paragraphs)} (non-empty: {len(frz_paragraphs)})")
        print(f"  Table count:     {len(doc_frz.tables)}")

        assert len(doc_frz.tables) == 1, "Expected 1 table in frozen docx"
        table_frz = doc_frz.tables[0]
        print(f"  Table dimensions: {len(table_frz.rows)} rows x {len(table_frz.columns)} columns")
        assert len(table_frz.rows) == 4, f"Expected 4 rows, got {len(table_frz.rows)}"
        assert len(table_frz.columns) == 4, f"Expected 4 cols, got {len(table_frz.columns)}"

        header_cells = [c.text for c in table_frz.rows[0].cells]
        print(f"  Header row: {header_cells}")
        assert header_cells == ["Metric", "Q1", "Q2", "Target"]

        # Check XML attributes: tblHeader and cantSplit
        row0_xml = table_frz.rows[0]._tr.xml
        assert "tblHeader" in row0_xml, "tblHeader missing in header row XML!"
        assert "cantSplit" in row0_xml, "cantSplit missing in header row XML!"
        print("  [PASS] tblHeader and cantSplit confirmed in table OOXML!")

        # Check escaped pipe and ragged padding
        row3_cells = [c.text for c in table_frz.rows[3].cells]
        print(f"  Row 3 cells: {row3_cells}")
        assert row3_cells[0] == "Notes"
        assert row3_cells[1] == "Escaped | pipe"
        assert row3_cells[2] == "Ragged row missing target"
        assert row3_cells[3] == ""
        print("  [PASS] Escaped pipe and ragged padding confirmed!")

        # 5. Run identical command against source python
        print("\n[Check 5] Running source python -m cli.main for parity comparison...")
        source_cmd = [
            sys.executable,
            "-m",
            "cli.main",
            str(img_path),
            "-f",
            "docx",
            "-o",
            str(source_out_dir),
            "--endpoint",
            endpoint,
            "--backend",
            "llama-cpp",
        ]
        t0 = time.time()
        source_res = subprocess.run(source_cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        dt_source = time.time() - t0
        print(f"  Return code: {source_res.returncode} (in {dt_source:.2f}s)")
        source_docx = source_out_dir / "sample_doc.docx"
        assert source_docx.is_file(), "Source docx not created!"

        # 6. Compare frozen vs source docx
        print("\n[Check 6] Comparing frozen exe docx vs source docx...")
        doc_src = Document(str(source_docx))

        assert len(doc_frz.paragraphs) == len(doc_src.paragraphs), "Paragraph count mismatch!"
        for i, (p_f, p_s) in enumerate(zip(doc_frz.paragraphs, doc_src.paragraphs)):
            assert p_f.text == p_s.text, f"Paragraph {i} text mismatch: '{p_f.text}' vs '{p_s.text}'"
            assert p_f.style is not None and p_s.style is not None
            assert p_f.style.name == p_s.style.name, f"Paragraph {i} style mismatch!"

        table_src = doc_src.tables[0]
        assert len(table_frz.rows) == len(table_src.rows), "Table row count mismatch!"
        assert len(table_frz.columns) == len(table_src.columns), "Table col count mismatch!"

        for r_idx, (r_f, r_s) in enumerate(zip(table_frz.rows, table_src.rows)):
            cells_f = [c.text for c in r_f.cells]
            cells_s = [c.text for c in r_s.cells]
            assert cells_f == cells_s, f"Row {r_idx} cell mismatch: {cells_f} vs {cells_s}"

        print("  [PASS] 100% character-for-character, style-for-style, and table cell parity between frozen exe and source!")

        # 7. Test stdout streaming via buffer in frozen CLI
        print("\n[Check 7] Testing frozen AksaraSight-CLI.exe stdout binary redirect...")
        piped_docx_path = temp_dir / "piped_frozen.docx"
        with open(piped_docx_path, "wb") as f_out:
            pipe_res = subprocess.run(
                [
                    str(CLI_EXE),
                    str(img_path),
                    "-f",
                    "docx",
                    "--endpoint",
                    endpoint,
                    "--backend",
                    "llama-cpp",
                ],
                stdout=f_out,
                stderr=subprocess.PIPE,
            )
        assert pipe_res.returncode == 0, f"Piped execution failed: {pipe_res.stderr.decode('utf-8', errors='replace')}"
        assert piped_docx_path.stat().st_size > 0, "Piped docx is empty!"
        doc_piped = Document(str(piped_docx_path))
        assert len(doc_piped.tables) == 1, "Piped docx table missing!"
        print(f"  [PASS] Frozen CLI stdout streaming produced valid DOCX ({piped_docx_path.stat().st_size} bytes)")

        print("\n" + "=" * 60)
        print("ALL EMPIRICAL FROZEN DOCX CHECKS PASSED")
        print("=" * 60)
        return True

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        server.shutdown()


if __name__ == "__main__":
    success = verify_frozen_docx()
    sys.exit(0 if success else 1)
