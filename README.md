# DeepAgentLabs · Agentic Evals

Static site for **Agentic Evals**: the DeepAgentLabs-standard product landing page
(`index.html`), a docs page with fuller quickstart variants (`docs/`), a blog
(`blog/`), and three use-case projects the landing page links to — chatbot
evaluation, voice-agent evaluation, and turning a production trace into a
release decision.

## What this is

- **A product landing page, not a hub.** `index.html` follows the shared
  DeepAgentLabs website standard: a hero with an interactive simulation, then
  *Why it matters*, *How it works*, *Capabilities*, *Quickstart*, *Use cases*,
  and a closing CTA marked `Maturity · Beta`.
- **Shared standard assets plus one local stylesheet.** The landing and docs
  pages load shared DeepAgentLabs CSS and JS from the DeepAgentLabs CDN — the
  CDN scripts drive the interactive simulation — with `site.css` holding
  page-specific tweaks only. The landing page is therefore **not**
  zero-JavaScript.
- **The blog stays static.** Every page under `blog/` is plain HTML with no
  scripts, styled by the shared `styles.css` (loaded as `../styles.css`).
- **Three use-case projects.** The use-cases section links to each project with
  a relative URL (`Chatbot-eval/index.html`, `voice-agent-evals/index.html`,
  `Production trace to release decision/index.html`) and to its article under
  `blog/`.

## Files

| File / folder | Purpose |
| ------------- | ------- |
| `index.html` | Product landing page: hero + interactive simulation, why it matters, how it works, capabilities, quickstart, use cases, closing CTA. Links the shared DeepAgentLabs CDN assets plus `site.css`. |
| `site.css` | Page-specific tweaks for `index.html` only — keep it small; it is not the design system. |
| `styles.css` | Shared editorial styling for the `blog/` pages (referenced as `../styles.css`). Still required — blog pages depend on it. |
| `docs/index.html` | Detailed quickstart variants (a suite with a release gate, an LLM judge) plus capability notes. |
| `blog/` | Article index and long-form articles; static HTML only. |
| `README.md` | This file. |

## Local preview

Opening the pages directly via `file://` works for relative navigation; the
landing and docs pages additionally need internet access for the shared
DeepAgentLabs CDN assets. For a local server, from this directory:

```bash
# Python 3
python -m http.server 8000

# Windows, if `python` is not on PATH
py -m http.server 8000
```

Then open <http://localhost:8000/> in a browser.

## Deploy

This folder is the whole site. Publish the **contents** of this directory (not
a subfolder) to any static host:

- **GitHub Pages** — publish this branch/root.
- **Netlify / Vercel / Cloudflare Pages** — set the publish directory to the
  repository root; no build command is required.
- **Any web server / S3** — copy the files to the web root or a subpath.
  Stylesheets are referenced relatively (`site.css`, `../styles.css`), so
  subpath hosting works without edits.

No build step and no environment variables for the static site. The use-case
projects may also ship optional Python backends with their own requirements;
those are separate from the static site.

Optional backends (defined in `render.yaml`):

- `agentic-evals-api` — voice-agent API (`voice-agent-evals/server.py`).
- `agentic-evals-chatbot-api` — chatbot API (`Chatbot-eval/server.py`, which adds `POST /chat/evaluate`).
- `production-trace-release-decision` — standalone Production Trace API (`Production trace to release decision/app.py`, with `rootDir` set to that folder).

Each use-case `config.js` selects the deployed backend automatically when served over HTTPS; override it with the `?api=` query param or `localStorage('evalApiBase')`.

## Links

The use-case cards on `index.html` use **relative** URLs:

| Card | Targets |
| ---- | ------- |
| Chatbot Evaluation | `Chatbot-eval/index.html` · `blog/chatbot-evaluation.html` |
| Voice Agent Evaluation | `voice-agent-evals/index.html` · `blog/voice-agent-evaluation.html` |
| Production Trace to Release Decision | `Production trace to release decision/index.html` · `blog/production-trace-release-decision.html` |

Header and footer links to DeepAgentLabs pages, GitHub and PyPI are absolute
external URLs. There is **no** "URL CONFIGURATION" comment block in
`index.html` — to re-point a card, edit its `<a href>` directly.

## Design and accessibility notes

- The landing and docs pages reuse the shared DeepAgentLabs product-page
  styles and scripts; `site.css` is intentionally tiny (page-specific tweaks
  only — new page styles belong there, not in `styles.css`).
- `styles.css` remains the editorial dark design system for `blog/`: system
  fonts, responsive layout, `prefers-reduced-motion` support, no external
  assets of its own.
- Both standard pages keep the usual affordances: a skip link to `#main`,
  labelled landmarks (`nav`, `main`, `section`), `aria-hidden` on decorative
  SVGs, visible `:focus-visible` outlines, and a nav toggle driven by
  `aria-expanded` / `aria-controls`.
- Blog pages are plain semantic HTML with no scripts.

## Verification checklist

- [ ] `index.html` loads the shared DeepAgentLabs CDN stylesheets and scripts
      plus `site.css`; it contains no "URL CONFIGURATION" comment.
- [ ] Use-case card hrefs are relative and match the Links table.
- [ ] Every page in `blog/` still references `../styles.css`.
- [ ] `docs/index.html` links back to `../index.html` and `../blog/index.html`.
- [ ] No build step and no environment variables for the static site.

## License

MIT License — free to use, copy, modify, and distribute; provided "as is", without warranty.
