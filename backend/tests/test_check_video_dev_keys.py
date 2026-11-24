import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_keys", Path(__file__).resolve().parents[1] / "scripts/check_video_dev_keys.py"
)
check = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = check
spec.loader.exec_module(check)

GOOD = "x" * 32


def run(text):
    values, problems = check.parse(text)
    lines, ok = check.report(values)
    return lines, ok and not problems


def test_empty_template_fails_on_required_items_only():
    lines, ok = run("POLARIS_VIDEO_SCRIPT_MODEL=deepseek-v4.1\nPOLARIS_VIDEO_EDITING_PLAN_MODEL=m1\n")
    assert not ok
    assert any("文案大模型密钥" in line and "❌" in line for line in lines)
    assert any("声音克隆" in line and line.startswith("·") for line in lines)


def test_filled_required_items_pass_and_values_are_never_printed():
    text = "\n".join([
        "POLARIS_VIDEO_SCRIPT_BASE_URL=https://api.tengliapi.xyz",
        f"POLARIS_VIDEO_SCRIPT_API_KEY={GOOD}a",
        "POLARIS_VIDEO_SCRIPT_MODEL=deepseek-v4.1-flash-1017",
        "POLARIS_VIDEO_EDITING_PLAN_MODEL=deepseek-v4.1-flash-1017",
        f"POLARIS_VIDEO_EXTRACT_API_KEY={GOOD}b",
        f"POLARIS_QUANYU_API_KEY={GOOD}c",
    ])
    lines, ok = run(text)
    assert ok
    assert not any(GOOD in line for line in lines)
    assert any("已填（33 位）" in line for line in lines)


def test_format_problems_are_reported_in_plain_words():
    item = next(i for i in check.ITEMS if i.key == "POLARIS_QUANYU_API_KEY")
    assert "太短" in check.check_value(item, "short")
    assert "引号" in check.check_value(item, '"' + GOOD + '"')
    assert "空格" in check.check_value(item, GOOD[:10] + " " + GOOD)
    url = next(i for i in check.ITEMS if i.key == "POLARIS_VIDEO_SCRIPT_BASE_URL")
    assert "https://" in check.check_value(url, "http://api.example.com")


def test_optional_key_becomes_required_when_its_switch_is_on():
    lines, _ = run("POLARIS_VIDEO_COSYVOICE_ENABLED=true\n")
    assert any("声音克隆" in line and "❌" in line for line in lines)
    lines, _ = run("POLARIS_VIDEO_COSYVOICE_ENABLED=maybe\n")
    assert any("只能填 true 或 false" in line for line in lines)
