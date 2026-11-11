"""Document the intentional layers of the original foreground subtitle groups."""

_ROOT = "src/engines/workspace/字幕动效_可编辑库_20261105/"
FOREGROUND_SUBTITLE_DEPENDENCIES = {
    "AH-S06": ("font-43a890795ad133d7",),
    "SG-S05": ("font-9dd76f7ab430edd0", "font-aa4560dd8fe56457"),
    "BG-S10": ("font-06b2048c592b1dae",),
    "BG-S11": ("font-06b2048c592b1dae",),
}
FOREGROUND_ROLE_RENDERERS = {
    "AH-S06": (
        (
            _ROOT + "AH-S06/render.py",
            "c7e9cbddb4cb24331a9c3089a0f1c3c3590d665157adb8ae3bbac8cca7a1d9ab",
        ),
    ),
    "SG-S05": (
        (
            _ROOT + "SG-S05/render.py",
            "f607310f0a0010a9d15c1e9fe12e49c3764999573b5d037ad153f286d6770d8e",
        ),
    ),
    "SG-S08": (
        (
            _ROOT + "SG-S08/render.py",
            "9fda50a11d6abf2fc1e7c51e34b0ef75015c732b07fd1704218b8f20b0d3075c",
        ),
        (
            _ROOT + "SG-production/mechanisms.py",
            "48cd8bf1afd634da9fee47a372048f541902112480ad9fce054d825dcc4bcd9f",
        ),
    ),
}
_BG_PIPELINE = (
    _ROOT + "BG-production/pipeline.py",
    "40feca46e328224cdf0497e729ca2c618acf34146f2868395193b17f1ff2047d",
)
for _group, _digest in {
    "BG-S09": "fdcfc3c23ecb56dc2ce196c1a9933644620fed6499468b7296dc2b1fb9e04c74",
    "BG-S10": "46cb08c81a3f2804cead3a7b19a637ac29a31c92cec2a0432cf1bd08bf0bda60",
    "BG-S11": "ea7bdf19211de53be8a1cfb7ae5a127d64c17460000032aaf58b99cd1468b339",
}.items():
    FOREGROUND_ROLE_RENDERERS[_group] = (
        (_ROOT + _group + "/render.py", _digest),
        _BG_PIPELINE,
    )

FOREGROUND_ROLE_REASONS = {
    "AH-S06": "AH-S06 的原生英文位于中心字之后。",
    "SG-S05": "SG-S05 的金字在完成字体轮换后叠于同句前方。",
    "SG-S08": "SG-S08 的引导字退为灰色背衬，前景叠在原位置。",
    "BG-S09": "BG-S09 的白句缩小退灰后留作原生红字背衬。",
    "BG-S10": "BG-S10 的白词拼合并退为金色重点背衬。",
    "BG-S11": "BG-S11 的白句收定后留作原生红字背衬。",
}


def foreground_role_windows(
    group: str, config: dict
) -> list[tuple[list[str], int, int]]:
    events = config["events"]
    if group == "AH-S06":
        start = max(events["center_frame"], events["english_frame"])
        return [(["center", "english"], start, events["clear_frame"])]
    if group == "SG-S05":
        if events["cycle_3"] < events["front_start"] < events["exit_end"]:
            return [
                ([role, "accent"], events["front_start"], events["exit_end"])
                for role in ("lead_1", "lead_2", "lead_3")
            ]
        return []
    if group == "SG-S08":
        back, settled = events["back_start"], events["back_end"]
        accent, end = events["accent_start"], events["exit_end"]
        return [
            (["lead", "back"], back, settled),
            (["lead", "accent"], accent, settled),
            (["back", "accent"], max(back, accent), end),
        ]
    focus = events["focus_frame"]
    if not 0 <= events["retreat_frame"] - focus <= 5:
        return []
    end = config["frames"]
    if group == "BG-S10":
        right = events["right_frame"]
        return [
            (["left", "right"], right, right + 5),
            (["left", "focus"], focus, end),
            (["right", "focus"], focus, end),
        ]
    return [(["body", "focus"], focus, end)]
