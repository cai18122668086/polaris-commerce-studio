# Retry and feedback control

## Revision-cycle budget

A module revision cycle has exactly two possible render slots:

1. initial render;
2. one automatic repair that edits the initial render.

After the second failed audit, enter `REPAIR_EXHAUSTED`. Reject the asset, keep residual failures visible, do not advance, and do not call image generation again. File creation, attractiveness, partial improvement, or schedule pressure cannot override this gate.

Do not disguise a third automatic attempt as a user adjustment, prompt rewrite, fresh generation, alternate tool call, context restart, or audit relaxation. Only an explicit user instruction naming a change may open a new revision cycle. The new cycle keeps the old cycle ID, attempts, diagnoses, and residuals in revision history and receives its own two-slot ceiling.

## Feedback scope

Store only true campaign invariants globally:

- canonical product identity;
- approved factual claims and forbidden inventions;
- series visual DNA and independent-logo policy;
- approved page story and reference-use policy.

Store screen-specific requests under the named module:

- move this screen's title beside the product;
- reduce this screen's numeric block;
- keep this screen's successful texture treatment;
- do not repeat this screen's comparison frame.

The prompt compiler includes global constraints plus only the current module's local constraints. It must never import another module's placement, crop, wording, or repair diagnosis.

## Audit integrity

The second audit uses the same material-failure standard as the first. Do not accept a still-failing screen merely to continue. Report the failed contract fields and wait for the user to choose a local adjustment, replan, or stop.
