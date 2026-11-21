# Price Tracker design system: "Ledger & Petrol"

A pricing desk for an ops team that lives in it all day. It should feel like a trading desk crossed
with an editorial ledger: dense, calm, precise, warm. Every rule below exists to make one of three
answers instant: **are we competitive, what changed, and what needs my decision.**

## Colour

All colour is defined once as RGB triplets in `src/index.css` (light, dark, and `[data-theme]`
overrides) and exposed to Tailwind in `tailwind.config.ts`. Components never use raw hex.

| Token | Light | Dark | Job |
| --- | --- | --- | --- |
| `surface` | `#F4F1EA` paper | `#0B1214` | canvas |
| `raised` / `sunken` / `rail` | `#FFFDF8` / `#EDE9DF` / `#ECE8DE` | `#111B1E` / `#162225` / `#0D1517` | cards, insets, sidebar |
| `ink` / `muted` | `#12191B` / `#5B6461` | `#E8EEEC` / `#8FA09C` | text |
| `brand` | `#0F3D3E` petrol | `#EDE8DC` paper | primary actions, active nav |
| `band` | `#0F3D3E` | `#103434` | the Overview command band only |
| `accent` | `#17707F` aqua | `#5CC8DA` | focus rings, links, "live" |
| `good` | `#09704C` jade | `#4AD696` | competitor raised · approved · healthy |
| `bad` | `#B83028` vermilion | `#F27A6E` | competitor cut · rejected · failing |
| `warn` | `#7E5200` saffron | `#F2B84B` | needs attention · pending · we're pricier |
| `amazon` / `flipkart` | `#CC6212` / `#2F6FEB` | `#DD7526` / `#5F8FEF` | platform identity (charts, dots) only |

Rules:

- **Our own recommended actions are not alarms.** Lower / raise / hold badges are neutral ink with a
  direction glyph. Colour is kept for market direction (a competitor cut or raise) and for state.
- **Platform colours are used for nothing else**, so a tangerine dot always means Amazon.
- **Never colour alone.** Cuts and raises carry ▼/▲ glyphs, statuses carry a dot *and* a label.

Measured contrast, light theme (on the canvas): ink 15.8, muted 5.4, accent 5.1, good 5.4,
bad 5.3, warn 6.0; paper on petrol 10.6. Dark theme: muted 6.9, every semantic text colour 7.0 or
above. The chart palette was checked with the dataviz validator: the platform pair passes CVD
separation in both themes (ΔE ≥ 25), and the cut/raise fills pass (ΔE ≥ 17). In light mode the jade
fill sits under 3:1 as a graphic, so it always ships with counts and labels.

## Type

- **Geist** for UI. 14px body, 12–13px for dense tables, with 11px uppercase eyebrows (+0.07em).
- **Geist Mono** (`.mono`) for every price in tables, tickets and key figures: the ledger face.
- **Instrument Serif** (`.display`) for page titles and the Overview hero figures, **and nowhere
  else**. That contrast is the signature.
- Long marketplace titles are shown through `shortTitle()` (in `src/lib/format.ts`), with the full
  title in a tooltip.

## Shape and space

A 4px grid, with section rhythm at 24 / 32 / 40. Hairlines separate; shadows are reserved for
floating layers (popover, palette, dialog, toast) and the primary button's lift. Radii: 6–7 for
inputs, chips and buttons, 10 for cards, 14 for the band and dialogs.

## Signature moments

1. **Command band** (Overview): "N of M products at or below the lowest competitor", a segmented
   position bar, the average gap where we're pricier, and the approvals CTA.
2. **Rolling digits** (`RollingNumber`): correct on first paint, never counted up from zero. Digits
   roll only when a value changes on refresh, tinted once by direction.
3. **Market tape** (top bar): the latest move on every listing. It scrolls only when it overflows,
   pauses on hover or focus, and is static under reduced motion.
4. **Price history** (`PriceHistoryChart`): hand-built SVG step lines, our price drawn on top with a
   soft area, a hatched floor band, right-edge value labels and a crosshair tooltip. No chart
   library.
5. **Trade ticket** (`RecommendationCard`): current → proposed in large mono, the analyst's reasoning
   as a pull-quote with a confidence meter, the guardrails, and the one hero button in the app,
   Approve, with spring press feedback.

## Motion

Everything lives in `src/lib/motion.ts`: one ease-out curve for enters, springs for things that
move physically (nav indicator, tab underline, segmented thumb). Only transform and opacity
animate. Stagger happens on a page's first mount only, never on the 30-second refreshes.
Nothing animates on keyboard actions: the ⌘K palette opens instantly. `prefers-reduced-motion`
keeps fades and drops movement, rolling and the tape.
