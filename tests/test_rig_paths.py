import pytest

from rig_mcp.paths import is_safe_path_segment


@pytest.mark.parametrize("name", ["boot.txt", "dump", "a_b-c.1", "CVE-2024-1"])
def test_safe_names_pass(name: str) -> None:
    assert is_safe_path_segment(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "",  # empty
        ".hidden",  # leading dot
        "..",  # parent reference (caught by the leading dot)
        "../escape",  # separator
        "a/b",  # forward separator
        "a\\b",  # backslash separator
        "a\0b",  # NUL byte
    ],
)
def test_unsafe_names_rejected(name: str) -> None:
    assert is_safe_path_segment(name) is False
