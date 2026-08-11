---
name: ecommerce-model-pose-transfer
description: Pose-only transfer for ecommerce fashion-model images. Use when a user wants to change, imitate, or match a model pose from a second image, whether the input roles are already clear or need clarification. Execution requires exactly one single-person model_source and one unambiguous pose_reference; a catalog pose is supported only after the caller resolves it to a pose_reference image. Preserve source identity, body proportions, apparel, accessories, scene, lighting, and canvas. Do not use for model replacement, virtual try-on, garment replacement, identity transfer, background replacement, or style remixing.
---

# Ecommerce Model Pose Transfer

Transfer only pose geometry from `pose_reference` to `model_source`. Do not transfer the reference person's identity, apparel, or scene. Before editing, read and obey [the pose-transfer contract](references/pose-transfer-contract.md). Stop if the contract is unavailable.

## Preconditions

- Bind exactly one image as `model_source` and exactly one different image as `pose_reference`.
- `model_source` must contain one clear target person. If it contains multiple people, request an isolated crop or a new source image.
- `pose_reference` may contain other people only when one intended pose subject is unambiguous; otherwise ask the user to identify or crop it.
- If roles are unlabelled and the user's instruction does not resolve them, ask. Never infer roles from gender, clothing, filename, or image order alone.
- Stop when the source person, apparel, or reference pose is not usable.

## Select an editing path

1. Load and follow the installed `imagegen` skill when working in Codex.
2. Prefer an image-editing backend that accepts both inputs in one request. Submit `model_source` as the editable base image and `pose_reference` as the secondary pose-only reference. Label both roles explicitly in the request.
3. If the available editor accepts only one image, first inspect `pose_reference` and compile a geometry-only pose description. Edit `model_source` with that description and disclose that pose fidelity may be lower. Never use the reference person's pixels as reconstruction content.
4. Do not concatenate the two people into an unlabelled contact sheet, and never use the reference person as a base for face replacement or garment replacement.
5. If no image editor is available, do not claim that an image was generated. Return an execution-ready edit instruction plus the capability limitation, then stop.
6. Do not silently switch to a paid CLI/API fallback. Follow the active image tool's approval, credential, cost, and downgrade rules.

The website caller must resolve a catalog selection's stable slug/hash to the original-quality `pose_reference` before execution. Catalog thumbnails are UI-only and MUST NOT be sent to the image editor. This skill does not select catalog entries or resolve website asset IDs.

## Workflow

1. **Inspect separately.** Record source identity, proportions, apparel, accessories, logos/text, background, lighting, camera, source aspect ratio, framing, and crop. Separately abstract the reference skeleton, joint angles, orientation, balance, limb placement, and occlusion order. For dynamic poses, prioritize the main line of action, torso lean, arm-swing phase, center of gravity, and leg/gait phase.
2. **Compile the request.** State that the base image is the only appearance authority. List protected source facts, authorized pose geometry, prohibited reference facts, and regions that require pose-dependent reconstruction.
3. **Make the minimum edit.** Rebuild only the body articulation, garment drape, occlusions, contact shadows, and nearby source-consistent background forced by the pose. Preserve the source aspect ratio and framing semantics. Provider-normalized output resolution is acceptable when the editor cannot emit the exact source pixels; any subject repositioning or modest rescaling must remain inside the equivalent source-shaped canvas. Never expand or redesign the canvas to chase the reference pose.
4. **Inspect the render.** Apply the contract checklist for identity leakage, apparel drift, reference-person leakage, extra people, anatomy, hands/feet, protected graphics, background, canvas, localized blue-gray/cyan bands, color blocks, and edge smearing.
5. **Apply at most one focused correction when supported.** If critical identity/apparel leakage, an extra person, invalid source-inconsistent anatomy, or wrong aspect ratio remains, do not deliver it as compliant. Otherwise return the best valid result and disclose unresolved noncritical deviations.

## Conflict priority

1. Valid inputs, safety, and anatomical validity.
2. Source identity and body proportions.
3. Source apparel, accessories, protected graphics, scene, and lighting.
4. Reference pose geometry.
5. Source framing inside the unchanged canvas.
6. Beautification or style preference.

Approximate the pose whenever exact matching would violate a higher-priority fact.

## Output

- Return the actual image artifact and a concise limitation note when generation succeeds.
- If no image was generated, return only an execution-ready instruction and state that no artifact was produced.
- Generative editing cannot guarantee pixel-exact identity, logos, or text. Treat them as top-priority preservation and acceptance targets. Disclose the limitation before execution when the user requires an absolute guarantee the editor cannot provide.
- Report roles, completion status, known approximation, and items requiring human review. Do not expose hidden reasoning.
