"""Model manager and cryptographic downloader for pinned local model weights.

Guarantees cryptographic tamper-evidence against the pinned SHA-256 hashes
established at commit time. It does not certify pre-pin source trust.
"""

import hashlib
import logging
import os
from pathlib import Path
import shutil
import sys
import threading
from typing import Any, Callable, Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Pinned Model Specification (Single Source of Truth)
PINNED_MODEL_REPO = "PaddlePaddle/PaddleOCR-VL-1.6-GGUF"
PINNED_MODEL_REVISION = "511b09642bb324401f15f97cc23bc67e8f0a291d"
PINNED_MODEL_FILES = {
    "model": {
        "filename": "PaddleOCR-VL-1.6-GGUF.gguf",
        "sha256": "f3ae46ec885050acf4b3d31944431e1fd90d50664fb09126af4a3c050ba14ee8",
        "size_bytes": 935769056,
    },
    "mmproj": {
        "filename": "PaddleOCR-VL-1.6-GGUF-mmproj.gguf",
        "sha256": "204d757d7610d9b3faab10d506d69e5b244e32bf765e2bab2d0167e65e0a058a",
        "size_bytes": 881770560,
    },
}
TOTAL_MODEL_BYTES = 1817539616
REQUIRED_EXTRA_DISK_BYTES = 500_000_000


def _migrate_legacy_models(
    legacy_dir: Optional[Path] = None,
    canonical_dir: Optional[Path] = None,
) -> bool:
    """Migrate model weights from legacy PascalCase directory to canonical XDG directory."""
    if legacy_dir is None:
        legacy_dir = Path.home() / ".local" / "share" / "AksaraSight" / "models" / "glm-ocr-q8_0"
    if canonical_dir is None:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg_data) if xdg_data and xdg_data.strip() else Path.home() / ".local" / "share"
        canonical_dir = base / "aksarasight" / "models" / "glm-ocr-q8_0"

    try:
        if not legacy_dir.is_dir():
            parent_legacy = legacy_dir.parent
            if parent_legacy.is_dir() and any(parent_legacy.iterdir()):
                legacy_dir = parent_legacy

        if not legacy_dir.is_dir():
            return False

        try:
            if os.path.samefile(legacy_dir, canonical_dir):
                return False
        except (FileNotFoundError, ValueError, OSError):
            pass

        files = [f for f in legacy_dir.iterdir() if f.is_file()]
        if not files:
            try:
                legacy_dir.rmdir()
            except OSError:
                pass
            try:
                legacy_dir.parent.rmdir()
            except OSError:
                pass
            return False


        canonical_dir.mkdir(parents=True, exist_ok=True)
        migrated = False
        for f in files:
            dest = canonical_dir / f.name
            if not dest.exists():
                shutil.move(str(f), str(dest))
                migrated = True

        try:
            legacy_dir.rmdir()
        except OSError:
            pass
        try:
            legacy_dir.parent.rmdir()
        except OSError:
            pass
        try:
            legacy_dir.parent.parent.rmdir()
        except OSError:
            pass

        return migrated
    except Exception as exc:
        logger.warning("Failed to migrate legacy models: %s", exc)
        return False


def prune_legacy_models(models_dir: Optional[Path] = None) -> bool:
    """Safely remove deprecated GLM-OCR model weights if present.

    Handles Windows file lock errors gracefully.
    """
    candidates = []
    if models_dir is not None:
        target = Path(models_dir)
        if target.name == "glm-ocr-q8_0":
            candidates.append(target)
        else:
            candidates.append(target / "glm-ocr-q8_0")
            if target.parent.name == "models":
                candidates.append(target.parent / "glm-ocr-q8_0")
    else:
        if sys.platform != "win32":
            xdg_data = os.environ.get("XDG_DATA_HOME")
            base_dir = Path(xdg_data) if xdg_data and xdg_data.strip() else Path.home() / ".local" / "share"
            candidates.append(base_dir / "aksarasight" / "models" / "glm-ocr-q8_0")
            candidates.append(Path.home() / ".local" / "share" / "AksaraSight" / "models" / "glm-ocr-q8_0")
        else:
            candidates.append(
                Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
                / "AksaraSight"
                / "models"
                / "glm-ocr-q8_0"
            )

    pruned_any = False
    for candidate in candidates:
        if candidate.is_dir():
            try:
                for item in list(candidate.iterdir()):
                    try:
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                    except OSError as file_exc:
                        logger.warning("Could not delete legacy file '%s': %s", item, file_exc)
                candidate.rmdir()
                pruned_any = True
                logger.info("Pruned legacy model directory: %s", candidate)
            except OSError as dir_exc:
                logger.warning("Could not remove legacy model directory '%s': %s", candidate, dir_exc)

    return pruned_any


def get_models_dir() -> Path:
    """Return the target local directory for pinned model weights."""
    if sys.platform != "win32":
        xdg_data = os.environ.get("XDG_DATA_HOME")
        base_dir = Path(xdg_data) if xdg_data and xdg_data.strip() else Path.home() / ".local" / "share"
        canonical_dir = base_dir / "aksarasight" / "models" / "paddleocr-vl-1.6"

        legacy_dir = Path.home() / ".local" / "share" / "AksaraSight" / "models" / "paddleocr-vl-1.6"
        legacy_parent = Path.home() / ".local" / "share" / "AksaraSight" / "models"
        if (legacy_dir.is_dir() and any(legacy_dir.iterdir())) or (legacy_parent.is_dir() and any(legacy_parent.iterdir())):
            _migrate_legacy_models(legacy_dir if legacy_dir.is_dir() else legacy_parent, canonical_dir)

        return canonical_dir

    return (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
        / "AksaraSight"
        / "models"
        / "paddleocr-vl-1.6"
    )


def _compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file on disk."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _verify_candidate(
    model_path: Path,
    mmproj_path: Path,
    verify_hash: bool = False,
) -> bool:
    """Verify size and optional hash of model and mmproj candidate paths."""
    if not (model_path.is_file() and mmproj_path.is_file()):
        return False
    try:
        if model_path.stat().st_size != PINNED_MODEL_FILES["model"]["size_bytes"]:
            return False
        if mmproj_path.stat().st_size != PINNED_MODEL_FILES["mmproj"]["size_bytes"]:
            return False
        if verify_hash:
            if _compute_sha256(model_path).lower() != PINNED_MODEL_FILES["model"]["sha256"].lower():
                return False
            if _compute_sha256(mmproj_path).lower() != PINNED_MODEL_FILES["mmproj"]["sha256"].lower():
                return False
        return True
    except OSError:
        return False


def is_pinned_model_repo(repo: Optional[str]) -> bool:
    """Check if repository ID refers to the pinned PaddleOCR-VL model family."""
    if not repo:
        return True
    clean = repo.strip().lower()
    pinned = PINNED_MODEL_REPO.lower()
    return clean == pinned or clean in ("paddleocr-vl-1.6-gguf", "paddleocr-vl")


def get_local_model_paths(
    repo: Optional[str] = None,
    models_dir: Optional[Path] = None,
    verify_hash: bool = False,
) -> Optional[Tuple[Path, Path]]:
    """Resolve local paths for pinned model weights if present and valid.

    Checks target models directory first, then Hugging Face hub cache snapshot.
    Returns (model_path, mmproj_path) if valid, else None.
    """
    if repo is not None and not is_pinned_model_repo(repo):
        return None

    # Check target models directory
    target_dir = models_dir if models_dir is not None else get_models_dir()
    candidate_local = (
        target_dir / PINNED_MODEL_FILES["model"]["filename"],
        target_dir / PINNED_MODEL_FILES["mmproj"]["filename"],
    )
    if _verify_candidate(candidate_local[0], candidate_local[1], verify_hash=verify_hash):
        return candidate_local

    # Check HF hub cache snapshot
    hf_home = Path(os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface")))
    repo_folder = f"models--{PINNED_MODEL_REPO.replace('/', '--')}"
    snapshot_dir = hf_home / "hub" / repo_folder / "snapshots" / PINNED_MODEL_REVISION
    candidate_hf = (
        snapshot_dir / PINNED_MODEL_FILES["model"]["filename"],
        snapshot_dir / PINNED_MODEL_FILES["mmproj"]["filename"],
    )
    if _verify_candidate(candidate_hf[0], candidate_hf[1], verify_hash=verify_hash):
        return candidate_hf

    return None


_ACTIVE_DOWNLOAD_LOCK = threading.Lock()


class ModelDownloader:
    """Resumable download engine with cryptographic SHA-256 verification.

    Guarantees cryptographic tamper-evidence against the pinned SHA-256 hashes
    established at commit time. It does not certify pre-pin source trust.
    """

    def __init__(
        self,
        dest_dir: Optional[Path] = None,
        session: Optional[requests.Session] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.dest_dir = dest_dir or get_models_dir()
        if session is not None:
            self.session = session
        else:
            default_session = requests.Session()
            default_session.trust_env = False
            self.session = default_session
        self.progress_callback = progress_callback
        self.is_downloading: bool = False
        self.bytes_downloaded: int = 0
        self.total_bytes: int = TOTAL_MODEL_BYTES
        self.current_file: str = ""
        self.error_message: Optional[str] = None
        self.cancel_event: threading.Event = threading.Event()
        self._state_lock: threading.Lock = threading.Lock()

    def cancel(self) -> None:
        """Signal the active download to stop without deleting partial progress."""
        self.cancel_event.set()

    def get_status(self) -> Dict[str, Any]:
        """Return the current download status."""
        with self._state_lock:
            return {
                "is_downloading": self.is_downloading,
                "bytes_downloaded": self.bytes_downloaded,
                "total_bytes": self.total_bytes,
                "current_file": self.current_file,
                "error_message": self.error_message,
                "percent": round((self.bytes_downloaded / self.total_bytes * 100), 2)
                if self.total_bytes > 0
                else 0.0,
            }

    def _notify_progress(self) -> None:
        if not self.progress_callback:
            return
        status = self.get_status()
        try:
            self.progress_callback(status)
        except Exception as cb_exc:
            logger.debug("Error in download progress callback: %s", cb_exc)

    def download(self) -> bool:
        """Execute resumable download with SHA-256 verification.

        Returns:
            bool: True if completed successfully, False if cancelled.

        Raises:
            RuntimeError: If another download is already in progress.
            OSError: If disk space is insufficient.
            ValueError: If downloaded file fails cryptographic hash check.
            requests.RequestException: On network error.
        """
        if not _ACTIVE_DOWNLOAD_LOCK.acquire(blocking=False):
            raise RuntimeError("Download already in progress")

        try:
            return self._execute_download()
        finally:
            _ACTIVE_DOWNLOAD_LOCK.release()

    def _execute_download(self) -> bool:
        try:
            self.dest_dir.mkdir(parents=True, exist_ok=True)

            # Safely prune legacy model directory to free disk space
            prune_legacy_models(self.dest_dir.parent)

            # Check available disk space
            usage = shutil.disk_usage(self.dest_dir)
            required_space = TOTAL_MODEL_BYTES + REQUIRED_EXTRA_DISK_BYTES
            if usage.free < required_space:
                err = f"Insufficient disk space: {usage.free} bytes available, {required_space} bytes required"
                with self._state_lock:
                    self.error_message = err
                    self.is_downloading = False
                self._notify_progress()
                raise OSError(err)

            with self._state_lock:
                self.cancel_event.clear()
                self.is_downloading = True
                self.error_message = None
                self.bytes_downloaded = 0
                self.total_bytes = TOTAL_MODEL_BYTES
            self._notify_progress()

            files_to_download = [
                ("model", PINNED_MODEL_FILES["model"]),
                ("mmproj", PINNED_MODEL_FILES["mmproj"]),
            ]

            http_client = self.session

            for role, spec in files_to_download:
                if self.cancel_event.is_set():
                    with self._state_lock:
                        self.is_downloading = False
                    self._notify_progress()
                    return False

                filename = spec["filename"]
                expected_sha256 = spec["sha256"]
                expected_size = spec["size_bytes"]

                dest_file = self.dest_dir / filename
                part_file = self.dest_dir / f"{filename}.part"

                with self._state_lock:
                    self.current_file = filename

                # Check if file already exists and is valid
                if dest_file.is_file():
                    if dest_file.stat().st_size == expected_size:
                        with self._state_lock:
                            self.current_file = f"Verifying {filename} (SHA-256)..."
                        self._notify_progress()
                        is_valid = _compute_sha256(dest_file).lower() == expected_sha256.lower()
                        with self._state_lock:
                            self.current_file = filename
                        if is_valid:
                            logger.info("Model file already present and verified: %s", filename)
                            with self._state_lock:
                                self.bytes_downloaded += expected_size
                            self._notify_progress()
                            continue
                        else:
                            logger.warning("Existing file invalid or incomplete; re-downloading: %s", filename)
                            dest_file.unlink()
                    else:
                        logger.warning("Existing file invalid or incomplete; re-downloading: %s", filename)
                        dest_file.unlink()

                # Check existing partial file
                existing_bytes = 0
                if part_file.exists():
                    part_size = part_file.stat().st_size
                    if part_size > expected_size:
                        logger.warning("Partial file oversized; discarding: %s", part_file.name)
                        part_file.unlink()
                    elif part_size == expected_size:
                        with self._state_lock:
                            self.current_file = f"Verifying {part_file.name} (SHA-256)..."
                        self._notify_progress()
                        is_valid = _compute_sha256(part_file).lower() == expected_sha256.lower()
                        with self._state_lock:
                            self.current_file = filename
                        if is_valid:
                            os.replace(part_file, dest_file)
                            with self._state_lock:
                                self.bytes_downloaded += expected_size
                            self._notify_progress()
                            continue
                        else:
                            logger.warning("Completed partial file digest mismatch; discarding: %s", part_file.name)
                            part_file.unlink()
                    else:
                        existing_bytes = part_size

                with self._state_lock:
                    self.bytes_downloaded += existing_bytes
                self._notify_progress()

                url = f"https://huggingface.co/{PINNED_MODEL_REPO}/resolve/{PINNED_MODEL_REVISION}/{filename}"
                headers = {"User-Agent": "AksaraSight-Local-Desktop"}
                if existing_bytes > 0:
                    headers["Range"] = f"bytes={existing_bytes}-"

                try:
                    resp = http_client.get(url, headers=headers, stream=True, timeout=30.0)
                    if resp.status_code == 416:
                        logger.warning("HTTP 416 received for %s; clearing corrupt .part file and retrying from byte 0", filename)
                        resp.close()
                        if part_file.exists():
                            try:
                                part_file.unlink()
                            except OSError:
                                pass
                        if existing_bytes > 0:
                            with self._state_lock:
                                self.bytes_downloaded -= existing_bytes
                            existing_bytes = 0
                            self._notify_progress()
                        retry_headers = dict(headers)
                        retry_headers.pop("Range", None)
                        resp = http_client.get(url, headers=retry_headers, stream=True, timeout=30.0)

                    with resp:
                        if resp.status_code == 206:
                            mode = "ab"
                        elif resp.status_code == 200:
                            mode = "wb"
                            if existing_bytes > 0:
                                with self._state_lock:
                                    self.bytes_downloaded -= existing_bytes
                                existing_bytes = 0
                        else:
                            resp.raise_for_status()
                            mode = "wb"

                        with open(part_file, mode) as f_out:
                            for chunk in resp.iter_content(chunk_size=65536):
                                if self.cancel_event.is_set():
                                    logger.info("Download cancelled during streaming: %s", filename)
                                    with self._state_lock:
                                        self.is_downloading = False
                                    self._notify_progress()
                                    return False
                                if chunk:
                                    f_out.write(chunk)
                                    with self._state_lock:
                                        self.bytes_downloaded += len(chunk)
                                    self._notify_progress()
                except Exception as stream_exc:
                    with self._state_lock:
                        self.error_message = str(stream_exc)
                        self.is_downloading = False
                    self._notify_progress()
                    raise

                if self.cancel_event.is_set():
                    with self._state_lock:
                        self.is_downloading = False
                    self._notify_progress()
                    return False

                # Verify SHA-256 of completed .part file
                logger.info("Verifying SHA-256 for %s...", filename)
                computed_sha = _compute_sha256(part_file)
                if computed_sha.lower() != expected_sha256.lower():
                    if part_file.exists():
                        part_file.unlink()
                    err = f"Digest mismatch for {filename}: expected {expected_sha256}, got {computed_sha}"
                    with self._state_lock:
                        self.error_message = err
                        self.is_downloading = False
                    self._notify_progress()
                    raise ValueError(err)

                # Atomically rename to destination
                os.replace(part_file, dest_file)
                logger.info("Successfully verified and placed: %s", dest_file.name)

            with self._state_lock:
                self.is_downloading = False
                self.bytes_downloaded = self.total_bytes
            self._notify_progress()
            return True
        except Exception as exc:
            with self._state_lock:
                self.is_downloading = False
                if self.error_message is None:
                    self.error_message = str(exc)
            self._notify_progress()
            raise
        finally:
            with self._state_lock:
                self.is_downloading = False


_global_downloader: Optional[ModelDownloader] = None
_downloader_lock = threading.Lock()


def get_model_downloader() -> ModelDownloader:
    """Return the shared ModelDownloader singleton instance."""
    global _global_downloader
    with _downloader_lock:
        if _global_downloader is None:
            _global_downloader = ModelDownloader()
        return _global_downloader
