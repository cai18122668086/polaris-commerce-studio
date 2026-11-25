/** 写稿被后端拒绝时，指出具体是哪一句或哪一处事实替换没通过。 */
export type WritingIssue = { kind: string; index: number; text: string };

const quote = (text: string) => (text.length > 40 ? `${text.slice(0, 40)}…` : text);

export function writingIssueMessage(issue?: WritingIssue | null): string {
  if (!issue || !Number.isInteger(issue.index) || issue.index < 0) return "上次写稿未通过检查，请核对原文和事实后重试。";
  const n = issue.index + 1;
  const text = quote(issue.text || "");
  switch (issue.kind) {
    case "replacement_ungrounded":
      return `上次写稿未通过检查：第 ${n} 处事实替换「${text}」，替换后的文字在事实卡或正文里找不到原样内容。可以重试，或把事实卡写成口播里会说的原话。`;
    case "source_leftover":
      return `上次写稿未通过检查：第 ${n} 处事实替换后，原文里的「${text}」仍留在新稿中。请重试。`;
    case "numeric_claim":
      return `上次写稿未通过检查：第 ${n} 句「${text}」含有事实卡里没有的数字或数量。请在事实卡补充，或重试。`;
    case "unknown_fact":
      return `上次写稿未通过检查：第 ${n} 句「${text}」引用了事实卡里没有提供的事实。请重试。`;
    case "section_order":
      return text ? `上次写稿未通过检查：新稿没有按拆解顺序写到「${text}」这一段。请重试。` : "上次写稿未通过检查：新稿没有按拆解顺序覆盖每一段。请重试。";
    default:
      return "上次写稿未通过检查，请核对原文和事实后重试。";
  }
}
