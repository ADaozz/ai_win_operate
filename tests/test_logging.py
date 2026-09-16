import json
from pathlib import Path

from app.common.logging import configure_logging, get_logger


def test_configure_logging_writes_json_log(tmp_path: Path) -> None:
    configure_logging("INFO", tmp_path)

    get_logger("test").info("test_event", answer=42)

    payload = json.loads((tmp_path / "app.log").read_text(encoding="utf-8").strip())
    assert payload["event"] == "test_event"
    assert payload["answer"] == 42
    assert payload["level"] == "info"

