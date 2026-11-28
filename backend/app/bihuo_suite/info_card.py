"""Opening info card in spoken order (``bihuo-info-card/1``).

The app-window template (bihuo-03, bundle fk-1109, kind ``app-top``) draws
the opening scene's ``gray`` line (28 px) above its ``blue`` line (48 px) and
fills them with subtitle above title. When the plan splits one spoken phrase
into title and subtitle (title "这款白色", subtitle "头戴耳机，"), the card
reads "头戴耳机，这款白色" (acceptance 2026-11-26, ACCEPT-39 #1). The corner
pill and the footer then repeat the title as the chapter label right next to
it, so the same words sit three times inside one card.

For that split-phrase case only, the compiled card gets the phrase in spoken
order: gray = title, blue = subtitle (the continuation, usually the product
noun), without trailing clause punctuation, and the opening scene's chapter
label is cleared because the card already shows it (the pill keeps its
number). Header and navigation draw title before subtitle and stay as they
are. A subtitle that is not the title's continuation (an eyebrow over a
headline), or a title that ends a clause (a whole phrase followed by the next
sentence), keeps the template mapping; only a label repeating the title is
cleared. Speech, captions and the bundle are unchanged; the record is stored
as ``config.info_card``.
"""

from __future__ import annotations

from typing import Any

VERSION = "bihuo-info-card/1"
ENGINES = {"app-window"}
TRAILING = "，,、；;：: "


def _display(text: str) -> str:
    return text.rstrip(TRAILING) or text


def apply(payload: Any) -> Any:
    cfg = payload.get("config") if isinstance(payload, dict) else None
    if not isinstance(cfg, dict) or cfg.get("engine") not in ENGINES:
        return payload
    title = str(cfg.get("header_title") or "")
    subtitle = str(cfg.get("header_support") or "")
    record: dict[str, Any] = {"version": VERSION, "applied": False}
    found = cfg.get("chapters")
    chapters: list[Any] = found if isinstance(found, list) else []
    opening = next(
        (
            scene
            for scene in chapters
            if isinstance(scene, dict)
            and scene.get("at") == 0
            and "quote" not in scene
            and scene.get("gray") == subtitle
            and scene.get("blue") == title
        ),
        None,
    )
    tokens = (cfg.get("resolved_plan") or {}).get("tokens") or []
    spoken = "".join(str(token.get("text", "")) for token in tokens)
    if opening is None or not title or not subtitle:
        record["reason"] = "no split opening title"
    elif title.rstrip() != title.rstrip(TRAILING) or title + subtitle not in spoken:
        # A title that ends a clause (「这款白色头戴耳机，」) is a whole phrase
        # and the subtitle the next sentence: keep the template mapping.
        record["reason"] = "title and subtitle are separate phrases"
        if (
            opening is not None
            and title
            and opening.get("label")
            in {
                title,
                _display(title),
            }
        ):
            # The card already shows the title; the pill and footer would
            # repeat it a third time (bihuo-03 planning b9f6560d).
            opening["label"] = ""
            record["label_cleared"] = True
    else:
        gray, blue = _display(title), _display(subtitle)
        cleared = opening.get("label") in {title, gray}
        opening.update(gray=gray, blue=blue)
        if cleared:
            opening["label"] = ""
        record.update(
            applied=True,
            gray=gray,
            blue=blue,
            original={"gray": subtitle, "blue": title},
            label_cleared=cleared,
            reason="one spoken phrase split into title and subtitle",
        )
    cfg["info_card"] = record
    return payload
