from pathlib import Path

from raspudger.config import Credential, load_credential, parse_env_file

SUB = "CLAUDE_CODE_OAUTH_TOKEN"
API = "ANTHROPIC_API_KEY"
ACCEPTED = (SUB, API)


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.env"
    path.write_text(content)
    return path


def test_loads_subscription_token(tmp_path: Path) -> None:
    credential = load_credential(_write(tmp_path, f"{SUB}=sk-oat\n"), ACCEPTED)
    assert credential == Credential(env_var=SUB, value="sk-oat")


def test_loads_api_key(tmp_path: Path) -> None:
    credential = load_credential(_write(tmp_path, f"{API}=sk-api\n"), ACCEPTED)
    assert credential == Credential(env_var=API, value="sk-api")


def test_prefers_first_accepted_when_both_present(tmp_path: Path) -> None:
    credential = load_credential(_write(tmp_path, f"{API}=sk-api\n{SUB}=sk-sub\n"), ACCEPTED)
    assert credential == Credential(env_var=SUB, value="sk-sub")


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_credential(tmp_path / "nope.env", ACCEPTED) is None


def test_none_present_returns_none(tmp_path: Path) -> None:
    assert load_credential(_write(tmp_path, "OTHER=value\n"), ACCEPTED) is None


def test_empty_value_skipped(tmp_path: Path) -> None:
    credential = load_credential(_write(tmp_path, f"{SUB}=\n{API}=sk-api\n"), ACCEPTED)
    assert credential == Credential(env_var=API, value="sk-api")


def test_ignores_comments_and_strips(tmp_path: Path) -> None:
    credential = load_credential(_write(tmp_path, f'# c\nexport {SUB}="sk-q"\n'), ACCEPTED)
    assert credential is not None
    assert credential.value == "sk-q"


def test_parse_env_file_basic() -> None:
    assert parse_env_file("A=1\nB = two \n# c\nexport C='x'\n") == {
        "A": "1",
        "B": "two",
        "C": "x",
    }
