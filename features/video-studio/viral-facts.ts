import type { Fact, Facts, Slot } from "./use-viral-writing";

/** Fixed questions; a teardown slot that already asks the same thing replaces one. */
export const BASE: { id: string; category: Fact["category"]; label: string; question: string; rows: number }[] = [
  { id: "me", category: "identity", label: "我的身份", question: "你是谁？例如：做了 8 年护肤的美容师、两个孩子的妈妈", rows: 1 },
  { id: "product", category: "product", label: "产品名称", question: "你要讲的产品叫什么？", rows: 1 },
  { id: "points", category: "product", label: "核心卖点", question: "产品最打动人的 2–3 个卖点、规格或价格（只写真实的）", rows: 3 },
  { id: "story", category: "story", label: "真实经历", question: "你或客户用过的真实经历、前后变化（选填）", rows: 2 },
];

type SlotLike = Pick<Slot, "id" | "category" | "label" | "question">;

/** A fixed field the teardown already asks for (「我的身份」「产品名」) is not asked twice. */
export const asked = (slots: Pick<Slot, "label">[], item: (typeof BASE)[number]) => slots.some(slot => slot.label === item.label
  || (item.id === "me" && /身份/.test(slot.label)) || (item.id === "product" && /产品名|品名/.test(slot.label)));

/** The slot id is the fact id the model sees; only a clash with a base field gets a prefix. */
export const slotKey = (id: string) => BASE.some(item => item.id === id) ? "slot-" + id : id;

/** The fact card sent to the writer: answered = user_declared, blank = unknown (never used). */
export function buildFacts(slots: SlotLike[], answers: Record<string, string>, forbidden: string, limits: Facts["restricted_claims"]): Facts {
  const rows = [
    ...slots.map(slot => ({ id: slotKey(slot.id), category: slot.category, label: slot.label })),
    ...BASE.filter(item => !asked(slots, item)),
  ];
  return {
    facts: rows.map(row => {
      const value = (answers[row.id] || "").trim();
      return { id: row.id, category: row.category, label: row.label, value: value || null, status: value ? "user_declared" as const : "unknown" as const, source_note: "用户填写" };
    }),
    forbidden_terms: [...new Set(forbidden.split("\n").map(s => s.trim()).filter(Boolean))].slice(0, 100),
    restricted_claims: limits,
  };
}
