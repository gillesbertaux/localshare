# localshare brand

Everything here is MIT-licensed along with the rest of the repo. Use the marks to
refer to localshare — in a README, a blog post, a talk, a client that wraps the
CLI. Don't use them as the identity of a different product, or in a way that
implies the project endorses yours.

## The mark: Reach Dial

<img src="png/logo-256.png" alt="" width="96" height="96">

A filled dot with three concentric arcs opening at the bottom left.

- **The dot is localhost.** It never changes. Your server is always the thing in
  the middle; localshare only decides how far it carries.
- **The arcs are reach, ordered by distance.** Inner is the LAN (same Wi-Fi),
  middle is the tailnet (your devices, anywhere), outer is the public internet.
  This is the same order as `reach: lan | tailnet | public`, and the same order
  of risk — which is why the outer ring is the warning colour.
- **The gap is deliberate.** The arcs stop at 270°, and the notch is squared off
  against the left and bottom edges so it reads as a corner — the `L` of
  localshare, and a reminder that a share is scoped, not broadcast everywhere.

Geometry lives in `tokens.json` under `geometry` if you need to redraw it: 64
unit box, 5 unit stroke with round caps, dot radius 5, arc radii 11.5 / 19 /
26.5, each sweeping 270° with the gap centred at 135°.

## Colour

One colour per reach. These are semantic, not decorative — don't reassign them.

| Role | Light | Dark | Meaning |
| --- | --- | --- | --- |
| Ink | `#10162F` | `#F4F6FF` | The dot, wordmark, body text |
| Ink muted | `#5D6588` | `#9AA3C4` | `share` in the lockup, secondary text |
| Paper | `#FFFFFF` | `#0B0F1F` | Background |
| Reach: lan | `#12B886` | `#2AD8A4` | Unauthenticated, same network |
| Reach: tailnet | `#5B7CFA` | `#8098FF` | Default reach, your devices only |
| Reach: public | `#F59F0A` | `#FFB733` | Funnel — needs two gates, so it warns |
| Reach: off | ink at 16% | ink at 20% | Shareable but not shared |

The dark column is the same hue lifted for contrast on ink; it is not a different
palette. `tokens.css` ships both with a `prefers-color-scheme` switch, and
`tokens.json` has the raw values.

## Files

| File | Use it for |
| --- | --- |
| `logo.svg` | Default. Anything on a light background. |
| `logo-dark.svg` | Dark backgrounds. Lifted arc colours, light dot. |
| `logo-mono.svg` | One colour. Strokes inherit `currentColor` when inlined, so it adapts; standalone it renders black. |
| `logo-badge.svg` | Avatars, app and dock icons, favicons that need a filled tile. Mark reversed on an ink rounded square. |
| `logo-lockup.svg` | Mark plus wordmark, horizontal. |
| `logo-lockup-dark.svg` | Lockup on dark backgrounds. |
| `logo-lockup-mono.svg` | Lockup in one colour. |
| `favicon.svg` | 16–24px only. See below. |
| `favicon.ico` | Legacy browsers. Contains 16, 32 and 48px. |
| `states/reach-*.svg` | Status indicators in docs and UI: the active ring is coloured, the rest fade to the off colour. The dot and faded rings use `currentColor`, so inlined they follow the surrounding text. |
| `png/` | Generated. For anywhere SVG isn't an option. |

`favicon.svg` is a **two-ring** simplification, with a bigger dot and a heavier
stroke. Three rings at 16px close their own gaps and turn into a coloured blob.
Use it small; use `logo.svg` everywhere else.

## Clear space and minimum size

Keep clear space of at least the dot's diameter (5 units, ~8% of the box) on all
four sides. The mark already carries 3 units of padding inside its viewBox, so
don't crop to the strokes.

Minimum sizes: `logo.svg` at 24px, `favicon.svg` at 16px, `logo-lockup.svg` at
120px wide. Below those, use the badge or the favicon.

## Wordmark

Set as **`localshare`** — one word, always lowercase, even at the start of a
sentence. Never `LocalShare`, `Localshare`, or `local-share`.

The lockup uses live `<text>`, not outlines, in a system UI sans
(SF Pro / Segoe UI / Inter) at weight 650 with `-0.8` tracking. That keeps the
file editable and tiny, but it renders differently where those fonts are
missing, and the viewBox carries slack for wider fallbacks. When you need the
lockup to be pixel-identical everywhere, use `png/logo-lockup-*.png`, or place
`logo.svg` next to live HTML text.

## Don't

- Don't recolour the arcs, reorder them, or drop only the middle one — the ring
  order carries meaning.
- Don't close the gap into full circles, or rotate it away from the bottom left.
- Don't add gradients, shadows, glows, or outlines.
- Don't stretch. Scale uniformly.
- Don't put the light mark on a mid-tone photo or colour; use the badge.
- Don't rebuild the wordmark in a display, serif, or monospace face.

## Regenerating the PNGs

The SVGs are the source of truth. `png/` and `favicon.ico` are generated:

```bash
python3 brand/build.py
```

macOS only, and it needs Chrome — it's the renderer available here that both
honours `stroke-linecap` and keeps the background transparent. ImageMagick's
internal SVG renderer squares off the arc caps and fills the gaps; QuickLook
flattens onto white. ImageMagick is still used, from raster input only, to pack
`favicon.ico`. Edit an SVG, rerun, commit the result.
