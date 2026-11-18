"""Keep reference typography geometry separate from its source wordmarks."""


def instruction(language: str) -> str:
    locale = language.lower().split("-", 1)[0]
    fallback = {"zh": "商品展示", "en": "PRODUCT"}.get(locale)
    replacement = (
        f"use exactly '{fallback}' for a dominant headline, or leave that text area clean. "
        if fallback else "leave that text area clean. "
    )
    return (
        "SOURCE TEXT REPLACEMENT — binding on every analysis field and image zone\n"
        "A giant background wordmark is source brand text, even when described as "
        "letter-shaped scenery or a graphic prop. Its letters are NOT part of the "
        "locked scene. Preserve the text area's position, scale, alignment and "
        "visual weight, but replace the complete letter shapes and wording. Never "
        "copy a source brand, a partial name or a near-spelling as decorative art. "
        "If the user supplied no separate approved headline, "
        f"{replacement}"
        "Omit other unapproved source wording rather than recreating it. Descriptions "
        "of source words in reference analysis, typography zones, composition "
        "anchors or an execution prompt are observations to replace, never permission "
        "to render those words. This rule overrides scene/background preservation "
        "and copied case prose. Preserve marks actually printed on the user's product "
        "photo; do not transfer marks from the visual-strategy reference."
    )
