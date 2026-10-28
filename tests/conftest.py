import os
import hashlib
from pathlib import Path
import shutil
import pytest
import dotenv
import config.settings

REPO_ENV = (Path(__file__).resolve().parent.parent / ".env").resolve()


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="session", autouse=True)
def guard_repo_env_immutability():
    pre_exists = REPO_ENV.exists()
    pre_hash = _hash_file(REPO_ENV) if pre_exists else None

    orig_load_dotenv = dotenv.load_dotenv

    def safe_load_dotenv(dotenv_path=None, **kwargs):
        if dotenv_path is None:
            return False
        if Path(dotenv_path).resolve() == REPO_ENV:
            return False
        return orig_load_dotenv(dotenv_path=dotenv_path, **kwargs)

    dotenv.load_dotenv = safe_load_dotenv
    config.settings.load_dotenv = safe_load_dotenv

    try:
        yield
    finally:
        dotenv.load_dotenv = orig_load_dotenv
        config.settings.load_dotenv = orig_load_dotenv

        post_exists = REPO_ENV.exists()
        post_hash = _hash_file(REPO_ENV) if post_exists else None

        if pre_exists != post_exists or pre_hash != post_hash:
            raise AssertionError(
                f"Repository .env was mutated during test session: "
                f"pre=(exists={pre_exists}, sha256={pre_hash}), "
                f"post=(exists={post_exists}, sha256={post_hash})"
            )


@pytest.fixture(scope="session", autouse=True)
def isolate_test_output_directory(tmp_path_factory: pytest.TempPathFactory):
    """Redirect OCR_OUTPUT_DIR to an isolated session temp directory during tests.

    Prevents tests that invoke export endpoints without an explicit output_dir
    from writing mock test artifacts into the user's real ~/Documents/AksaraSight/output.
    Performs immediate teardown cleanup upon test session completion.
    """
    test_out_dir = tmp_path_factory.mktemp("aksarasight_isolated_output")
    old_output_env = os.environ.get("OCR_OUTPUT_DIR")
    os.environ["OCR_OUTPUT_DIR"] = str(test_out_dir)
    try:
        yield test_out_dir
    finally:
        if old_output_env is not None:
            os.environ["OCR_OUTPUT_DIR"] = old_output_env
        else:
            os.environ.pop("OCR_OUTPUT_DIR", None)
        shutil.rmtree(test_out_dir, ignore_errors=True)
