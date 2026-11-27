# Selling-point depth and module-count planning

Use this contract before choosing module count. Its purpose is to distinguish “mentioned” from “sold through”. It is category-neutral and does not prescribe a conventional page length.

## Three candidate modes

Every normal sales page compares three distinct candidates:

- `COMPACT_COVERAGE`: the shortest truthful page that mentions every active fact and preserves the pain-to-solution chain. It is a diagnostic lower bound, not the default recommendation.
- `BALANCED_EXPRESSION`: gives primary selling points enough independent visual persuasion while merging genuinely shared evidence and buyer questions.
- `FULL_SALES`: adds non-duplicative decision angles such as dedicated use scope, material/detail, operation, selection, risk removal or reinforced recall when evidence supports them.

Counts must be distinct and normally increase in that order. The selected candidate must be `BALANCED_EXPRESSION` or `FULL_SALES` unless the user explicitly requested a short/compact page or the evidence can support only the compact option. “Fewer screens”, “cleaner”, or “already mentioned” is not enough justification.

Each candidate records coverage trade-off, selling-point fit, story-obligation fit, primary-selling-point depth fit, evidence-boundary fit and decision.

## Selling-point depth contract

For each primary verified selling point, record:

- claim ID and priority;
- depth tier: `DEEP`, `STANDARD` or `SUPPORT`;
- evidence ceiling: `DIRECT_PROOF_AVAILABLE`, `QUALIFIED_CLAIM_ONLY`, `PACKAGING_CLAIM_ONLY` or `CONTEXT_ONLY`;
- required decision jobs;
- scheduled module IDs;
- why those modules are non-duplicative;
- forbidden expansion.

Decision jobs use this vocabulary:

`PROBLEM_CONTEXT`, `VALUE_OVERVIEW`, `DEDICATED_EXPRESSION`, `MECHANISM_OR_REASON`, `USE_SCOPE`, `ACTION_OR_OPERATION`, `RESULT_OR_EXPERIENCE`, `RISK_QUALIFICATION`, `SELECTION`, `TRUST`, `RECALL`.

The must-remember set is the primary depth set. Every must-remember claim is `PRIMARY` and `DEEP`. A `DEEP` claim needs `VALUE_OVERVIEW`, `DEDICATED_EXPRESSION`, `RECALL`, and at least one evidence-supported mechanism/use/action/result/selection/trust job across at least three modules. Record `module_jobs` so each module-to-job assignment can be audited. A dedicated module must lead with that claim; appearance as a supporting claim does not count. Shared overview and closure may count, but a screen containing several primary claims is only overview unless each has a separate visual zone, proof relation and scan stop.

Secondary and tertiary facts may remain `STANDARD` or `SUPPORT`; they do not enter the must-remember set unless promoted by user emphasis or purchase importance.

## Dynamic count formula

Choose counts only after depth planning:

`base_narrative_jobs + primary_depth_expansion + supporting_jobs - shared_proof_savings = computed_balanced_minimum`

- `base_narrative_jobs` is at least three for a normal sales page: hook, pain/bridge and purchase closure.
- `primary_depth_expansion` is at least two per primary claim; overview and recall may be shared, while dedicated proof cannot be borrowed from another claim.
- `supporting_jobs` covers genuinely necessary operation, selection, sensory, specification or trust decisions supported by evidence.
- `shared_proof_savings` is allowed only when the buyer question, visible proof relation and commercial conclusion are all shared. It cannot exceed the number of primary claims minus one.

The selected balanced or full-sales count may not fall below the formula. Compact selection remains an explicit user/evidence-limited exception.

## When related selling points may be split

Facts sharing a broad umbrella may still answer different buyer questions. “Hygiene”, “comfort”, “durability” or “convenience” is not automatically one selling point. Split when the sub-points have different use contexts, objections, visual carriers, evidence qualifications or purchase consequences.

An overview screen may group several sub-points, but it does not consume their need for deeper expression when they are primary selling points. Repetition is valid only when the buyer job or visual proof changes.

## Formula, ingredient, structure and element selling points

When product information is supplied, do not collapse prominent formula/ingredient/structure/element claims into one generic “成分” screen. Promote an item to an independent formula claim when it is foregrounded by the user or packaging and has its own buyer question, user problem, benefit, use consequence or evidence boundary. Each promoted independent claim receives a dedicated storyboard module/screen and a visible bridge:

`what it is → what it does (within the evidence ceiling) → which buyer problem or decision it addresses → why the buyer cares`.

An overview may introduce the formula family, but cannot replace the dedicated screens. Merge only synonyms, quantitative descriptors of the same claim, or items sharing the same function, evidence condition and visual proof. A formula screen may lead with the ingredient/structure itself; the product pack is optional when the claim object, process or result is the stronger visual carrier. Use clean diagrams, macro material views, source-to-result paths or comparisons as appropriate, without inventing molecular geometry, internal structure, efficacy, dosage or test results.

When this rule is triggered, the plan must expose `formula_split_contract`, recording each formula/element, independent-split reason, corresponding buyer problem/question, supported benefit, evidence ceiling, dedicated module ID and visual expression route. The module-count rationale must include these dedicated modules; crowding independent formula claims onto one screen is a planning defect.

## Evidence ceiling during expansion

More screens never authorize stronger claims.

- `DIRECT_PROOF_AVAILABLE`: may use the documented result, mechanism or comparison within its conditions.
- `QUALIFIED_CLAIM_ONLY`: may present the qualified claim and safe use/result context, not an invented test or mechanism.
- `PACKAGING_CLAIM_ONLY`: may show the authentic package and its claim, plus the buyer concern/use scope and a concise qualifier. Evidence provenance remains machine-side: never make “包装可见、宣称来源、包装位置、缺少检测报告” the screen duty, lead conclusion or primary visual story. A clearly stylized `CONCEPTUAL_NON_DIAGNOSTIC` visualization may show the claim object and a generic commercial state change—such as being surrounded, separated, reduced, removed or blocked—so the claim is not carried by text alone. It must not look like microscopy or laboratory evidence and may not invent exact organism morphology, a causal mechanism, a percentage, a detection condition or a clinical/experimental result.
- `CONTEXT_ONLY`: may establish a buyer problem or scene but cannot claim that the product resolves it without a verified value bridge.

When evidence is thin, expand through truthful context, product detail, operation, selection, sensory experience or information clarity. Never create filler screens, duplicate the same packshot/copy relationship, or turn one weak claim into multiple pseudo-proof screens.

## Selection rule

Select the smallest candidate that satisfies all primary depth obligations, preserves distinct buyer questions and visual carriers, respects evidence ceilings, and still forms an intentional commercial rhythm. This is not the same as the smallest candidate that can list every fact.
