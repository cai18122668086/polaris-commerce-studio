"""系统声音的显示名（一处维护，前端只显示接口返回的名字）。

供应商目录里的名字（「霸道青年音色」「病娇弟弟」「…-beta」）直接照抄不像正经商业网站，
这里按「性别/年龄感 + 声音特质 + 适用场景」给出显示名和一句用途说明。

规则：
- 只改显示，不改 voice_id；生成任务里写给供应商的仍是原始 voice_id / voice_name。
- 角色化、卡通、儿童、恋爱向、负面情绪的声音，以及与正式版重复的 beta 版，
  不在系统声音列表里展示；已被固定形象、作品条目或历史任务引用的照常可用
  （由调用方通过 ``include`` 放回列表，显示供应商原名）。
- 中文普通话 / 粤语逐条人工核对；其他语言统一为「语言 + 性别 + 特质」。
- 全语种的公共音色（qy-voice-*）由上游实时返回，按 id 映射，并核对上游原名，
  原名对不上时退回到清洗后的原名，避免上游换序后张冠李戴。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# 显示名里不允许出现的词（pytest 检查）。
BANNED_WORDS = (
    "病娇",
    "男友",
    "女友",
    "霸道",
    "御姐",
    "卡通",
    "猪",
    "beta",
    "音色",
    "妩媚",
    "嗲",
    "萌妹",
    "萌兽",
    "少爷",
    "小姐",
    "竹马",
    "学弟",
    "学妹",
    "学长",
    "学姐",
    "弟弟",
    "男童",
    "女童",
    "傲娇",
    "嚣张",
    "战甲",
    "搞笑",
    "大婶",
    "大爷",
    "空姐",
    "闺蜜",
)

# voice_id -> (性别, 显示名, 用途说明)。中文普通话 / 粤语，逐条人工核对。
CHINESE: dict[str, tuple[str, str, str]] = {
    "male-qn-qingse": (
        "男",
        "清爽男声 · 学生好物",
        "年轻干净，适合文具、数码配件、平价好物推荐。",
    ),
    "male-qn-jingying": (
        "男",
        "干练男声 · 数码科技",
        "语速利落、咬字清楚，适合数码、家电参数讲解。",
    ),
    "male-qn-badao": (
        "男",
        "磁性男声 · 品质推荐",
        "低沉有力、气场足，适合男士护理、酒水、汽车用品。",
    ),
    "male-qn-daxuesheng": (
        "男",
        "阳光男声 · 校园生活",
        "轻快自然，适合运动、零食、校园日用。",
    ),
    "female-shaonv": (
        "女",
        "元气女声 · 潮流好物",
        "明亮有活力，适合饰品、潮玩、新品种草。",
    ),
    "female-yujie": (
        "女",
        "干练女声 · 时尚美妆",
        "成熟利落，适合彩妆、服饰、轻奢单品。",
    ),
    "female-chengshu": (
        "女",
        "成熟女声 · 品质生活",
        "从容稳重，适合家居、厨电、高客单商品。",
    ),
    "female-tianmei": ("女", "甜美女声 · 美妆个护", "温柔甜润，适合护肤、个护、香氛。"),
    "danya_xuejie": ("女", "淡雅女声 · 文艺生活", "安静清淡，适合茶饮、书籍、手作。"),
    "Chinese (Mandarin)_Reliable_Executive": (
        "男",
        "沉稳男声 · 商务讲解",
        "沉着可信，适合企业服务、理财、商务产品介绍。",
    ),
    "Chinese (Mandarin)_News_Anchor": (
        "女",
        "播报女声 · 资讯讲解",
        "标准播音腔，适合活动公告、行业资讯。",
    ),
    "Chinese (Mandarin)_Mature_Woman": (
        "女",
        "知性女声 · 产品介绍",
        "清晰有条理，适合产品功能、成分讲解。",
    ),
    "Chinese (Mandarin)_Unrestrained_Young_Man": (
        "男",
        "潮流男声 · 运动户外",
        "随性有张力，适合运动、户外、潮牌。",
    ),
    "Chinese (Mandarin)_Kind-hearted_Antie": (
        "女",
        "热情中年女声 · 家居日用",
        "热心接地气，适合清洁、厨房、家居日用。",
    ),
    "Chinese (Mandarin)_HK_Flight_Attendant": (
        "女",
        "港普女声 · 旅行出行",
        "带港式口音、亲切礼貌，适合旅行、出行、跨境好物。",
    ),
    "Chinese (Mandarin)_Gentleman": (
        "男",
        "温润男声 · 品质讲解",
        "温和有修养，适合茶叶、家居、高端礼品。",
    ),
    "Chinese (Mandarin)_Warm_Bestie": (
        "女",
        "亲切女声 · 生活分享",
        "像朋友聊天，适合日常好物、使用心得。",
    ),
    "Chinese (Mandarin)_Male_Announcer": (
        "男",
        "播报男声 · 新品发布",
        "字正腔圆，适合新品发布、门店活动。",
    ),
    "Chinese (Mandarin)_Sweet_Lady": (
        "女",
        "柔美女声 · 服饰穿搭",
        "柔和细腻，适合女装、内衣、穿搭分享。",
    ),
    "Chinese (Mandarin)_Southern_Young_Man": (
        "男",
        "南方男声 · 美食特产",
        "带南方口音、亲和朴实，适合美食、地方特产。",
    ),
    "Chinese (Mandarin)_Wise_Women": (
        "女",
        "从容女声 · 母婴家庭",
        "温和有阅历，适合母婴、家庭健康、教育。",
    ),
    "Chinese (Mandarin)_Gentle_Youth": (
        "男",
        "温和男声 · 好物分享",
        "舒缓耐听，适合家居、生活方式类分享。",
    ),
    "Chinese (Mandarin)_Warm_Girl": (
        "女",
        "温暖女声 · 日常种草",
        "温柔亲近，适合日用、宠物、家居小物。",
    ),
    "Chinese (Mandarin)_Kind-hearted_Elder": (
        "女",
        "慈和长者女声 · 健康养生",
        "慢而慈祥，适合养生、滋补、银发用品。",
    ),
    "Chinese (Mandarin)_Radio_Host": (
        "男",
        "电台男声 · 故事讲述",
        "低沉舒缓，适合品牌故事、长文案。",
    ),
    "Chinese (Mandarin)_Lyrical_Voice": (
        "男",
        "抒情男声 · 品牌故事",
        "富有感染力，适合品牌宣传片、节日营销。",
    ),
    "Chinese (Mandarin)_Straightforward_Boy": (
        "男",
        "直爽少年男声 · 开箱测评",
        "直接有劲，适合开箱、测评、对比。",
    ),
    "Chinese (Mandarin)_Sincere_Adult": (
        "男",
        "真诚男声 · 口碑推荐",
        "诚恳可信，适合口碑推荐、售后说明。",
    ),
    "Chinese (Mandarin)_Gentle_Senior": (
        "女",
        "温柔女声 · 知识讲解",
        "耐心细致，适合知识科普、使用教程。",
    ),
    "Chinese (Mandarin)_Crisp_Girl": (
        "女",
        "清脆女声 · 零食饮品",
        "清亮爽快，适合零食、饮品、快消品。",
    ),
    "Chinese (Mandarin)_Soft_Girl": (
        "女",
        "柔和女声 · 家居香氛",
        "轻柔安静，适合香氛、床品、助眠类商品。",
    ),
    "Cantonese_ProfessionalHost（F)": (
        "女",
        "粤语女声 · 专业主持",
        "标准粤语主持腔，适合粤港澳市场的活动与新品介绍。",
    ),
    "Cantonese_GentleLady": (
        "女",
        "粤语女声 · 温柔",
        "温柔亲切，适合粤语生活好物分享。",
    ),
    "Cantonese_ProfessionalHost（M)": (
        "男",
        "粤语男声 · 专业主持",
        "稳重清晰，适合粤语商务与产品讲解。",
    ),
    "Cantonese_PlayfulMan": ("男", "粤语男声 · 活泼", "轻松有趣，适合粤语美食、探店。"),
    "Cantonese_KindWoman": (
        "女",
        "粤语女声 · 亲和",
        "亲和耐心，适合粤语家庭日用推荐。",
    ),
}

# 中文声音里不展示的：beta 重复、儿童、卡通、角色化、恋爱向。
HIDDEN_CHINESE: dict[str, str] = {
    **{
        f"{base}-jingpin": "与正式版重复的 beta 版"
        for base in [
            "male-qn-qingse",
            "male-qn-jingying",
            "male-qn-badao",
            "male-qn-daxuesheng",
            "female-shaonv",
            "female-yujie",
            "female-chengshu",
            "female-tianmei",
        ]
    },
    "clever_boy": "儿童",
    "cute_boy": "儿童",
    "lovely_girl": "儿童",
    "cartoon_pig": "卡通",
    "Chinese (Mandarin)_Cute_Spirit": "卡通",
    "Robot_Armor": "角色化",
    "bingjiao_didi": "角色化",
    "badao_shaoye": "角色化",
    "Arrogant_Miss": "角色化",
    "wumei_yujie": "角色化",
    "qiaopi_mengmei": "角色化",
    "diadia_xuemei": "角色化",
    "tianxin_xiaoling": "角色化",
    "chunzhen_xuedi": "角色化",
    "lengdan_xiongzhang": "角色化",
    "Chinese (Mandarin)_Humorous_Elder": "角色化",
    "Chinese (Mandarin)_Pure-hearted_Boy": "角色化",
    "junlang_nanyou": "恋爱向",
    "Chinese (Mandarin)_Stubborn_Friend": "恋爱向",
    "Cantonese_CuteGirl": "儿童",
}

# 口播用的公共音色（上游 /api/tts/preset-voices）：id -> (上游原名, 性别, 显示名, 用途)
QUANYU: dict[str, tuple[str, str, str, str]] = {
    "1": (
        "温柔女声",
        "女",
        "温柔女声 · 居家好物",
        "温和舒缓，适合家居、母婴、日用推荐。",
    ),
    "2": (
        "新闻女声",
        "女",
        "资讯女声 · 新闻播报",
        "正式清晰，适合资讯、公告、活动通知。",
    ),
    "3": (
        "抒情女声",
        "女",
        "抒情女声 · 品牌故事",
        "细腻有感染力，适合品牌故事、节日营销。",
    ),
    "4": (
        "青涩男声",
        "男",
        "青年男声 · 清新推荐",
        "年轻自然，适合学生、运动、平价好物。",
    ),
    "5": (
        "精英男声",
        "男",
        "精英男声 · 职场效率",
        "利落专业，适合办公、数码、效率工具。",
    ),
    "6": (
        "少女女声",
        "女",
        "青春女声 · 活力种草",
        "明快有朝气，适合美妆、饰品、零食种草。",
    ),
}

LANGUAGE_LABELS = {
    "英文": "英语",
    "日文": "日语",
    "韩文": "韩语",
    "西班牙文": "西班牙语",
    "葡萄牙文": "葡萄牙语",
    "法文": "法语",
    "印尼文": "印尼语",
    "德文": "德语",
    "俄文": "俄语",
    "意大利文": "意大利语",
    "阿拉伯文": "阿拉伯语",
    "土耳其文": "土耳其语",
    "乌克兰文": "乌克兰语",
    "荷兰文": "荷兰语",
    "越南文": "越南语",
    "泰文": "泰语",
    "波兰文": "波兰语",
    "罗马尼亚文": "罗马尼亚语",
    "希腊文": "希腊语",
    "捷克文": "捷克语",
    "芬兰文": "芬兰语",
    "印地文": "印地语",
    "中文 (粤语)": "粤语",
    "中文 (普通话)": "普通话",
}

# 其他语言：英文原名（小写）-> (性别, 特质)；None = 角色化/恋爱向/负面情绪，不展示。
# 性别为 "" 时按 voice_id 里的 male/female 判断，判断不了显示「人声」。
FOREIGN: dict[str, tuple[str, str] | None] = {
    "ambitious woman": ("女", "进取"),
    "assetive woman": ("女", "果断"),
    "assured presenter": ("男", "从容主持"),
    "athletic girl": ("女", "运动活力"),
    "athletic student": ("男", "运动活力"),
    "aussie bloke": ("男", "澳洲口音"),
    "bossy leader": ("", "强势干练"),
    "calm gentleman": ("男", "沉着"),
    "calm lady": ("女", "平静"),
    "calm leader": ("男", "沉稳领导"),
    "calm woman": ("女", "沉静"),
    "captivating storyteller": ("", "故事讲述"),
    "caring man": ("男", "体贴"),
    "caring woman": ("女", "体贴"),
    "casual man": ("男", "随和"),
    "casual woman": ("女", "随和"),
    "charming girl": ("女", "亲和"),
    "charming lady": ("女", "优雅亲和"),
    "chatty girl": ("女", "健谈"),
    "cheerful cool junior": ("男", "开朗"),
    "comedian": ("男", "幽默"),
    "compelling girl": ("女", "有说服力"),
    "confident boss": ("男", "自信"),
    "confident woman": ("女", "自信"),
    "conscientious instructor": ("", "认真讲解"),
    "considerate senior": ("男", "周到稳重"),
    "debator": ("男", "思辨"),
    "deep-toned man": ("男", "低沉"),
    "deep-voiced gentleman": ("男", "浑厚"),
    "dependable woman": ("女", "可靠"),
    "determined boy": ("男", "坚定"),
    "determined manager": ("", "果决"),
    "diligent leader": ("男", "勤勉"),
    "diligent man": ("男", "踏实"),
    "elegant girl": ("女", "清雅"),
    "elegant lady": ("女", "优雅"),
    "energetic boy": ("男", "活力"),
    "energetic woman": ("女", "活力"),
    "energetic youth": ("男", "青春活力"),
    "enthusiastic teen": ("男", "热情"),
    "female anchor": ("女", "主播"),
    "frank lady": ("女", "直率"),
    "friendly big sister": ("女", "亲切"),
    "friendly boy": ("男", "友善"),
    "friendly guy": ("男", "友善"),
    "friendly man": ("男", "友善"),
    "friendly neighbor": ("", "邻家亲切"),
    "gentle boss": ("男", "温和稳重"),
    "gentle girl": ("女", "温柔"),
    "gentle lady": ("女", "温婉"),
    "gentle teacher": ("", "耐心讲解"),
    "gentle woman": ("女", "温和"),
    "gentle-voiced man": ("男", "温和"),
    "girl next door": ("女", "邻家亲切"),
    "gorgeous lady": ("女", "华丽"),
    "graceful lady": ("女", "端庄"),
    "graceful maiden": ("女", "清秀"),
    "humorous elder": ("男", "风趣长者"),
    "innocent boy": ("男", "清澈"),
    "inspiring lady": ("女", "鼓舞"),
    "intellectual man": ("男", "知性"),
    "intellectual senior": ("", "知性长者"),
    "intonate girl": ("女", "抑扬顿挫"),
    "jovial man": ("男", "爽朗"),
    "kind lady": ("女", "和善"),
    "kind-hearted girl": ("女", "善良"),
    "level-headed man": ("男", "冷静"),
    "lovely lady": ("女", "可亲"),
    "male anchor": ("男", "主播"),
    "male narrator": ("男", "旁白"),
    "mature lady": ("女", "成熟"),
    "narrator": ("", "旁白"),
    "news anchor": ("", "新闻播报"),
    "optimistic youth": ("", "乐观"),
    "patient female presenter": ("女", "耐心主持"),
    "playful girl": ("女", "俏皮"),
    "playful man": ("男", "轻松"),
    "powerful veteran": ("男", "老练"),
    "rational man": ("男", "理性"),
    "reliable man": ("男", "可靠"),
    "reliable sister": ("女", "可靠"),
    "reliable youth": ("男", "可靠青年"),
    "reserved young man": ("男", "内敛"),
    "sensible manager": ("", "务实"),
    "sentimental lady": ("女", "感性"),
    "serene elder": ("", "安详长者"),
    "serene man": ("男", "安详"),
    "serene woman": ("女", "恬静"),
    "sincere teen": ("男", "真诚"),
    "smart young girl": ("女", "聪慧"),
    "soothing lady": ("女", "舒缓"),
    "sophisticated lady": ("女", "成熟干练"),
    "sporty student": ("男", "运动"),
    "steadfast narrator": ("女", "稳定旁白"),
    "steady mentor": ("男", "稳重导师"),
    "strict boss": ("", "严谨"),
    "strong-willed boy": ("男", "坚毅"),
    "sweet girl": ("女", "甜美"),
    "sweet lady": ("女", "甜美"),
    "thoughtful lady": ("女", "细致"),
    "thoughtful man": ("男", "深思"),
    "thoughtful mentor": ("男", "睿智导师"),
    "thoughtful woman": ("女", "细致"),
    "tranquil woman": ("女", "宁静"),
    "trustworthy advisor": ("男", "可信顾问"),
    "trustworthy man": ("男", "可信"),
    "upbeat man": ("男", "积极"),
    "wise lady": ("女", "睿智"),
    "wise scholar": ("", "学者"),
    "wise teacher": ("", "睿智讲解"),
    # 以下角色化 / 恋爱向 / 负面情绪，不展示
    **{
        name: None
        for name in [
            "airheaded girl",
            "angry man",
            "anime character",
            "arnold",
            "assertive queen",
            "attractive girl",
            "attractive guy",
            "bad-tempered boy",
            "brave adventurer",
            "brave female warrior",
            "brave heroine",
            "brave youth",
            "bright queen",
            "caring girlfriend",
            "charming elder sister",
            "charming queen",
            "charming santa",
            "charming sister",
            "cheerful boyfriend",
            "cheerful little sister",
            "childhood friend girl",
            "cocky guy",
            "cold girl",
            "cold queen",
            "cold young man",
            "crazy girl",
            "cute elf",
            "decisive princess",
            "decisive queen",
            "dominant man",
            "dramatist",
            "elegant princess",
            "enchanting sister",
            "fascinating boy",
            "fragile boy",
            "fussy hostess",
            "generous izakaya owner",
            "gentle butler",
            "ghost",
            "godfather",
            "grim reaper",
            "grinch",
            "handsome childhood friend",
            "haughty lady",
            "lonely warrior",
            "loyal knight",
            "mature partner",
            "movie lead female",
            "mysterious girl",
            "naughty schoolgirl",
            "passionate warrior",
            "pessimistic girl",
            "playboy charmer",
            "playful spirit",
            "pompous lady",
            "possessive man",
            "powerful soldier",
            "quirky girl",
            "romantic husband",
            "rudolph",
            "sad teen",
            "santa claus",
            "sassy girl",
            "serious commander",
            "shy girl",
            "stressed lady",
            "theatrical actor",
            "tough boss",
            "upset girl",
            "wandering sorcerer",
            "whimsical girl",
            "whispering girl",
            "wise elf",
        ]
    },
}


def _id_gender(voice_id: str) -> str:
    lowered = voice_id.lower()
    if "female" in lowered:
        return "女"
    if "male" in lowered:
        return "男"
    return ""


def clean_original(name: str | None) -> str:
    """供应商原名去掉「音色」「-beta」等冗余后缀（没有映射时的兜底）。"""
    text = re.sub(r"[-_ ]?beta$", "", (name or "").strip(), flags=re.I)
    return text.replace("音色", "").strip() or (name or "")


def _build() -> dict[str, dict[str, Any] | None]:
    catalog = json.loads(
        (Path(__file__).parent / "data/minimax-system-voices.json").read_text(
            encoding="utf-8"
        )
    )
    result: dict[str, dict[str, Any] | None] = {}
    seen: dict[str, int] = {}
    for voice in catalog["voices"]:
        voice_id, language = voice["voice_id"], voice["language"]
        if voice_id in HIDDEN_CHINESE:
            result[voice_id] = None
            continue
        if voice_id in CHINESE:
            gender, name, usage = CHINESE[voice_id]
        elif language.startswith("中文"):
            # 新增的中文声音必须先人工核对；未核对的先不展示。
            result[voice_id] = None
            continue
        else:
            entry = FOREIGN.get(voice["name"].lower())
            if entry is None:
                result[voice_id] = None
                continue
            gender, trait = entry
            gender = _id_gender(voice_id) or gender
            label = LANGUAGE_LABELS.get(language, language)
            name = f"{label}{gender + '声' if gender else '人声'} · {trait}"
            usage = f"{label}配音，适合面向{label}用户的商品讲解。"
        count = seen.get(name, 0) + 1
        seen[name] = count
        if count > 1:
            name = f"{name} {count}"
        result[voice_id] = {
            "name": name,
            "gender": gender or "未知",
            "description": usage,
        }
    return result


MINIMAX_DISPLAY = _build()


def minimax_display(voice: dict[str, Any]) -> dict[str, Any] | None:
    """返回 {name, gender, description}；None 表示不在系统声音列表里展示。"""
    return MINIMAX_DISPLAY.get(voice["voice_id"])


def quanyu_display(raw_id: str, original: str | None) -> dict[str, Any]:
    entry = QUANYU.get(raw_id)
    if entry and entry[0] == (original or "").strip():
        _, gender, name, usage = entry
        return {"name": name, "gender": gender, "description": usage}
    cleaned = clean_original(original)
    return {
        "name": cleaned,
        "gender": "男" if "男" in cleaned else "女" if "女" in cleaned else "未知",
        "description": "系统声音",
    }
