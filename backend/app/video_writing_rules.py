"""Website interpretation of the preserved colleague package, with file identity."""

import re
from pathlib import Path

from .motion_library import WRITING_SHA256, inside, read_json, sha256
from .video_writing_contracts import ReferenceSentence, WritingReference

MANIFEST = Path(__file__).parent / "data/video_writing_bundle.json"
RULES = [
    "参考原文、拆解、客户事实和新稿独立；不能把参考品牌、身份、价格、净含量、承诺当成客户事实。",
    "以句ID逐段解释钩子、论证与收口功能，全部结论有原句依据，不写没有证据的‘很抓人’。",
    "单条纯文字只能分析文字；未提供画面、互动数据或跨号样本，就标为未核验，不编镜头、时长、相关系数或爆款原因。",
    "来源方法的示例数值与历史比例不是本批数据，也不是必须填满的模板槽。缺数据不编事实。",
    "保留原段落功能与句数，一句对一句做事实映射，不额外加结尾、口号、经历或效果。",
    "unknown事实不能使用；声明为user_declared的事实仍只是用户提供，不能冒充独立核实或机构背书。",
    "先列identity/product/story替换映射，再逐句写稿；不可抄与必须改的内容按原功能整段替换，不残留旧事实。",
    "禁止自动继承参考价格和净含量，服从当前事实卡禁词、禁价格/净含量/疗效要求；需要数字但没有可靠数字时登记缺项。",
    "原shape checker只查结构、残留、禁词与字数；"
    "PASS不等于意思正确。每句对义仍由用户审阅。",
    "只输出严格JSON数据，不输出时间猜测、可执行代码、下载命令、工具调用或文件路径。",
]


def verify_writing_package(package: Path) -> dict:
    manifest = read_json(MANIFEST)
    if manifest["archive_sha256"] != WRITING_SHA256:
        raise ValueError("Writing method release differs")
    for relative, expected in manifest["files"].items():
        path = inside(package, relative)
        if not path.is_file() or sha256(path) != expected:
            raise ValueError("Original writing method file identity failed")
    return {
        "release": WRITING_SHA256,
        "files": len(manifest["files"]),
        "manifest_sha256": sha256(MANIFEST),
    }


def sentence_units(text: str) -> list[ReferenceSentence]:
    # Same sentence-ending set as the colleague's shadow checker. These are text
    # positions, not fabricated audio or video clocks.
    values = [s.strip() for s in re.findall(r"[^。！？!?；;…\n]+[。！？!?；;…]?", text)]
    values = [s for s in values if len(re.sub(r"[^\w\u4e00-\u9fff]", "", s)) >= 2]
    return [ReferenceSentence(id=f"r{i:04}", text=s) for i, s in enumerate(values)]


def reference_from_project(row: dict) -> WritingReference:
    text = row.get("original_text", "").strip()
    units = sentence_units(text)
    if not units:
        raise ValueError("Reference needs real text sentences before analysis")
    return WritingReference(
        reference_id=row["id"],
        original_text=text,
        source_url=row.get("url", ""),
        source_note=row.get("note", ""),
        sentences=units,
    )
