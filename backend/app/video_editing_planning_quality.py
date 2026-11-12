"""Free transcript checks and opt-in native binding instructions."""

from difflib import SequenceMatcher

from .errors import ApiError
from .video_editing_contracts import Transcript

NATIVE_BINDING_POLICY = "tengli.native-binding-rules/1"
NATIVE_BINDING_PROMPT = (
    "native_text、native_events、native_media 中每个 path 只能出现一次。"
    "按 native_word_binding_contract 完整绑定全部必需文字、事件和媒体字段；"
    "同一个标量入场事件不能重复绑定 start 和 end。"
    "emphasis_token_ids 只能为一段连续词 ID，多个分散重点应留空，"
    "不得把不连续词拼成原生文字。"
    "Z-M01、Z-M04 的两句各至多九字，phrase0、phrase1 均用各句首词的 start；"
    "Z-M04 的 move 与 phrase1 同步。"
    "Z-M02 必须有三段实际短字幕，每段都绑定自己的 start 和 end 字段；"
    "darken 对第一段首词，release 对第三段首词，不能只填一段或两段。"
    "Z-M03 需要 title、三个 labels、summary 五个文字槽及对应入场点，"
    "relation 为 parallel，三个 relation_items 分别绑定三个 labels；"
    "没有三个真实并列项时不能选择本组。"
    "Z-M09 的 relation 为 contrast，两项分别绑定 premise、answer，"
    "保留完整否定，不能把无对比的普通说明强行改为对比。"
    "Z-M11 方格纸需要两行，各行 label 一至三字、text 一至十二字，"
    "使用 omit_sentence_punctuation；relation 为 parallel，"
    "两个 relation_items 各绑定本行 label 和 text 的完整实录范围。"
    "row0、row1 各只有一个 start 入场点，必须绑定各行 label 首词；"
    "两行须按实录先后出现，末字之后保留原生阅读时间。"
    "不满足某组的完整字段、真实语义或阅读时间时保留 Z-M00 并说明原因，"
    "不得为凑种类编造文字、关系、字段或时间。"
)


def require_reference_transcript(
    transcript: Transcript, source_kind: str, generation_lineage: dict | None
) -> None:
    """Never bill a new plan for badly incomplete ASR of our confirmed script.

    Uploaded/reference-only videos and explicit correction revisions retain
    their existing behavior. This does not substitute script text for speech.
    """
    if (
        source_kind != "generation_task"
        or not generation_lineage
        or generation_lineage.get("generation_script_snapshot") != "matched"
        or transcript.text_status != "automatic"
        or transcript.text_revision_id is not None
        or transcript.reference_matches is not False
        or not transcript.reference_text
    ):
        return
    expected = "".join(c for c in transcript.reference_text if c.isalnum())
    actual = "".join(
        c for token in transcript.tokens for c in token.text if c.isalnum()
    )
    if len(expected) < 30:
        return
    similarity = SequenceMatcher(None, expected.casefold(), actual.casefold()).ratio()
    if len(actual) < len(expected) * 0.8 or similarity < 0.75:
        raise ApiError(
            409,
            "EDITING_TRANSCRIPT_REVIEW_REQUIRED",
            "自动字幕与这条口播的已确认原稿差异较大，请先校对字幕并重新对齐，"
            "再继续编排。此检查不会提交计费模型请求。",
        )
