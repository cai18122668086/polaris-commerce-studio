"""Versioned composition slots built from the preserved Motion catalog."""

from copy import deepcopy

from .video_editing_azl_panels import AZL_DEPENDENCIES, AZL_GROUPS, azl_binding
from .video_editing_azl_panels import AZL_TEMPLATE_ID as AZL_TEMPLATE_ID
from .video_editing_browser_clocks import (
    CARD_GROUP,
    FRUIT_LIST_FONTS,
    FRUIT_LIST_GROUP,
    FRUIT_LIST_TEMPLATE_ID,
    LIVE_SPLIT_GROUPS,
    LIVE_SPLIT_TEMPLATE_ID,
    NUMBERED_GROUP,
    SPLIT_HORIZONTAL,
    SPLIT_TITLE_FONT,
    SPLIT_VERTICAL,
)
from .video_editing_browser_rotation import ROTATION_GROUP, ROTATION_MATTE
from .video_editing_contracts import SemanticPlan
from .video_editing_cut_scenes import CUT_GROUPS, CUT_TEMPLATE_ID
from .video_editing_cxbr import CXBR_DEPENDENCIES, CXBR_PURPOSES, cxbr_binding
from .video_editing_cxbr import CXBR_TEMPLATE_ID as CXBR_TEMPLATE_ID
from .video_editing_handoff_scenes import HANDOFF_GROUPS, HANDOFF_TEMPLATE_ID
from .video_editing_hypit import HY_PICTURE_TEMPLATE_ID, PICTURE_GROUP
from .video_editing_hypit_foreground import FOREGROUND_MATTE
from .video_editing_hypit_strips import (
    DETAIL_CARDS_TEMPLATE_ID,
    LIVE_STRIP_GROUP,
    PRICE_CARD_GROUP,
    SLANT_GROUP,
)
from .video_editing_judgment import JUDGMENT_BRUSH_FONT, JUDGMENT_GROUP
from .video_editing_line_branch import LINE_BRUSH_FONT, LINE_GROUP
from .video_editing_native_content import PACKAGE_GROUP, YEAR_GROUP
from .video_editing_presenter_motion import (
    MOTION_FONT,
    MOTION_MATTE,
    PRESENTER_MOTION_GROUPS,
    motion_binding,
)
from .video_editing_question_branch import QUESTION_FONT, QUESTION_GROUP
from .video_editing_question_card import QUESTION_CARD_A_FONTS, QUESTION_CARD_GROUP
from .video_editing_story_panels import PANEL_GROUPS, PANEL_TEMPLATE_ID
from .video_editing_subtitle_foreground import FOREGROUND_SUBTITLE_DEPENDENCIES
from .video_editing_unified_scenes import (
    UNIFIED_EXPANDED_GROUPS,
    UNIFIED_EXPANDED_TEMPLATE_ID,
    UNIFIED_EXPLANATION_GROUPS,
    UNIFIED_EXPLANATION_TEMPLATE_ID,
    UNIFIED_GROUPS,
    UNIFIED_TEMPLATES,
    YEAR_BINDING,
    YEAR_FONT,
    unified_binding,
)
from .video_editing_unified_scenes import UNIFIED_TEMPLATE_ID as UNIFIED_TEMPLATE_ID
from .video_editing_yy6_scenes import YY6_GROUPS, yy6_binding
from .video_editing_yy_openings import (
    YY_OPENING_ALL_GROUPS,
    YY_OPENING_DEPENDENCIES,
    YY_OPENING_EXPANDED_GROUPS,
    YY_OPENING_GROUPS,
    yy_opening_binding,
)

MIN_OVERLAY_TYPES = 5
PREFERRED_OVERLAY_TYPES = 10
LEGACY_PICTURE_TEMPLATE_ID = "picture-compare-v1"
PICTURE_TEMPLATE_ID = "picture-compare-v2"
ROTATION_TEMPLATE_ID = "rotation-cards-v1"
PRESENTER_TEMPLATE_ID = "presenter-openings-v1"
PRESENTER_MOTION_TEMPLATE_ID = "presenter-reframing-v1"
YY_OPENING_TEMPLATE_ID = "yy-presenter-openings-v1"
YY_OPENING_EXPANDED_TEMPLATE_ID = "yy-presenter-openings-v2"
YY_OPENING_ALL_TEMPLATE_ID = "yy-presenter-openings-v3"
YY_OPENING_TEMPLATES = frozenset(
    {
        YY_OPENING_TEMPLATE_ID,
        YY_OPENING_EXPANDED_TEMPLATE_ID,
        YY_OPENING_ALL_TEMPLATE_ID,
    }
)
JUDGMENT_TEMPLATE_ID = "evidence-judgment-v1"
QUESTION_CARD_TEMPLATE_ID = "question-card-story-v1"
EXPLAINER_TEMPLATE_ID = "explainer-steps-v1"
PACKAGE_TEMPLATE_ID = "package-specs-v1"
LINE_TEMPLATE_ID = "line-story-v1"
SUBTITLE_STORY_TEMPLATE_ID = "subtitle-story-v1"
SUBTITLE_RELAY_TEMPLATE_ID = "subtitle-relay-v1"
SUBTITLE_PROGRESS_TEMPLATE_ID = "subtitle-progress-v1"
SUBTITLE_FOREGROUND_TEMPLATE_ID = "subtitle-foreground-v1"
LAYERED_SUBTITLE_TEMPLATES = frozenset(
    {SUBTITLE_PROGRESS_TEMPLATE_ID, SUBTITLE_FOREGROUND_TEMPLATE_ID}
)
TEXT_HANDOFF_TEMPLATES = frozenset(
    {SUBTITLE_RELAY_TEMPLATE_ID, *LAYERED_SUBTITLE_TEMPLATES}
)
SYNC_SUBTITLE_TEMPLATES = frozenset(
    {
        SUBTITLE_STORY_TEMPLATE_ID,
        PRESENTER_MOTION_TEMPLATE_ID,
        AZL_TEMPLATE_ID,
        CXBR_TEMPLATE_ID,
        *UNIFIED_TEMPLATES,
        *YY_OPENING_TEMPLATES,
        *TEXT_HANDOFF_TEMPLATES,
    }
)
NUMBERED_TEMPLATE_ID = "numbered-pictures-v1"
LIVE_STRIP_TEMPLATE_ID = "live-strip-story-v1"
PACKAGE_TEMPLATES = frozenset({PACKAGE_TEMPLATE_ID, LINE_TEMPLATE_ID})
_OPENING_PURPOSES = {
    "LYO01": (
        "用原放大与暗角强调一条口播短句",
        "caption 最多 14 字，text_frame 锚定其首词。",
    ),
    "LYO02": (
        "把同期人物缩入原圆窗，显示主题词",
        "theme 最多 8 字。先绑定圆窗开始和完成的两个词点，"
        "再将 text_frame 锚定主题首词。",
    ),
    "LYO03": (
        "将主标题放在人物身后，随后显示口播说明",
        "title 最多 4 字，subtitle 最多 12 字，各自的入场事件锚定首词。"
        "主标题和说明要有足够间隔。",
    ),
    "LYO04": (
        "用原变形人物窗引出一条口播短句",
        "caption 最多 14 字，text_frame 锚定其首词。",
    ),
}
OPENING_GROUPS = frozenset(_OPENING_PURPOSES.keys() | YY_OPENING_ALL_GROUPS.keys())
_OPENING_FONT = "font-06e1a30f687ab7d3"
AUTOMATIC_TEMPLATE_DEPENDENCIES = {
    **dict.fromkeys(AZL_GROUPS, AZL_DEPENDENCIES),
    **CXBR_DEPENDENCIES,
    **FOREGROUND_SUBTITLE_DEPENDENCIES,
    YEAR_GROUP: (YEAR_FONT,),
    **dict.fromkeys(YY_OPENING_ALL_GROUPS, YY_OPENING_DEPENDENCIES),
    **dict.fromkeys(PRESENTER_MOTION_GROUPS, (MOTION_FONT,)),
    **dict.fromkeys(("YYP04", "YYP06"), (MOTION_FONT, MOTION_MATTE)),
    CARD_GROUP: (SPLIT_TITLE_FONT,),
    FRUIT_LIST_GROUP: FRUIT_LIST_FONTS,
    SLANT_GROUP: (SPLIT_TITLE_FONT, "font-baa251526d686271", FOREGROUND_MATTE),
    NUMBERED_GROUP: (SPLIT_TITLE_FONT,),
    SPLIT_VERTICAL: (SPLIT_TITLE_FONT,),
    SPLIT_HORIZONTAL: (SPLIT_TITLE_FONT, ROTATION_MATTE),
    QUESTION_GROUP: (QUESTION_FONT,),
    QUESTION_CARD_GROUP: QUESTION_CARD_A_FONTS,
    JUDGMENT_GROUP: (JUDGMENT_BRUSH_FONT,),
    LINE_GROUP: (LINE_BRUSH_FONT,),
    ROTATION_GROUP: (*FRUIT_LIST_FONTS, ROTATION_MATTE),
    "LYO01": (_OPENING_FONT,),
    "LYO02": (_OPENING_FONT, ROTATION_MATTE),
    "LYO03": (_OPENING_FONT, ROTATION_MATTE),
    "LYO04": (_OPENING_FONT,),
}
_SPECIFICATION_SLOT = {"group_id": "SG-S09", "purpose": "分别表达单件规格和到手总量"}
_SHARED_SLOTS = [
    _SPECIFICATION_SLOT,
    {"group_id": "SG-S03", "purpose": "强调真实的使用时长或体验短句"},
    {"group_id": "AH-S05", "purpose": "突出优惠条件和结论"},
    {"group_id": "JJ-S01", "purpose": "区分来源与对应说明"},
    {"group_id": "SG-S02", "purpose": "标注条款或标准的上下文"},
    {"group_id": "SG-S06", "purpose": "分两层呈现成分或功能短语"},
    {"group_id": "BG-S04", "purpose": "突出并列用途中的关键词"},
]
_FRONT_LAYER = {"group_id": "SG-S10", "purpose": "保留下单条件或行动条件"}
_ROLL_SLOTS = [
    {"group_id": "BG-S06", "purpose": "用两层滚动字幕表达报价及到手件数"},
    {"group_id": "AHG-S02", "purpose": "区分先前的实际购买经历"},
    *_SHARED_SLOTS,
]
_QUESTION_SLOT = {
    "group_id": "W-R18",
    "purpose": "实际追问可短暂整帧虚化，随后回到同期原片",
    "layer": "scene",
    "native_branch": "question",
    "binding": (
        "选择完整追问段，将 question_in 锚定该段首词。"
        "用 question 和 dissolve_in 标记实录标题和溶解词点。"
        "presenter 与 question_background 都绑定同一原片素材 ID。"
        "主字幕由网站统一生成。"
    ),
}
_ACTION_SLOT = {"group_id": "AH-S09", "purpose": "分开显示下单前提与对应行动"}
_SUBTITLE_STORY_SLOTS = {
    "AH-S02": "先定位实际口播短句，再滑入对应重点，例如已说出的报价。",
    "AH-S08": "先以实录短标题引出上下文，再滑入一条对应说明。",
    "AHG-S04": "先打出同句口播，再把句内的重点留在画面中。",
    "AHG-S05": "先写清对象或成分，再让相关结论从下方翻出。",
    "BG-S02": "左侧先出现实际短句，右侧大字补充对应说明。",
    "BG-S03": "用上下两行依次表达两项实录内容，再按原节奏错位。",
    "BG-S05": "居中缩放实录主题，在下方呈现实际说出的补充信息。",
    "JJ-S02": (
        "先写清来源或对象，再显示实际说明。让后景退定后再显示前景，"
        "retreat/1 最晚锚定 front/0 的词点。"
    ),
    "JJ-S04": "实录背景或动作先落位，再引出金色结论。",
    "JJ-S05": "让实录短主题上下分开，从中间带出对应的短结论。",
}
_SUBTITLE_RELAY_SLOTS = {
    "AH-S04": "白色实录短句先折叠展开，后续重点以原生红字落下，两行各至多六字。",
    "AHG-S01": (
        "以四字内的实录短语引出五字内的关键词。退定词点 retreat/1 最晚等于 keyword/0。"
    ),
    "JJ-S06": (
        "前后两句必须为同一语义段的实录，前句至多六字，后句至多七字。"
        "保留原生同位置淡入淡出交接。"
        "handoff/0 绑定第二句首词，handoff/1 用其附近实录边界结束交接。"
    ),
    "BG-S07": "用实录四字主题和五字补充说明做白、金双行接力。",
    "BG-S08": "四字实录标题和五字后续说明分别放入原大标题与下方读区。",
}
_SUBTITLE_PROGRESS_SLOTS = {
    "AH-S01": (
        "用两字内关键词带出八字内的实录说明。说明入场后留足展开时间，再清除画面。"
    ),
    "SG-S01": "三字主词复制分开，再接六字实录说明。两段文字各从首词进入。",
    "SG-S04": "同一实录主题拆成两个两字短语，按原动作一起进入，再由三字重点接力。",
    "SG-S07": "以实录两字引导接五字说明。两词分别按首词入场，保留原上下换位。",
    "JJ-S07": (
        "两个相邻实录短语合并再分开，中间接后续实录关键词。左四字、右三字、中七字以内。"
    ),
    "JJ-S08": "以本段首词开始四字内标题和五字内说明的原生斜排。说明首词触发换位。",
    "JJ-S09": "以本段首词开始双行第一段缩放，后句首词触发第二段。上五字、下四字以内。",
    "BG-S01": "先以白字显示四字内实录主题，后接五字内同基线说明。两句各以首词入场。",
}
_SUBTITLE_FOREGROUND_SLOTS = {
    "AH-S06": (
        "使用实录短词、实录英文字母与两个单字侧字。"
        "英文在中心词后、侧字前出现。给侧字保留完整溶落时间。"
    ),
    "SG-S05": (
        "同一八字实录短句依次轮换三款原字体，之后接五字重点。"
        "先完成轮换，再引出金字并退场。"
    ),
    "SG-S08": "两字引导退为原生背衬，五字实录重点从前方进场。",
    "BG-S09": "白色短句先起，红色重点在对应首词放大，白句同期退为背衬。",
    "BG-S10": "两个至多两字的短语先左右拼合，再以原粗书体带出实录重点。",
    "BG-S11": "白色短句收定后，原粗书体红色重点从对应首词冲入。",
}
_EXPLAINER_SLOTS = [
    {"group_id": "BG-S06", "purpose": "用两层文字交代使用场景和要解决的问题"},
    {"group_id": "SG-S03", "purpose": "让典型场景里的实录短词从说明中突出"},
    {"group_id": "AH-S05", "purpose": "从动作说明中跳出核心动作词"},
    {"group_id": "JJ-S01", "purpose": "分开呈现适用对象及其说明"},
    {"group_id": "SG-S02", "purpose": "从说明中标出选择或安排的关键词"},
    {"group_id": "SG-S06", "purpose": "分两层呈现做法和对应目标"},
    {"group_id": "BG-S04", "purpose": "左右对照两个相关的实录短词"},
    {"group_id": "AH-S09", "purpose": "分开呈现主题和补充说明"},
    {"group_id": "JJ-S03", "purpose": "突出实录给出的做法或结论"},
    {"group_id": "SG-S10", "purpose": "让背景概念承托前景行动建议"},
    {"group_id": "AHG-S02", "purpose": "标记分类或行动的实录短语"},
]
_TEMPLATES = {
    LIVE_STRIP_TEMPLATE_ID: {
        "id": LIVE_STRIP_TEMPLATE_ID,
        "name": "斜切标签与口播重点",
        "slots": [
            {
                "group_id": LIVE_STRIP_GROUP,
                "purpose": "用三道交错的原生斜切标签呈现实录中的并列短词",
                "layer": "overlay",
                "binding": (
                    "仅在 Hypit 运行已核验且原片无内嵌字幕时选择。"
                    "三个标签各取实录 1–3 个汉字，relation_items 各绑定一项文本，"
                    "三个 entry_frame 分别绑定其首词。条幅下移避开人物，"
                    "末项需留出原入场和阅读时间。同组可在不同段重复。"
                    "stagger#mkstage1 只绑定本期原片，不需要额外图片。"
                ),
            },
            *_ROLL_SLOTS,
            _ACTION_SLOT,
        ],
    },
    NUMBERED_TEMPLATE_ID: {
        "id": NUMBERED_TEMPLATE_ID,
        "name": "三项编号图与口播重点",
        "slots": [
            {
                "group_id": NUMBERED_GROUP,
                "purpose": "依次累积三个实录要点的编号、短标签和对应配图",
                "layer": "overlay",
                "binding": (
                    "只用于同一段中明确列出的三项，缺图就跳过。"
                    "每项使用一张独立的本期图片。/presenter 绑定本期原片。"
                    "items 中的 label 各取实录 1–2 字，spoken 绑定所属实录条目。"
                    "at 分别绑定 label 的首词。原生卡片需要时间入场，"
                    "末项结束后在同一片段保留可读时间。"
                    "relation_items 每项绑定 label、spoken 和对应的 image。"
                ),
            },
            *_EXPLAINER_SLOTS,
        ],
    },
    EXPLAINER_TEMPLATE_ID: {
        "id": EXPLAINER_TEMPLATE_ID,
        "name": "讲解步骤与口播重点",
        "slots": _EXPLAINER_SLOTS,
    },
    "label-compare-v1": {
        "id": "label-compare-v1",
        "name": "价签与规格对照",
        "slots": [
            {"group_id": "AHG-S02", "purpose": "标注本期真实口播里的报价"},
            {"group_id": "JJ-S03", "purpose": "标出价格或关键结论"},
            {"group_id": "AH-S09", "purpose": "分开呈现主张和补充信息"},
            *_SHARED_SLOTS,
            _FRONT_LAYER,
        ],
    },
    "roll-compare-v1": {
        "id": "roll-compare-v1",
        "name": "滚动报价与规格对照",
        "slots": [*_ROLL_SLOTS, _FRONT_LAYER],
    },
    "question-story-v1": {
        "id": "question-story-v1",
        "name": "整帧追问与口播重点",
        "slots": [_QUESTION_SLOT, *_ROLL_SLOTS, _ACTION_SLOT],
    },
    QUESTION_CARD_TEMPLATE_ID: {
        "id": QUESTION_CARD_TEMPLATE_ID,
        "name": "透明问号与口播重点",
        "slots": [
            {
                "group_id": QUESTION_CARD_GROUP,
                "native_branch": "input-A",
                "purpose": "用原版左右短语和中央问号标记实录追问，保留同期人物",
                "layer": "overlay",
                "binding": (
                    "仅用于实际追问。/content/left 与 /content/right 各 1–2 字，"
                    "必须是实录中相邻的两段词。question_gloss 只译这两个短语，"
                    "用不超过 24 字符的简短大写英文。"
                    "chinese_frame 和 question_frame 分别绑定左右短语首词起点，"
                    "english_frame 绑定两处之间实录词的起点。"
                    "exit_frame 与 clear_frame 按序绑定后续词的边界，"
                    "给问号完成放大和淡出留时间。英文和问号图形无需 native_text。"
                    "无法匹配时选择其他语义合适的槽或留白。"
                ),
            },
            *_ROLL_SLOTS,
            _ACTION_SLOT,
        ],
    },
    "roll-compare-v2": {
        "id": "roll-compare-v2",
        "name": "滚动报价与规格对照",
        "slots": [*_ROLL_SLOTS, _ACTION_SLOT],
    },
    PACKAGE_TEMPLATE_ID: {
        "id": PACKAGE_TEMPLATE_ID,
        "name": "纸面规格与口播重点",
        "slots": [
            {
                "group_id": PACKAGE_GROUP,
                "purpose": "用原纸面布局逐项说明四个实录要点，圆窗保留同期人物",
                "layer": "scene",
                "binding": (
                    "只在口播有四项相连的规格或商品说明且各有对应项目图片时选择。"
                    "presenter 绑定本期原片，四项标签保留实录数字和单位。"
                    "每项使用一张不同图片，relation_items 按出场顺序绑定标签和图片，"
                    "item0 至 item3 分别锚定其标签的首词。"
                    "第四项之后留出阅读时间。可选补充字由主字幕承载。"
                    "缺图或没有合适的四项时跳过该槽。"
                ),
            },
            _QUESTION_SLOT,
            *_ROLL_SLOTS,
            _ACTION_SLOT,
        ],
    },
    JUDGMENT_TEMPLATE_ID: {
        "id": JUDGMENT_TEMPLATE_ID,
        "name": "证据判断与口播重点",
        "slots": [
            {
                "group_id": JUDGMENT_GROUP,
                "purpose": "按实录用两份本期图片对照依据和反例，再显示竖排结论",
                "layer": "scene",
                "binding": (
                    "仅用于口播明确比较的两个对象和后续判断。"
                    "background 用本期原片。按原生上下两行的出画顺序，"
                    "第一个标签 left_label 对应右上透明图 person_right 和勾，"
                    "第二个标签 right_label 对应左下图 evidence_left 和叉。"
                    "relation_items 按该顺序分别绑定实录标签和对应图片。"
                    "按原序绑定两次素材入场、勾、叉、结论和退场的词点。"
                    "结论入场从实际结论首词起，主字幕由网站统一绘制。"
                ),
            },
            *_ROLL_SLOTS,
            _ACTION_SLOT,
        ],
    },
    PRESENTER_TEMPLATE_ID: {
        "id": PRESENTER_TEMPLATE_ID,
        "name": "人物开场与口播重点",
        "slots": [
            *(
                {
                    "group_id": group,
                    "purpose": purpose,
                    "layer": "scene",
                    "binding": (
                        "用本期原片绑定 /media/presenter/path，"
                        "人物和声音继续按原时钟播放。"
                        + instructions
                        + "文本入场后保留实录阅读区间。"
                    ),
                }
                for group, (purpose, instructions) in _OPENING_PURPOSES.items()
            ),
            *_ROLL_SLOTS,
            _ACTION_SLOT,
        ],
    },
    ROTATION_TEMPLATE_ID: {
        "id": ROTATION_TEMPLATE_ID,
        "name": "三图轮换与口播重点",
        "slots": [
            {
                "group_id": ROTATION_GROUP,
                "purpose": "保留同期人物，围绕三个并列事项逐张轮换图卡焦点",
                "layer": "scene",
                "binding": (
                    "仅在有三个并列事项及三张对应项目图时使用。"
                    "presenter 使用本期原片 source 素材，原生暖色背景固定。"
                    "首项首词开始该段，三项各用短标签和自己的首词锚定 at。"
                    "relation_items 按顺序绑定各项标签和图片，不共用素材。"
                    "在第三项之后给切换留出实录阅读区间。"
                ),
            },
            _QUESTION_SLOT,
            *_ROLL_SLOTS,
            _ACTION_SLOT,
        ],
    },
    LEGACY_PICTURE_TEMPLATE_ID: {
        "id": LEGACY_PICTURE_TEMPLATE_ID,
        "name": "三图卡与口播重点",
        "slots": [
            {
                "group_id": "CX-G07",
                "purpose": "在整帧画面依次展示与口播对应的三张项目图片",
                "layer": "scene",
                "binding": (
                    "只在本段有三个并列项目和对应图片时使用。"
                    "background 绑定已选背景图，三个 cards 各用不同图片。"
                    "同一卡的 food 和 city 槽绑定相同的实录标签和图片。"
                    "前三个动作锚定各卡标签首词，最后一项落稳使用后续实录词点。"
                    "relation_items 逐卡列出两套槽对应的词范围和素材。"
                ),
            },
            _QUESTION_SLOT,
            *_ROLL_SLOTS,
            _ACTION_SLOT,
        ],
    },
}

_TEMPLATES[SUBTITLE_STORY_TEMPLATE_ID] = {
    "id": SUBTITLE_STORY_TEMPLATE_ID,
    "name": "原生字效叙事",
    "slots": [
        {"group_id": group, "purpose": purpose}
        for group, purpose in _SUBTITLE_STORY_SLOTS.items()
    ]
    + [_SPECIFICATION_SLOT, *_EXPLAINER_SLOTS],
}
for _template_id, _opening_groups in (
    (YY_OPENING_TEMPLATE_ID, YY_OPENING_GROUPS),
    (YY_OPENING_EXPANDED_TEMPLATE_ID, YY_OPENING_EXPANDED_GROUPS),
    (YY_OPENING_ALL_TEMPLATE_ID, YY_OPENING_ALL_GROUPS),
):
    _TEMPLATES[_template_id] = {
        "id": _template_id,
        "name": "月云川人物开场",
        "slots": [
            *(
                {
                    "group_id": group,
                    "purpose": purpose,
                    "layer": "scene",
                    "binding": yy6_binding(group)
                    if group in YY6_GROUPS
                    else yy_opening_binding(group),
                }
                for group, purpose in _opening_groups.items()
            ),
            *_TEMPLATES[SUBTITLE_STORY_TEMPLATE_ID]["slots"],
        ],
    }
_TEMPLATES[PRESENTER_MOTION_TEMPLATE_ID] = {
    "id": PRESENTER_MOTION_TEMPLATE_ID,
    "name": "同期人物运镜与分区",
    "slots": [
        *(
            {
                "group_id": group,
                "purpose": purpose,
                "layer": "scene",
                "binding": motion_binding(group),
            }
            for group, (purpose, _, _) in PRESENTER_MOTION_GROUPS.items()
        ),
        *_TEMPLATES[SUBTITLE_STORY_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[AZL_TEMPLATE_ID] = {
    "id": AZL_TEMPLATE_ID,
    "name": "阿哲多素材板式",
    "slots": [
        *(
            {
                "group_id": group,
                "purpose": purpose,
                "layer": "scene",
                "binding": azl_binding(group),
            }
            for group, (purpose, _) in AZL_GROUPS.items()
        ),
        *_TEMPLATES[SUBTITLE_STORY_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[CXBR_TEMPLATE_ID] = {
    "id": CXBR_TEMPLATE_ID,
    "name": "晨曦双路实景",
    "slots": [
        *(
            {
                "group_id": group,
                "purpose": purpose,
                "layer": "scene",
                "binding": cxbr_binding(group),
            }
            for group, purpose in CXBR_PURPOSES.items()
        ),
        *_TEMPLATES[SUBTITLE_STORY_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[UNIFIED_TEMPLATE_ID] = {
    "id": UNIFIED_TEMPLATE_ID,
    "name": "论点与数量对照",
    "slots": [
        *(
            {
                "group_id": group,
                "purpose": purpose,
                "layer": "scene",
                "binding": unified_binding(group),
            }
            for group, (purpose, _) in UNIFIED_GROUPS.items()
        ),
        *_TEMPLATES[SUBTITLE_STORY_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[UNIFIED_EXPANDED_TEMPLATE_ID] = {
    "id": UNIFIED_EXPANDED_TEMPLATE_ID,
    "name": "论点、数量与年份",
    "slots": [
        *(
            {
                "group_id": group,
                "purpose": purpose,
                "layer": "scene",
                "binding": unified_binding(group),
            }
            for group, (purpose, _) in UNIFIED_EXPANDED_GROUPS.items()
        ),
        {
            "group_id": YEAR_GROUP,
            "purpose": "用实录年份引出实际说出的事件，保持原生前后字和背衬。",
            "binding": YEAR_BINDING,
        },
        *_TEMPLATES[UNIFIED_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[UNIFIED_EXPLANATION_TEMPLATE_ID] = {
    "id": UNIFIED_EXPLANATION_TEMPLATE_ID,
    "name": "资料说明与口播问答",
    "slots": [
        *(
            {
                "group_id": group,
                "purpose": purpose,
                "layer": "scene",
                "binding": unified_binding(group),
            }
            for group, (purpose, _) in UNIFIED_EXPLANATION_GROUPS.items()
        ),
        *_TEMPLATES[UNIFIED_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[HANDOFF_TEMPLATE_ID] = {
    "id": HANDOFF_TEMPLATE_ID,
    "name": "转场与评论引导",
    "slots": [
        *(
            {
                "group_id": group,
                "purpose": purpose,
                "layer": "scene",
                "binding": binding,
            }
            for group, (purpose, binding) in HANDOFF_GROUPS.items()
        ),
        *_TEMPLATES[UNIFIED_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[LIVE_SPLIT_TEMPLATE_ID] = {
    "id": LIVE_SPLIT_TEMPLATE_ID,
    "name": "竖横分屏与同期人物",
    "slots": [
        *(
            {
                "group_id": group,
                "purpose": "用原生竖向分屏和人物方窗依次显示三项。"
                if group == SPLIT_VERTICAL
                else "用原生横向分屏和右下人物轮廓依次显示三项。",
                "layer": "scene",
                "binding": "同期原片绑定 /presenter。"
                "三个 spoken、label、image 各自绑定同一实录条目。"
                "at 取各 label 的实际首词。末项要留足原入场时间。"
                + (
                    "intro 绑定第一项前已说出的短标题。"
                    "需至少 0.3 秒入场前区间，中文片的英文槽留空。"
                    if group == SPLIT_VERTICAL
                    else "横向 label 最多两字，完整短语绑定 spoken 并由主字幕承载。"
                ),
            }
            for group in LIVE_SPLIT_GROUPS
        ),
        *_TEMPLATES[UNIFIED_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[FRUIT_LIST_TEMPLATE_ID] = {
    "id": FRUIT_LIST_TEMPLATE_ID,
    "name": "水果介绍与图文清单",
    "slots": [
        {
            "group_id": FRUIT_LIST_GROUP,
            "purpose": "用原生「水果介绍」圆形头图及三条图文说明展示实录。",
            "layer": "scene",
            "binding": "第一项之前须在本段说出水果主题。"
            "三种水果各绑定一至三字名称、一至十二字说明及不同的项目图。"
            "at 取各水果名称首词，三个 relation_items 按实录顺序绑定对应行。"
            "另选一张至少 1006×814 的水果头图绑定 /presenter。该槽用于头图。",
        },
        *_TEMPLATES[UNIFIED_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[HY_PICTURE_TEMPLATE_ID] = {
    "id": HY_PICTURE_TEMPLATE_ID,
    "name": "同期人物与原生三图卡",
    "slots": [
        {
            "group_id": SLANT_GROUP,
            "purpose": "使用原生斜卡和独立底图呈现三项内容，人物沿用原片尺寸和位置。",
            "layer": "scene",
            "binding": "绑定三张独立配图和一张本期背景图。前景绑定同期原片。"
            "三条中文标题各取一至三字实录，在各自首词触发。原可选英文留空。"
            "每项绑定对应的原生标题、图片和实录范围。",
        },
        {
            "group_id": PICTURE_GROUP,
            "purpose": "三张图片依次落入原生图槽，同期人物与背景同时播放。",
            "layer": "scene",
            "binding": "原片同时绑定 /background/path 与 /presenter/path。"
            "三张独立项目图片按实录条目依次绑定 /items/{i}/path，"
            "entry_frame 各取对应项首词。完整口播由主字幕显示。",
        },
        *_TEMPLATES[UNIFIED_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[DETAIL_CARDS_TEMPLATE_ID] = {
    "id": DETAIL_CARDS_TEMPLATE_ID,
    "name": "三项说明与同期口播",
    "slots": [
        {
            "group_id": PRICE_CARD_GROUP,
            "purpose": "用三个原生双行图卡显示本段对应的三项说明，保留同期人物。",
            "layer": "scene",
            "binding": "各项依次绑定本期独立图片及实际说出的标题和说明。"
            "标题与说明各取一至六字，先说标题，说明首词触发图卡。"
            "从早到晚绑定 mka6c3、mka6c2、mka6c1，底板 mkstage1 使用同期原片。"
            "图卡右侧留浅色空白给原生黑字，完整原话由主字幕显示。",
        },
        *_TEMPLATES[UNIFIED_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[CUT_TEMPLATE_ID] = {
    "id": CUT_TEMPLATE_ID,
    "name": "实拍与项目素材接力",
    "slots": [
        *(
            {
                "group_id": group,
                "purpose": purpose,
                "layer": "scene",
                "binding": binding + " 每个 cuts 用对应实录首词，"
                "relation_items 按同序绑定各词段、素材 ID 及唯一原媒体槽。"
                "缺少对应图时跳过。",
            }
            for group, (purpose, binding) in CUT_GROUPS.items()
        ),
        *_TEMPLATES[SUBTITLE_STORY_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[PANEL_TEMPLATE_ID] = {
    "id": PANEL_TEMPLATE_ID,
    "name": "人物与图例并置",
    "slots": [
        *(
            {
                "group_id": group,
                "purpose": purpose,
                "layer": "scene",
                "binding": binding
                + " 用 relation_items 按实录顺序绑定各项和对应媒体槽。",
            }
            for group, (purpose, binding) in PANEL_GROUPS.items()
        ),
        *_TEMPLATES[CUT_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[SUBTITLE_RELAY_TEMPLATE_ID] = {
    "id": SUBTITLE_RELAY_TEMPLATE_ID,
    "name": "双层字幕接力",
    "slots": [
        *(
            {"group_id": group, "purpose": purpose}
            for group, purpose in _SUBTITLE_RELAY_SLOTS.items()
        ),
        *_TEMPLATES[SUBTITLE_STORY_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[SUBTITLE_PROGRESS_TEMPLATE_ID] = {
    "id": SUBTITLE_PROGRESS_TEMPLATE_ID,
    "name": "关键词递进",
    "slots": [
        *(
            {"group_id": group, "purpose": purpose}
            for group, purpose in _SUBTITLE_PROGRESS_SLOTS.items()
        ),
        *_TEMPLATES[SUBTITLE_RELAY_TEMPLATE_ID]["slots"],
    ],
}
_TEMPLATES[SUBTITLE_FOREGROUND_TEMPLATE_ID] = {
    "id": SUBTITLE_FOREGROUND_TEMPLATE_ID,
    "name": "原字形前景重点",
    "slots": [
        *(
            {"group_id": group, "purpose": purpose}
            for group, purpose in _SUBTITLE_FOREGROUND_SLOTS.items()
        ),
        *_TEMPLATES[SUBTITLE_PROGRESS_TEMPLATE_ID]["slots"],
    ],
}

_TEMPLATES[PICTURE_TEMPLATE_ID] = {
    "id": PICTURE_TEMPLATE_ID,
    "name": "三图卡与口播重点",
    "slots": [
        {
            "group_id": "CX-G07",
            "purpose": "保持同期人物口播，依次叠加对应三个并列事项的图卡",
            "layer": "overlay",
            "binding": (
                "background 绑定本期原片 source 素材，人物随同期画面继续口播。"
                "每张卡使用一张与标签内容对应的本期项目图片。"
                "素材描述应支持这一对应关系，通用人物头像不能代替场景图。"
                "没有合适的三张图片时跳过该槽。"
                "同一卡的 food 和 city 槽绑定相同的实录标签和图片。"
                "前三个动作锚定各卡标签首词，最后一项落稳使用后续实录词点。"
                "relation_items 逐卡列出两套槽对应的词范围和素材。"
            ),
        },
        _QUESTION_SLOT,
        *_ROLL_SLOTS,
        _ACTION_SLOT,
    ],
}

_TEMPLATES[LINE_TEMPLATE_ID] = {
    "id": LINE_TEMPLATE_ID,
    "name": "线描经历与纸面规格",
    "slots": [
        {
            "group_id": LINE_GROUP,
            "purpose": "用本期线描回顾一段实录经历，再按原动效回切同期人物",
            "layer": "scene",
            "binding": (
                "选择口播中一段具体经历。presenter 绑定本期原片。"
                "previous、director_ink、hand_sequence 分别绑定不透明过渡图、"
                "透明线描和六列四行的透明手势帧图。三份原件须不同。"
                "director_label、hand_label 和 paper_text 使用实际短词。"
                "依次绑定 previous_out、hand_in、label_in 和四个 portrait_scale_keys。"
                "hand_in 从纸面短语首词开始，label_in 从手势标签首词开始，"
                "四个回切点完成后给同期人物留出可见区间。由网站统一绘制主字幕。"
                "缺少任一素材或合适的实录词点时跳过此场景。"
            ),
        },
        *_TEMPLATES[PACKAGE_TEMPLATE_ID]["slots"],
    ],
}


def overlay_templates() -> list[dict]:
    return [
        overlay_template(key)
        for key in (
            "label-compare-v1",
            "roll-compare-v2",
            "question-story-v1",
            QUESTION_CARD_TEMPLATE_ID,
            PICTURE_TEMPLATE_ID,
            ROTATION_TEMPLATE_ID,
            NUMBERED_TEMPLATE_ID,
            LIVE_STRIP_TEMPLATE_ID,
            PACKAGE_TEMPLATE_ID,
            LINE_TEMPLATE_ID,
            PRESENTER_TEMPLATE_ID,
            YY_OPENING_ALL_TEMPLATE_ID,
            PRESENTER_MOTION_TEMPLATE_ID,
            AZL_TEMPLATE_ID,
            CXBR_TEMPLATE_ID,
            UNIFIED_EXPANDED_TEMPLATE_ID,
            UNIFIED_EXPLANATION_TEMPLATE_ID,
            HANDOFF_TEMPLATE_ID,
            LIVE_SPLIT_TEMPLATE_ID,
            HY_PICTURE_TEMPLATE_ID,
            DETAIL_CARDS_TEMPLATE_ID,
            CUT_TEMPLATE_ID,
            PANEL_TEMPLATE_ID,
            JUDGMENT_TEMPLATE_ID,
            EXPLAINER_TEMPLATE_ID,
            SUBTITLE_STORY_TEMPLATE_ID,
            SUBTITLE_RELAY_TEMPLATE_ID,
            SUBTITLE_PROGRESS_TEMPLATE_ID,
            SUBTITLE_FOREGROUND_TEMPLATE_ID,
        )
    ]


def overlay_template(template_id: str) -> dict:
    if template_id not in _TEMPLATES:
        raise ValueError("Unknown original overlay composition template")
    return deepcopy(_TEMPLATES[template_id])


def validate_template_plan(
    plan: SemanticPlan, template: dict, *, complete: bool
) -> None:
    if template != overlay_template(template["id"]):
        raise ValueError("Overlay template version or slots changed")
    allow_question_gloss = template["id"] == QUESTION_CARD_TEMPLATE_ID
    if any(
        (beat.question_gloss is not None)
        != (allow_question_gloss and beat.group_id == QUESTION_CARD_GROUP)
        for beat in plan.beats
    ):
        raise ValueError("English question gloss must match the selected AH-S03 A slot")
    groups = {slot["group_id"] for slot in template["slots"]}
    chosen = {beat.group_id for beat in plan.beats if beat.group_id != "Z-M00"}
    if not chosen <= groups or (complete and len(chosen) < MIN_OVERLAY_TYPES):
        raise ValueError(
            "Selected native groups do not match the chosen overlay template"
        )
