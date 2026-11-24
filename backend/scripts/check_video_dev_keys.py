"""检查视频开发环境的密钥文件：是否已填、格式是否正确。

只读本地文件，不发任何网络请求，也不会产生费用；输出里不显示密钥内容。
用法：python3 check_video_dev_keys.py /srv/polaris-dev/videodev/keys.env
退出码：0 = 必填项都没问题；1 = 有必填项缺失或格式错误。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    used_for: str
    kind: str  # "secret" | "url" | "model" | "flag"
    required: bool = False
    needs_flag: str | None = None  # 只有这个开关为 true 时才需要


ITEMS: tuple[Item, ...] = (
    Item(
        "POLARIS_VIDEO_SCRIPT_BASE_URL",
        "文案大模型地址",
        "写稿、拆解、改写、剪辑编排",
        "url",
        required=True,
    ),
    Item(
        "POLARIS_VIDEO_SCRIPT_API_KEY",
        "文案大模型密钥（腾立模型网关）",
        "写稿、拆解、改写、剪辑编排",
        "secret",
        required=True,
    ),
    Item(
        "POLARIS_VIDEO_SCRIPT_MODEL",
        "文案模型名",
        "写稿、拆解、改写",
        "model",
        required=True,
    ),
    Item(
        "POLARIS_VIDEO_EDITING_PLAN_MODEL",
        "剪辑编排模型名",
        "智能剪辑的编排画面",
        "model",
        required=True,
    ),
    Item(
        "POLARIS_VIDEO_EXTRACT_API_KEY",
        "视频提取 / 找对标密钥（EveryInfra）",
        "提取抖音原文、搜对标",
        "secret",
        required=True,
    ),
    Item(
        "POLARIS_QUANYU_API_KEY",
        "数字人口播密钥（全域数字人）",
        "公共形象、生成口播",
        "secret",
        required=True,
    ),
    Item(
        "POLARIS_VIDEO_SCRIPT_FALLBACK_BASE_URL",
        "备用文案大模型地址",
        "主通道出错时备用",
        "url",
    ),
    Item(
        "POLARIS_VIDEO_SCRIPT_FALLBACK_API_KEY",
        "备用文案大模型密钥",
        "主通道出错时备用",
        "secret",
    ),
    Item(
        "POLARIS_SKYHUMAN_API_KEY",
        "备用口播通道密钥（SkyHuman）",
        "口播主通道失败时",
        "secret",
        needs_flag="POLARIS_VIDEO_LIPSYNC_FAILOVER_ENABLED",
    ),
    Item(
        "POLARIS_VIDEO_HASHSIGHT_API_KEY",
        "Hashsight 配音密钥",
        "选用 Hashsight 音色时",
        "secret",
        needs_flag="POLARIS_VIDEO_HASHSIGHT_TTS_ENABLED",
    ),
    Item(
        "POLARIS_TAO_API_KEY",
        "陶配音密钥",
        "选用陶配音音色时",
        "secret",
        needs_flag="POLARIS_VIDEO_TAO_TTS_ENABLED",
    ),
    Item(
        "POLARIS_VIDEO_COSYVOICE_API_KEY",
        "声音克隆密钥（通义 CosyVoice）",
        "克隆专属声音",
        "secret",
        needs_flag="POLARIS_VIDEO_COSYVOICE_ENABLED",
    ),
    Item("POLARIS_YIYUAN_API_KEY", "易元形象动作密钥", "新建定制形象", "secret"),
    Item("POLARIS_WUYE_API_KEY", "无界形象动作密钥", "新建定制形象", "secret"),
)
FLAGS = (
    "POLARIS_VIDEO_SCRIPT_PLANNING_ENABLED",
    "POLARIS_VIDEO_EXTRACT_ENABLED",
    "POLARIS_VIDEO_BENCHMARK_SEARCH_ENABLED",
    "POLARIS_VIDEO_PROVIDERS_ENABLED",
    "POLARIS_VIDEO_LIPSYNC_FAILOVER_ENABLED",
    "POLARIS_VIDEO_HASHSIGHT_TTS_ENABLED",
    "POLARIS_VIDEO_TAO_TTS_ENABLED",
    "POLARIS_VIDEO_COSYVOICE_ENABLED",
)
MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{1,119}$")


def parse(text: str) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    problems: list[str] = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            problems.append(f"第 {number} 行缺少「=」，请写成 名字=值")
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values, problems


def check_value(item: Item, value: str) -> str | None:
    """None = 格式没问题；否则返回中文原因（不含值本身）。"""
    if value != value.strip() or any(ch.isspace() for ch in value):
        return "里面有空格或换行，请删掉"
    if value[:1] in "\"'" or value[-1:] in "\"'":
        return "不要加引号"
    if item.kind == "secret":
        if len(value) < 16:
            return f"太短（{len(value)} 位），可能没有复制完整"
        if len(value) > 512 or not value.isascii() or not value.isprintable():
            return "包含不该有的字符，请重新复制"
    if item.kind == "url" and not re.match(
        r"^https://[A-Za-z0-9.-]+(:\d+)?(/\S*)?$", value
    ):
        return "应以 https:// 开头，例如 https://api.tengliapi.xyz"
    if item.kind == "model" and not MODEL.match(value):
        return "模型名格式不对（只能是字母、数字和 . - _ : /）"
    return None


def report(values: dict[str, str]) -> tuple[list[str], bool]:
    lines: list[str] = []
    ok = True
    for flag in FLAGS:
        value = values.get(flag, "")
        if value and value.lower() not in {"true", "false"}:
            lines.append(f"❌ {flag}：只能填 true 或 false")
            ok = False
    for item in ITEMS:
        value = values.get(item.key, "")
        flag_on = (
            item.needs_flag is not None
            and values.get(item.needs_flag, "").lower() == "true"
        )
        needed = item.required or flag_on
        if not value:
            if needed:
                why = (
                    "必填"
                    if item.required
                    else f"已打开开关 {item.needs_flag}，需要填写"
                )
                lines.append(f"❌ {item.name}：未填写（{why}；用于{item.used_for}）")
                ok = False
            else:
                lines.append(f"·  {item.name}：未填写（选填，用于{item.used_for}）")
            continue
        problem = check_value(item, value)
        if problem:
            lines.append(f"❌ {item.name}：{problem}")
            ok = ok and not needed
        else:
            shown = f"已填（{len(value)} 位）" if item.kind == "secret" else "已填"
            lines.append(f"✅ {item.name}：{shown}")
    return lines, ok


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "/srv/polaris-dev/videodev/keys.env")
    if not path.is_file():
        print(f"找不到密钥文件：{path}")
        return 1
    if path.stat().st_mode & 0o077:
        print("⚠️  密钥文件权限太宽，建议只让自己可读：chmod 600 " + str(path))
    values, problems = parse(path.read_text(encoding="utf-8"))
    lines, ok = report(values)
    print("视频开发环境 · 密钥检查（只检查格式，不联网、不花钱）\n")
    for line in problems + lines:
        print(line)
    print(
        "\n结论："
        + (
            "必填项都已填好，格式正确。可以切到真实后端：videodev.sh real"
            if ok and not problems
            else "还有问题，请按上面的 ❌ 修改后再运行一次。"
        )
    )
    return 0 if ok and not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
