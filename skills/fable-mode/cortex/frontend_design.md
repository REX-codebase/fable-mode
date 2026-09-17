# Cortical lobe: frontend design

Use `../references/design-system.md` as the semantic owner for frontend work. Its loop is:

```text
READ -> THESIS -> SYSTEM -> BUILD -> RENDER -> ATTACK -> RECEIPT
```

The important learned scar is simple: code-shaped quality is not visual proof. A generated scaffold, regex audit, or token table can guide implementation, but only inspected pixels can establish hierarchy, crop, spacing, wrapping, and responsive correctness.

## Tool associations

- `infer_design_brief`: start a brief; verify its assumptions against the product.
- `generate_design_tokens`: produce role-based theme tokens; confirm font availability and actual contrast.
- `generate_awwwards_scaffold`: make a starting scaffold. The action name remains for compatibility, not as a quality claim.
- `audit_anti_slop`: catch known source patterns; do not turn its bans into a house style.
- `validate_preflight_design`: check source-level release contracts; follow its manual visual checks.
- `record_visual_mockups`: bind reviewed concepts or screenshots into the Fable evidence trail.
- `set_goal_rubric` / `evaluate_goal_rubric`: score the brief's actual user outcomes.

## Red-team scars

Reject or revise work when any of these are true:

- the visual direction is unrelated to product behavior;
- all domains become the same dark hero, glass card, bento grid, or gradient;
- placeholders hide the real content shape;
- invented metrics are styled as production evidence;
- hover is polished while loading, empty, error, disabled, and focus states are missing;
- desktop pixels are shown while mobile remains uninspected;
- source checks are reported as visual verification;
- a redesign silently changes information architecture or product behavior;
- proprietary or unavailable fonts are named but never loaded;
- reduced motion, keyboard order, contrast, or text zoom is untreated.

## Completion

A frontend completion record names the design thesis, viewports inspected, states checked, automated commands, defects fixed after visual review, and any unverified area. If the screenshots were not inspected, say so.
