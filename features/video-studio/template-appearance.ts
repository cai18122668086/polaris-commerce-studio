// Library presentation for catalog cards. Names, collections and hidden templates live in editing-presentation.
import { TEMPLATE_COLLECTIONS, templateEntry, templateFallbackCollection, type TemplateCollection } from "./editing-presentation";

export { TEMPLATE_COLLECTIONS, isTemplateListed, type TemplateCollection } from "./editing-presentation";

export function templateAppearance(card: { id: string; name: string; category: string; visual_features: string[] }) {
  const entry = templateEntry(card.id);
  const collection: TemplateCollection = entry?.[0] ?? templateFallbackCollection(card.category) ?? "人物出镜";
  return {
    collection,
    name: entry?.[1] ?? card.name.replace(/^.+?[·\-]\s*/, "").replace(/-?模板$/, ""),
    detail: entry?.[2] ?? card.visual_features.slice(0, 2).join(" · "),
    hint: TEMPLATE_COLLECTIONS.find(row => row.name === collection)!.hint,
  };
}
