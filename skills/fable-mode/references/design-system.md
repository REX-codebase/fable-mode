# Fable design system: evidence, not decoration

Use this reference for frontend creation or redesign. The target is a specific product experience that still works under real content, narrow screens, keyboards, reduced motion, errors, and slow devices.

## The quality loop

1. **Read the product.** Name the user, their immediate job, the most important action, the evidence they need, the content shape, and the technical constraints.
2. **Write a design thesis.** One sentence connecting product behavior to visual structure. Do not choose an aesthetic before the product signal is clear.
3. **Define roles, not paint.** Create tokens for canvas, surface, raised surface, text, muted text, border, accent, danger, focus, spacing, type, radius, and motion. Components consume roles.
4. **Compose around content.** Use concrete names, numbers, statuses, dates, and errors. Placeholder content hides layout failures.
5. **Implement the whole interaction.** Include default, hover, focus-visible, active, disabled, loading, empty, error, and success where the feature can reach them.
6. **Prove it in pixels.** Capture 360×800, 768×1024, and 1440×900. Inspect hierarchy, clipping, overlap, line length, image crop, and focus order. A source audit cannot certify appearance.
7. **Attack it.** Try long labels, a 200% text zoom, keyboard-only use, reduced motion, missing media, empty data, and a representative error.
8. **Write the receipt.** Record screenshots, checks, defects fixed, and known limits.

## Brief card

Before code, write:

```text
User:
Job:
Primary action:
Proof the user needs:
Content shape:
Constraints:
Design thesis:
Distinctive move:
What stays quiet:
```

If the brief is missing a load-bearing product choice, ask. If only aesthetic latitude is missing, choose a restrained direction and state it.

## Distinctiveness without costume

A page needs one product-derived move, not a bag of effects. Examples:

- a deployment product can make the receipt chain the main spatial spine;
- an editorial archive can let chronology control rhythm and navigation;
- a furniture catalogue can expose construction details through measured annotations;
- an operations view can reserve color for state change and ownership.

Do not default every page to dark glass, a centered hero, three cards, a bento grid, huge type, gradients, grain, or scroll theater. These can be correct, but only when the brief earns them.

## System contract

### Typography

- Pick fonts that are available or load them deliberately. A proprietary font name in a token is not an implementation.
- Keep body measure around 45-75 characters where prose matters.
- Test long words, numeric tables, mixed case, and 200% zoom.
- Use hierarchy to reveal order, not to make every heading loud.

### Color

- Use semantic roles and test actual foreground/background pairs.
- Meet WCAG 2.2 contrast for text and controls. Never claim contrast from a palette name.
- Do not use color as the only signal for status.
- Make focus visible against every surface.

### Layout

- Start with content order, then choose grid behavior.
- Ensure the reading order matches DOM and keyboard order.
- Prefer intrinsic sizing, `min()`, `max()`, `clamp()`, grid, and flexbox over viewport guesses.
- Test at the contract viewports and between them. Avoid `100vh` mobile jumps.

### Interaction and motion

- Controls need accessible names, 44px targets where practical, keyboard operation, and visible focus.
- Motion must explain continuity, hierarchy, or feedback. If removing it changes nothing, remove it.
- Honor `prefers-reduced-motion`; never hide essential state in animation.
- Animate transforms and opacity before layout properties.

### Content

- Labels state outcomes: "Create workspace", not "Continue".
- Empty states say what is absent and what the user can do.
- Errors identify the problem, preserve input, and offer recovery.
- Use believable names and metrics only when they are clearly sample data. Do not present invented proof as live telemetry.

## Creation and redesign

For a new interface, use the brief card and build the smallest complete path. For a redesign, first inventory routes, components, tokens, behavior, content, accessibility, and tests. Preserve product semantics and familiar flows unless the user asked to change them. Rank fixes by broken behavior, hierarchy, legibility, consistency, then polish.

## Mechanical tools and honest boundaries

Use `infer_design_brief` to get a starting direction, `generate_design_tokens` for roles, `audit_anti_slop` for known source patterns, and `validate_preflight_design` for source-level contracts. `generate_awwwards_scaffold` remains the compatibility name for a starter scaffold; treat the result as a hypothesis, not a finished brand.

None of these actions sees rendered pixels. Completion still requires screenshots and direct inspection. Use browser or host test tools for visual regression, keyboard checks, accessibility scans, and performance measurements.

## Release receipt

```text
Intent: [user/job/action]
Direction: [thesis + distinctive move]
Viewports inspected: [paths or URLs]
States checked: [list]
Automated checks: [commands and results]
Visual defects fixed: [list]
Known limits: [list]
```
