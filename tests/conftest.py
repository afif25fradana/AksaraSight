import hashlib
from pathlib import Path
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
