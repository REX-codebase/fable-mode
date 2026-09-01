# Fable Mode Design Tokens & Typographic Matrix

## 1. Universal Base Tokens (OKLCH Precision)

```css
:root {
  /* ────────── Atmospheric Voids (Layer 0) ────────── */
  --void-obsidian: oklch(0.08 0.02 270);
  --void-charcoal: oklch(0.12 0.01 260);
  --void-bone: oklch(0.97 0.005 90);
  --void-paper: oklch(0.99 0.002 90);

  /* ────────── Glass & Refraction Substrates (Layer 3) ────────── */
  --glass-surface-dark: oklch(0.14 0.015 270 / 0.65);
  --glass-surface-light: oklch(0.98 0.005 90 / 0.70);
  --glass-blur: 24px;
  --glass-saturate: 180%;

  /* ────────── Hairline Specular Rims (Layer 4) ────────── */
  --rim-specular-light: oklch(1 0 0 / 0.16);
  --rim-specular-subtle: oklch(1 0 0 / 0.08);
  --rim-inner-bevel: inset 0 1px 0 0 oklch(1 0 0 / 0.18);
  --rim-drop-shadow: 0 16px 36px -6px oklch(0 0 0 / 0.40);

  /* ────────── Curated Spectral Accents (High-Voltage Singletons) ────────── */
  --accent-cyan-lume: oklch(0.85 0.18 195);
  --accent-lime-volt: oklch(0.92 0.22 130);
  --accent-solar-flare: oklch(0.75 0.22 45);
  --accent-international-blue: oklch(0.48 0.24 260);
  --accent-international-red: oklch(0.58 0.24 25);
  --accent-nordic-amber: oklch(0.72 0.16 70);

  /* ────────── Fluid Golden-Ratio Typography (Layer 5) ────────── */
  --text-hero: clamp(2.75rem, 1.43rem + 5.63vw, 6.50rem);
  --text-h1: clamp(2.00rem, 1.21rem + 3.38vw, 4.25rem);
  --text-h2: clamp(1.50rem, 1.06rem + 1.88vw, 2.75rem);
  --text-h3: clamp(1.25rem, 1.03rem + 0.94vw, 1.875rem);
  --text-body-lead: clamp(1.0625rem, 0.99rem + 0.28vw, 1.25rem);
  --text-body: clamp(0.9375rem, 0.89rem + 0.19vw, 1.0625rem);
  --text-caption: clamp(0.8125rem, 0.79rem + 0.09vw, 0.875rem);
  --text-mono-telemetry: clamp(0.6875rem, 0.64rem + 0.19vw, 0.8125rem);
}
```

---

## 2. Archetype Palette Profiles

### Archetype 1: Cyber-Obsidian Monolith
```css
[data-theme="cyber-obsidian"] {
  --bg-primary: oklch(0.08 0.02 270);
  --bg-surface: oklch(0.12 0.015 270);
  --border-hairline: oklch(1 0 0 / 0.10);
  --text-primary: oklch(0.98 0.005 270);
  --text-secondary: oklch(0.70 0.01 270);
  --text-tertiary: oklch(0.45 0.01 270);
  --accent-primary: oklch(0.85 0.18 195); /* Luminescent Cyan */
  --font-display: 'PP Neue Machina', 'Cabinet Grotesk', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
  --radius-subtle: 2px;
}
```

### Archetype 2: Haute Editorial Modernism
```css
[data-theme="haute-editorial"] {
  --bg-primary: oklch(0.97 0.008 85);
  --bg-surface: oklch(0.94 0.012 85);
  --border-hairline: oklch(0 0 0 / 0.12);
  --text-primary: oklch(0.14 0.015 50);
  --text-secondary: oklch(0.40 0.02 50);
  --text-tertiary: oklch(0.60 0.02 50);
  --accent-primary: oklch(0.48 0.18 35); /* Deep Ochre Crimson */
  --font-display: 'PP Editorial New', 'Tiempos Headline', 'Cormorant Garamond', Georgia, serif;
  --font-body: 'Söhne', 'Geist Sans', system-ui, sans-serif;
  --radius-subtle: 0px;
}
```

### Archetype 3: Swiss Precision & Vignelli
```css
[data-theme="swiss-precision"] {
  --bg-primary: oklch(0.99 0 0);
  --bg-surface: oklch(0.95 0 0);
  --border-hairline: oklch(0 0 0 / 0.18);
  --text-primary: oklch(0.10 0 0);
  --text-secondary: oklch(0.40 0 0);
  --accent-primary: oklch(0.58 0.24 25); /* International Red */
  --font-display: 'Neue Haas Grotesk Display Pro', 'Helvetica Now Display', system-ui, sans-serif;
  --font-mono: 'Space Mono', monospace;
  --radius-subtle: 0px;
}
```

### Archetype 4: Kinetic Spatial HUD
```css
[data-theme="kinetic-hud"] {
  --bg-primary: oklch(0.06 0.015 250);
  --bg-surface: oklch(0.10 0.02 250 / 0.75);
  --border-hairline: oklch(0.85 0.18 195 / 0.25);
  --text-primary: oklch(0.95 0.01 250);
  --text-secondary: oklch(0.70 0.02 250);
  --accent-primary: oklch(0.92 0.22 130); /* Acid Lime Telemetry */
  --font-display: 'Geist Mono', 'Iosevka Term', monospace;
  --font-body: 'Instrument Sans', system-ui, sans-serif;
  --radius-subtle: 4px;
}
```

---

## 3. Verified Fluid Scale Calculation Table

```
Viewport:  375px        768px        1024px       1440px
Hero:      44.0px       66.1px       80.5px       104.0px
H1:        32.0px       45.3px       53.9px       68.0px
H2:        24.0px       31.4px       36.2px       44.0px
H3:        20.0px       23.7px       26.1px       30.0px
Body:      15.0px       15.7px       16.2px       17.0px
Telemetry: 11.0px       11.7px       12.2px       13.0px
```
