# Model Pose Transfer Contract

Use this contract for a two-image edit that changes only the pose of an existing apparel model. Treat **MUST**, **MUST NOT**, and **SHOULD** as binding priorities.

## Contents

1. Input roles
2. Fact-source priority and capability limits
3. Authorized transfer
4. Prohibited transfer
5. Protected source facts
6. Pose construction procedure
7. Composition, crop, and mismatch rules
8. Occlusion and reconstruction rules
9. Anatomy and garment physics
10. Output QA checklist
11. Refusal and explicit limitation

## 1. Input roles

- **`model_source` — identity and appearance authority.** The only source of truth for the output person, face, hair, skin tone, apparent age, body characteristics, clothing, accessories, visible text/graphics, background, lighting, camera style, and overall image identity.
- **`pose_reference` — pose geometry authority only.** Supplies body orientation, skeletal arrangement, joint angles, balance, limb placement, hand/foot placement, and pose rhythm. It supplies no identity, apparel, accessory, scene, or styling facts.
- Require exactly one usable image for each role. Never swap or merge the roles.
- A catalog `pose_reference` MUST resolve by stable slug/hash to the original-quality asset. Thumbnails are UI-only and MUST NOT enter generation.
- `model_source` must contain exactly one clear person. If it contains multiple people, request an isolated crop or a new source image.
- If roles are unlabelled and user intent does not resolve them, ask for clarification. Do not infer roles from gender, clothing, filename, or image order alone.
- If `pose_reference` contains multiple people, proceed only when one intended pose subject is unambiguous; otherwise request a crop or explicit identification.

## 2. Fact-source priority and capability limits

Resolve conflicts in this order:

1. Safety, anatomical validity, and physical plausibility.
2. `model_source` identity, clothing, logos/text/prints, accessories, scene, and visual style.
3. `pose_reference` pose geometry.
4. Minimal inferred pixels needed to complete newly exposed regions.

If exact pose matching would violate a higher-priority fact, preserve the higher-priority fact and approximate the pose. Never invent a compromise identity or hybrid outfit.

These are preservation and acceptance targets, not a promise of pixel-exact identity, logo, print, or text reproduction. If the selected editor cannot guarantee an absolute requirement, disclose that limitation before execution. Never claim a checklist item passed without inspecting the rendered result.

## 3. Authorized transfer

Transfer only what is required to express the reference pose:

- torso and pelvis orientation;
- head direction and tilt, without changing facial identity;
- shoulder, elbow, wrist, hip, knee, and ankle configuration;
- stance width, weight distribution, center of gravity, and body lean;
- arm, hand, leg, and foot placement;
- silhouette changes caused by articulation;
- pose-dependent garment drape, folds, tension, compression, and occlusion;
- self-occlusion and depth ordering required by the pose.

The target is perceptual pose equivalence, not pixel tracing. Adapt geometry to the source person's proportions, outfit, footwear, crop, and available canvas.

## 4. Prohibited transfer

MUST NOT copy, blend, or infer from `pose_reference`:

- face, facial features, expression identity, age, skin tone, makeup, hair, or body identity;
- body shape or proportions beyond unavoidable perspective effects;
- clothing, footwear, accessories, jewelry, props, logos, prints, colors, or materials;
- background, furniture, objects, other people, lighting, shadows, camera treatment, or color grade;
- visible words, watermarks, signatures, brands, or decorative graphics;
- gender presentation or other person attributes merely implied by the reference.

MUST NOT create a second person, duplicate the source person, retain the reference person, or produce a recognizable hybrid of both people.

## 5. Protected source facts

### Identity

- Preserve the source face and recognizable identity. Keep facial geometry, skin tone, apparent age, hairline, hairstyle, and distinguishing visible traits stable.
- Rotate or foreshorten the head only as required by the pose. Do not beautify, age, de-age, change ethnicity, change expression unnecessarily, or replace hidden facial regions with reference-person features.
- Preserve body build and limb proportions as far as perspective allows.

### Clothing and accessories

- Preserve garment category, cut, layering, fit, length, color, material, texture, seams, closures, pockets, collars, cuffs, hems, and accessories.
- Reconstruct newly exposed garment areas by extending patterns and construction cues from `model_source`, never from `pose_reference`.
- Pose-induced folds may change; garment identity and construction may not.
- Do not remove, add, restyle, resize, or relocate accessories except for the smallest physically required shift caused by articulation.

### Logos, prints, and text

- Aim to preserve each visible logo, print, emblem, graphic, and text element in content, count, color, scale, orientation on the garment, and approximate placement.
- Warp them only with the underlying fabric. Keep letters legible when they were legible in the source; if exact characters cannot be preserved, flag the result instead of claiming exact fidelity.
- Never hallucinate missing characters, mirror text, substitute a brand, duplicate a motif, or copy graphics from the reference.
- If occlusion makes an element invisible in the new pose, hide it naturally rather than relocating it to keep it visible.

### Background and image style

- Preserve the source background, lighting direction, exposure, color grade, lens feel, depth of field, and shadow logic.
- Modify only the local regions vacated or newly occupied by the posed body. Reconstruct background from nearby source evidence.
- Do not import reference-scene objects or reference lighting. Do not perform an unsolicited background replacement, relighting, or crop redesign.

## 6. Pose construction procedure

1. Identify stable source facts: person identity, proportions, garment topology, protected graphics, accessories, camera, crop, and scene.
2. Abstract the reference into a pose skeleton: head–spine–pelvis axis, shoulder/hip lines, joint positions, limb depth order, support foot, and center of gravity. For dynamic poses, lock the main line of action, torso lean, arm-swing phase, weight shift, and leg/gait phase before secondary joint detail. Ignore the reference person's appearance.
3. Retarget that skeleton to the source person's proportions and garment constraints. Preserve plausible limb lengths and joint ranges.
4. Move the source body as a single coherent articulated figure. Maintain torso–pelvis connection and correct front/back limb ordering.
5. Re-drape the original garments over the new body geometry. Propagate seams, texture, logos, prints, and folds consistently across visible surfaces.
6. Rebuild only newly exposed body, garment, and background regions from source-consistent evidence.
7. Validate the complete image against the checklist before returning it.

## 7. Composition, crop, and mismatch rules

Apply the least invasive feasible option in this order:

1. Keep the source aspect ratio, canvas bounds, viewpoint, framing semantics, and crop policy. Never expand the canvas to chase the reference pose.
2. Adapt the reference pose to the available source-shaped canvas while retaining its defining gesture.
3. If needed, modestly reposition or rescale the source person inside that canvas and fill only newly exposed areas with source-consistent background.
4. Provider-normalized pixel dimensions are acceptable when exact source resolution is unsupported, but the aspect ratio and framing semantics MUST remain source-derived. If full-pose reproduction remains impossible, preserve identity, apparel, anatomy, and source composition; return the closest valid partial pose.

Specific cases:

- **Source half-body, reference full-body:** reproduce the visible upper-body geometry and implied weight/torso direction. Do not invent legs solely to claim an exact match.
- **Source full-body, reference half-body:** reproduce the available upper-body pose; keep lower-body stance physically compatible and source-consistent. Do not guess hidden reference legs.
- **Different viewpoints:** approximate the pose in the source camera view. Do not force a rotation that requires inventing most of the face, garment, or body.
- **Different body proportions or restrictive apparel:** preserve source proportions and garment construction; relax extreme joint angles or limb spacing.
- **Reference limbs outside the source frame:** keep the original crop when possible; crop limbs only at natural frame boundaries, never at a joint solely to mimic the reference.
- **Required content outside the canvas:** adapt or reduce the pose inside the source-shaped canvas. Do not change to the reference aspect ratio or redesign the framing.

## 8. Occlusion and reconstruction rules

- Respect the reference pose's depth order only when anatomically valid for the source camera.
- A limb placed behind the torso must remain behind; a limb placed in front must create correct contact and occlusion boundaries.
- Newly hidden source details must disappear naturally. Never paste protected details over an occluding hand or limb.
- Newly revealed face, skin, garment, and background areas must be inferred from `model_source` only.
- If a critical identity or apparel region would require high-confidence invention with no source evidence, reduce the pose change rather than fabricate it.
- Do not use reference pixels as reconstruction content, even when their geometry aligns.

## 9. Anatomy and garment physics

- Preserve the source person's actual anatomy, including any visible limb difference, prosthesis, mobility aid, or other body characteristic. Produce one coherent source-consistent body; never add a limb or body part that the source person does not have. For a source person with typical visible anatomy, ensure the expected head, torso, pelvis, limbs, hands, and feet are coherent when within frame and not legitimately occluded.
- Maintain continuous limbs, plausible bone lengths, natural joint limits, stable balance, and credible contact with the ground or supporting surface.
- Hands must have plausible palm orientation, wrist connection, finger count, finger separation, and object/body contact. Prefer natural partial occlusion over malformed explicit fingers.
- Feet must connect correctly to ankles, preserve the source footwear, follow surface perspective, and support the body plausibly.
- Avoid duplicated, fused, floating, missing, or disconnected body parts; twisted joints; impossible intersections; and unexplained changes in limb thickness.
- Garments must remain continuous across joints and occlusions. Seams, hems, straps, layers, closures, prints, and texture must follow surface perspective without tearing, melting, duplication, or sudden discontinuity.
- Folds and tension must respond to gravity, compression, stretch, contact, and joint bending. Do not preserve source folds as a pasted texture when the new geometry makes them impossible.

## 10. Output QA checklist

Inspect every applicable item before delivery. Critical identity leakage, reference-apparel leakage, extra people, source-inconsistent anatomy, or wrong aspect ratio blocks delivery; lesser unresolved deviations must be disclosed:

### Inputs and role isolation
- [ ] Exactly one `model_source` and one `pose_reference` were used.
- [ ] Only pose geometry came from `pose_reference`.
- [ ] No reference-person, outfit, accessory, prop, background, text, or lighting leaked into the output.

### Identity
- [ ] Output contains exactly one person.
- [ ] Face remains recognizably the source person; skin tone, age impression, hair, and body build are stable.
- [ ] No blended, substituted, duplicated, or partially retained reference identity is visible.

### Pose and anatomy
- [ ] The defining reference gesture, orientation, joint arrangement, and weight distribution are recognizable.
- [ ] Retargeting fits the source proportions and camera view.
- [ ] Head, neck, shoulders, torso, pelvis, limbs, hands, and feet connect naturally.
- [ ] No extra, missing, fused, floating, stretched, or malformed anatomy is visible.
- [ ] Balance, ground contact, depth ordering, and self-occlusion are physically plausible.

### Apparel and protected graphics
- [ ] Original garments, footwear, accessories, colors, materials, cut, layering, and lengths are preserved.
- [ ] Seams, hems, closures, straps, folds, and texture remain continuous and physically plausible.
- [ ] Logos, prints, graphics, and text retain identity, count, spelling, orientation, and garment-relative placement, subject only to natural warp or occlusion.
- [ ] No reference apparel or graphics appear.

### Scene and rendering
- [ ] Original canvas/aspect ratio, framing, background, lighting, shadows, color grade, and camera style are preserved except for justified minimal reconstruction.
- [ ] Reconstructed regions match neighboring source detail without obvious seams, holes, smears, repeated texture, localized blue-gray/cyan bands, flat color blocks, or edge paint-over artifacts.
- [ ] Crop choices are natural; no important anatomy is cut at an implausible location.

## 11. Refusal and explicit limitation

Reject the edit rather than inventing a result when:

- either input is missing, unreadable, not an image, or contains no usable person/pose;
- `model_source` contains more than one person;
- the requested operation requires identity replacement, undressing, prohibited content, or transfer of non-pose facts from the reference;
- source evidence is insufficient to preserve the requested person's or garment's essential identity under any safe pose adaptation;
- a valid single-person anatomical result cannot be produced without fabricating major unseen content.

When an edit is possible only approximately, do not falsely claim an exact match. Preserve higher-priority source facts, produce the closest anatomically valid pose, and explicitly state the limitation, such as:

- exact limb placement was relaxed to preserve anatomy;
- only the visible portion of a full-body pose was transferred;
- camera-view mismatch required a pose approximation;
- crop or garment constraints prevented full reproduction;
- a protected logo/text detail became naturally occluded.
