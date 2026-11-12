"""Keep readable body text dominant; narrow oversized model-selected accents.

This is a deterministic planning/layout rule, applied once before rendering.
It only selects lexical content inside the model's existing accent ranges.
Speech, cue boundaries, timing and material placement are never changed.
"""

import copy
import math
import re
from functools import lru_cache
from typing import Any

from .video_editing_captioning import tokenizer

POLICY = "sparse-keyword-emphasis/1"
FUNCTION_WORDS = frozenset(
    {
        "有没有",
        "是不是",
        "能不能",
        "是否",
        "可以",
        "需要",
        "进行",
        "这个",
        "这些",
        "自己",
        "我们",
        "你们",
        "他们",
        "再看",
        "先看",
        "最后",
        "然后",
        "现在",
        "已经",
        "才能",
        "一下",
    }
)


def readable(text: str) -> int:
    return len(re.findall(r"\w", text))


def emphasis_budget(text: str) -> int:
    count = readable(text)
    return 0 if count < 4 else min(6, max(2, math.ceil(count * 0.35)))


@lru_cache(maxsize=1)
def _tagger() -> Any:
    from jieba.posseg import POSTokenizer

    return POSTokenizer(tokenizer())


def _words(text: str) -> list[tuple[int, int, str, str]]:
    result = []
    offset = 0
    for item in _tagger().cut(text, HMM=False):
        result.append((offset, offset + len(item.word), item.word, item.flag))
        offset += len(item.word)
    return result


def sparse_caption_emphasis(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = copy.deepcopy(rows)
    for row in result:
        total_budget = emphasis_budget(row["text"])
        used = 0
        selected_count = 0
        audit = []
        accents: list[str] = []
        for line in row["lines"]:
            text = line["text"]
            original = line["emphasis_spans"]
            budget = min(emphasis_budget(text), total_budget - used)
            accent_count = sum(readable(text[a:b]) for a, b in original)
            if accent_count <= budget and selected_count + len(original) <= 2:
                selected = original
            else:
                words = _words(text)
                candidates = []
                for a, b in original:
                    fragment = text[a:b]
                    contained = [w for w in words if a <= w[0] and w[1] <= b]
                    # Preserve an already small, meaningful model phrase first.
                    if (
                        0 < readable(fragment) <= budget
                        and any(
                            flag.startswith(("n", "v", "a", "m", "eng"))
                            for _, _, _, flag in contained
                        )
                        and not any(
                            word in FUNCTION_WORDS for _, _, word, _ in contained
                        )
                        and not any(
                            flag.startswith(("r", "p", "d", "c", "u"))
                            for _, _, _, flag in contained
                        )
                    ):
                        candidates.append((100, a, b))
                for a, b, word, flag in words:
                    if not any(start <= a and b <= stop for start, stop in original):
                        continue
                    size = readable(word)
                    if not 2 <= size <= budget or word in FUNCTION_WORDS:
                        continue
                    score = (
                        80
                        if flag.startswith(("n", "eng"))
                        else 60
                        if flag.startswith("v")
                        else 40
                        if flag.startswith("a")
                        else 0
                    )
                    if score:
                        candidates.append((score, a, b))
                # Some domain nouns are split into two single Han characters
                # by the dictionary (for example 主/图). Keep the compound noun.
                for left, right in zip(words, words[1:], strict=False):
                    a, middle, word_a, flag_a = left
                    start_b, b, word_b, flag_b = right
                    if (
                        middle == start_b
                        and readable(word_a) == readable(word_b) == 1
                        and flag_a.startswith(("n", "a", "b"))
                        and flag_b.startswith("n")
                        and budget >= 2
                        and any(start <= a and b <= stop for start, stop in original)
                    ):
                        candidates.append((85, a, b))
                selected = []
                count = 0
                for _, a, b in sorted(
                    candidates, key=lambda c: (-c[0], c[1], -(c[2] - c[1]))
                ):
                    size = readable(text[a:b])
                    if (
                        selected_count + len(selected) >= 2
                        or count + size > budget
                        or any(a < y and x < b for x, y in selected)
                    ):
                        continue
                    selected.append([a, b])
                    count += size
                selected.sort()
            used += sum(readable(text[a:b]) for a, b in selected)
            selected_count += len(selected)
            if selected != original:
                audit.append(
                    {"text": text, "model_spans": original, "render_spans": selected}
                )
            line["emphasis_spans"] = selected
            accents.extend(text[a:b] for a, b in selected)
        row["emphasis"] = accents[0] if accents else ""
        row["emphasis_policy"] = POLICY
        row["emphasis_characters"] = used
        row["body_characters"] = readable(row["text"]) - used
        row["emphasis_adjustments"] = audit
    return result
