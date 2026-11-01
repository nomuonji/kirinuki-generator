# Shorts design templates

![The five templates](templates.jpg)

Every clip is rendered with one of five templates so that consecutive uploads don't share a
single visual identity. Each template is a different editorial concept, not a recolour:

| id | concept | headline | how subtitles appear | punchline | reaction |
|---|---|---|---|---|---|
| `gougai` | 号外 / newspaper page | Shippori Mincho with 傍点 on emphasised words | photo caption (▲) | pull quote 「要点」 | editor's stamp 「注」 |
| `terminal` | 発言ログ / debate console | "Q." + Noto Sans JP, emphasis as highlighted blocks | typed-in log line with cursor | `// 結論` panel | `[comment]` log chip |
| `pop` | 雑誌表紙 / pop magazine cover | Dela Gothic One, emphasis in outlined hot colour | heavy outlined manga caption | black speech bubble | starburst sticker |
| `cinema` | シネマ / quiet film | Zen Kaku Gothic, blur-in | boxless, centred | quoted line in 「」 | translucent pill |
| `note` | ノート / study notebook | Yusei Magic with a highlighter swipe | written under a taped photo | sticky note "POINT!" | handwritten slip |

Each template also has 2–3 colour variants, and small per-clip differences (tilt direction,
paper/grain pattern) come from `designSeed`.

## Rotation

`packages/design_rotation.py` picks a template per clip, least-recently-used first:

- the same template is never used twice in a row;
- all five are used before any repeats, in a seeded order per cycle (no fixed A→B→C→D→E pattern);
- colour variants rotate the same way inside each template.

The direct lane passes the designs of previous uploads from the `kirinuki-state` ledger
(`KIRINUKI_DESIGN_HISTORY`) and records each clip's design in the ledger (`design` field), so the
rotation continues across runs. Lanes without a ledger still rotate within each run.

`KIRINUKI_DESIGN_TEMPLATE=<id>[:<variant>]` pins every clip to one design (useful for previews).

## Layout rules shared by all templates

- Readable text stays inside the Shorts-safe box (`SAFE` in `shared.tsx`): nothing important
  below y≈1615 or under the right-hand button column, where the YouTube player draws its UI.
- The headline is fully readable on frame 0; entrance animations never start from blank.
- Japanese text uses phrase-aware line breaking (`word-break: auto-phrase`), so words like
  結婚 or ひろゆき are not split across lines, and font sizes are fitted to the box.
- Fonts are bundled (Fontsource) and frames wait for the exact glyphs they need.
- No per-frame noise: animated grain wrecks compression after YouTube's re-encode.

## Adding a template

1. Add `apps/remotion/src/design/templates/<Name>.tsx` exporting the component and a `PALETTES`
   array, and register it in `registry.ts`.
2. Add the same id and palette count to `TEMPLATE_VARIANTS` in `packages/design_rotation.py`
   (`tests/test_design_rotation.py` fails if the two disagree).
3. Never rename an existing id: it's stored in the publish ledger.
