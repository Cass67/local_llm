# Theme Overhaul: Modern Pro (Zinc-Indigo)

## Goal
Shift the UI from a "2010s Dark Blue" aesthetic to a "Modern Pro" developer-tool aesthetic. Focus on high contrast, neutral surfaces, and crisp accents to improve readability and perceived quality.

## Palette (The "Zinc-Indigo" Look)

| Element | Current (Navy) | Proposed (Zinc/Indigo) | Note |
| :--- | :--- | :--- | :--- |
| **Base BG** | `#1a1a2e` | `#09090b` | Deep Zinc/Black for maximum contrast |
| **Card BG** | `#16213e` | `#18181b` | Subtle lift from base |
| **Accent** | `#0f3460` | `#6366f1` | Vibrant Indigo for primary actions |
| **Border** | `#2a2a4a` | `#27272a` | Neutral zinc border |
| **Text** | `#e0e0e0` | `#fafafa` | Crisp off-white |
| **Text Muted**| `#a0a0a0` | `#a1a1aa` | Soft zinc-grey |

## Visual Improvements

### 1. Depth & Hierarchy
- **Contrast**: Instead of using different shades of blue, use a neutral dark base with explicit borders (`--border`) to define surfaces.
- **Elevation**: Use a subtle `translateY(-2px)` and border-color shift on hover for model cards to provide tactile feedback.
- **Glassmorphism**: Apply `backdrop-filter: blur(12px)` to the sticky header for a modern OS feel.

### 2. Typography & Accents
- **Mono Integration**: Use a dedicated mono stack (`JetBrains Mono`, etc.) for Model IDs, Aliases, and Logs to lean into the "LLM Ops" vibe.
- **Status Indicators**: Replace simple colors with "glowing" status dots (box-shadow) and subtle background tints for badges (e.g., ROCm = Red tint, Vulkan = Purple tint).
- **Accent Focus**: Limit the vibrant Indigo to primary buttons and active navigation states to prevent visual fatigue.

### 3. Component Refinements
- **Model Cards**: Transition from a "box" to a "card" with better internal spacing and a distinct `profile-select` area that looks like a nested utility.
- **Logs**: Use a pure black background (`#000`) for the log viewer to distinguish the "terminal" area from the rest of the app.
- **Search**: Simplify the search bar to a minimal, high-contrast input that glows on focus.

## Demo & Reference
- **Static Demo**: `theme_preview_full.html` contains the full interactive layout implementation of this theme.
- **Implementation Path**: 
  1. Update `:root` variables in `ui/src/app.css`.
  2. Update component styles in `.svelte` files to use the new var names and spacing patterns.
  3. Implement the sticky header and view transitions.
