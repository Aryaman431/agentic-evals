# DeepAgentLabs · Use Case Hub

A single static landing page that presents three DeepAgentLabs engineering use cases —
chatbot evaluation, voice-agent testing, and turning a production trace into a release
decision. Semantic HTML, one stylesheet, zero JavaScript, and no third-party resources —
open it locally or publish it to any static host.

## What this is

- **A hub, not an app.** Three case panels, each linking out to a use case in a new tab.
- **Zero-JS by design.** There is intentionally **no `script.js`** and no `<script>`
  element anywhere in `index.html`. The mobile menu is a native `<details>/<summary>`
  disclosure; navigation is plain anchors. The page works with JavaScript disabled.
- **Self-contained.** No images, no web fonts, no CDN, no `@import`, and no `http(s)`
  URLs in the stylesheet. The only graphics are four inline SVG diagrams (one in the
  hero, one per case). The only outbound URLs are the three use-case links and the
  header's GitHub link.

## Files

| File         | Purpose |
| ------------ | ------- |
| `index.html` | Semantic page: skip link, sticky header (desktop nav + `details/summary` drawer), two-column hero with the Fig. 00 schematic, `#use-cases` with three case panels (Figs. 01–03), footer with rev meta. Four inline SVGs total. The URL CONFIGURATION comment is the first child of `<head>`. |
| `styles.css` | Editorial dark design system: near-black green-charcoal palette with acid-lime and mint accents, system fonts, responsive 3→2→1 case grid, reduced-motion support. |
| `README.md`  | This file. |

There is intentionally **no `script.js`** — do not add one. If you need behavior, prefer
progressive enhancement that degrades to the current static page.

## Local preview

Opening `index.html` directly via `file://` works — there are no fetches or module
imports. For a local server, from this directory:

```bash
# Python 3
python -m http.server 8000

# Windows, if `python` is not on PATH
py -m http.server 8000
```

Then open <http://localhost:8000/> in a browser.

## Deploy

This folder is the whole site. Publish the **contents** of `usecase-hub` (not its parent)
to any static host:

- **GitHub Pages** — publish the `usecase-hub` folder (or the branch/root that contains it).
- **Netlify / Vercel / Cloudflare Pages** — set the publish directory to `usecase-hub`;
  no build command is required.
- **Any web server / S3** — copy `index.html` and `styles.css` to the web root or a
  subpath. The stylesheet is referenced relatively (`styles.css`), so subpath hosting
  works without edits.

No environment variables, no build step, no server-side code.

## Link configuration

The single source of truth for the three **card** URLs is the **URL CONFIGURATION comment
block** at the top of `index.html` `<head>`. Current targets:

| Card / Nav | Title                                     | URL                                                       | Status |
| ---------- | ----------------------------------------- | --------------------------------------------------------- | ------ |
| uc-01 | Chatbot Evaluation                       | `https://deepagentlabs.io/agentic-evals/`                 | VERIFIED (HTTP 200, checked 2026-10-21) |
| uc-02 | Voice Agent Evaluation                   | `https://agentic-evals-api.onrender.com/`                 | [PLACEHOLDER — UNVERIFIED] (404; PROD_API_BASE from `agentic-evals-pr/voice-agent-evals/config.js`; likely the Evaluation API root, not the dashboard UI) |
| uc-03 | From Production Trace to Release Decision | `https://production-trace-release-decision.onrender.com/` | [PLACEHOLDER — UNVERIFIED] (404; derived from `SERVICE` in `usecase3/app.py`) |
| Nav   | GitHub — `DeepAgentLabs/agentic-evals`   | `https://github.com/DeepAgentLabs/agentic-evals`          | VERIFIED (public repo, checked 2026-10-21) |

The GitHub link is not part of the card URL CONFIG block; it appears twice in the header
(desktop list and drawer), each with `target="_blank" rel="noopener noreferrer"` and a
unique `aria-label`.

### Mirrored URL CONFIGURATION block

Reproduced from `index.html`; the two unverified status markers are shown as
`[UNVERIFIED]` in this copy so the literal placeholder token appears only in the
table above.

```text
============================================================
URL CONFIGURATION — single source of truth for outbound links.
To re-point a card, edit the matching href in the <article>
below. Keep target="_blank" and rel="noopener noreferrer" on
every CTA, and give each CTA a unique aria-label.
Verification statuses are recorded inline below.
------------------------------------------------------------
uc-01 · Chatbot Evaluation
  href: https://deepagentlabs.io/agentic-evals/
  Status: VERIFIED (HTTP 200, checked 2026-10-21)
uc-02 · Voice Agent Evaluation
  href: https://agentic-evals-api.onrender.com/
  Status: [UNVERIFIED] Returns 404. Value = PROD_API_BASE in agentic-evals-pr/voice-agent-evals/config.js (Evaluation API root; the public dashboard may instead live on GitHub Pages — confirm before launch).
uc-03 · From Production Trace to Release Decision
  href: https://production-trace-release-decision.onrender.com/
  Status: [UNVERIFIED] Returns 404. Derived from SERVICE = "production-trace-release-decision" in usecase3/app.py. Replace when a public URL exists.
```

### Replacing a placeholder URL

To re-point a card, edit **both** places in `index.html`:

1. The status/href line in the URL CONFIGURATION comment block at the top of `<head>`.
2. The single matching `<a class="case-cta" href="…">` inside `<article id="uc-0N">`.

Then keep this README in sync (the table above and the mirrored block). Keep
`target="_blank"` and `rel="noopener noreferrer"` on every CTA, and keep each `aria-label`
unique (each currently embeds the card title).

## Placeholder warning

**uc-02 and uc-03 are placeholders — both URLs currently return HTTP 404. Do not treat
them as live.**

- **uc-02** — `https://agentic-evals-api.onrender.com/` is the `PROD_API_BASE` value in
  `agentic-evals-pr/voice-agent-evals/config.js` (the Evaluation API root). The public
  dashboard may instead live on GitHub Pages — confirm the intended destination before
  launch.
- **uc-03** — `https://production-trace-release-decision.onrender.com/` is derived from
  `SERVICE = "production-trace-release-decision"` in `usecase3/app.py`. Replace it when a
  public URL exists.

uc-01 (`https://deepagentlabs.io/agentic-evals/`) and the header's GitHub nav link
(`https://github.com/DeepAgentLabs/agentic-evals`) are the only verified links
(checked 2026-10-21).

## Design notes

- **Palette:** background `#0A0F0E`; raised `#0D1312`; surfaces `#111917` / `#15201D`;
  borders `#283631` / `#3A4C44`; text `#F0F0E8` with muted `#9FADA5` and dim `#7B8C84`;
  acid-lime accent `#B8F34A` (hover `#C8FF5E`) on ink `#0A0F0E`; mint secondary
  `#5CD6B8`. Lime is rationed — the hero CTA (the only solid-lime surface on the page),
  diagram status dots, the card hover accent line, and focus outlines.
- **Type:** system sans (max weight 700) for headings and body copy; Georgia-class serif
  italic for editorial emphasis (`.serif-em`, with a lime highlight bar behind the
  emphasized words); system mono for eyebrows, labels, nav, footer meta, and diagram
  text. No web fonts.
- **Layout:** sticky translucent, blurred header; content capped at 1160px; two-column
  hero (7fr / 5fr) that stacks at ≤860px; hero figure sits on a fine 32px grid with
  corner coordinate marks (hidden at ≤480px); case panels carry mono outline index
  numerals and sit in a 3-column grid → 2 at ≤1024px (`uc-03` spans full width) → 1 at
  ≤640px. Anchors carry `scroll-margin-top: 76px` so jumps clear the sticky header.
- **Interaction:** no hover lift. Case panels reveal a 2px lime top accent line that
  scales in from the left, with a stronger border and surface; ghost CTAs turn lime;
  the hero CTA lightens. All transitions are disabled under `prefers-reduced-motion`,
  which also disables smooth scrolling.
- **Diagrams:** four original inline SVGs — hero evaluation-layer schematic (Fig. 00)
  and one per case: Fig. 01 mini conversation with four constraint chips, Fig. 02
  speech-to-response pipeline with a fault-injection band, Fig. 03 trace timeline →
  baseline-vs-replay → three verdicts.
- **Constraints honored:** no images, no external assets, no `@import`, no `http` URLs in
  CSS, no third-party resources.

## Accessibility notes

- Skip link (`Skip to use cases`) is the first focusable element and targets `#use-cases`.
- Landmarks: `header`, labelled `nav` ("Primary"), `main`, `section` labelled via
  `aria-labelledby`, one `article` per case, `footer`.
- The mobile menu is a native `<details>/<summary>` disclosure — keyboard-operable with
  no script. Per native browser behavior, Escape does not close the open drawer.
- Every card CTA has a unique `aria-label` that includes the card title and states that
  it opens in a new tab; all CTAs use `target="_blank" rel="noopener noreferrer"`. The
  GitHub nav link follows the same convention.
- Each of the four SVGs is `role="img"` with a `<title>` and `<desc>` wired via
  `aria-labelledby`; decorative marks (arrows, coordinate labels, section marks) are
  `aria-hidden`.
- Visible `:focus-visible` outlines use the lime accent.
- `prefers-reduced-motion: reduce` removes transitions and smooth scrolling.
- Light and muted text sit on dark surfaces; the hero CTA uses dark ink on the lime fill.

## Verification checklist

- [x] `index.html` contains zero script elements (no `script.js`, no inline scripts).
- [x] URL CONFIGURATION comment block is the first child of `<head>`.
- [x] Hero `h1` text reads exactly: `Evaluating AI agents takes more than a successful response.`
- [x] `#use-cases` contains three `<article>` panels with ids `uc-01`, `uc-02`, `uc-03`;
      each has a unique inline SVG diagram (Fig. 01–03), plus the hero Fig. 00.
- [x] Each card CTA has `target="_blank"`, `rel="noopener noreferrer"`, and a unique
      `aria-label`; the header GitHub link does too.
- [x] The three card hrefs are distinct and match the Link configuration table; the
      GitHub nav link (`https://github.com/DeepAgentLabs/agentic-evals`) is verified.
- [x] Exactly two placeholder markers in this README (the uc-02 and uc-03 table rows);
      uc-01 and the GitHub nav link are verified.
- [x] `styles.css` matches the documented palette; 3→2→1 grid at 1024px / 640px; nav and
      hero collapse at 860px; coordinate marks hidden ≤480px; lime top accent line on
      hover (no lift); `:focus-visible` outlines; `prefers-reduced-motion` block;
      no `@import`, no `http` URLs.
- [x] `usecase-hub/` contains only `index.html`, `styles.css`, and `README.md`; no
      images, no third-party resources, no build step.

## License

MIT License — free to use, copy, modify, and distribute; provided "as is", without warranty.
