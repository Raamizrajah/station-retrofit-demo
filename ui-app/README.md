# Station Retrofit UI

React + TypeScript + Vite frontend for the Station Retrofit brownfield toolkit.
Uses LEGO Connect design system components (`@lego/connect-components-react` v3.7.0).

> **Note:** The `@lego/connect-*` packages are hosted on LEGO's private npm registry. External contributors cannot run `npm install` in `ui-app/`, but the pre-built UI in `ui/dist/` works without it.

## Development

```bash
# From project root — install dependencies (loads GITHUB_TOKEN from .env)
./ui-app/setup.sh

cd ui-app
npm run dev      # Vite dev server with HMR
npm run build    # Build to ../ui/dist/ (served by Python server)
```

## Architecture

The UI is a single-page app with 8 tool panels ordered by brownfield lifecycle:

| Layer | Tabs |
|-------|------|
| **Understand** | Business Intel · Architecture · Scenario Plan |
| **Secure** | Secrets · Dependencies · Migrations |
| **Monitor** | Model Drift · Contract Drift |

### Key Components

- **Repo Picker** — filterable toggle chips with Select all / Deselect all. Type a keyword and press Enter to select only matching repos. All repos auto-discovered from sibling directories.
- **Tool Panels** — multi-repo checkbox grids (all pre-selected by default), focus area input, run button, and output display.
- **Output Display** — renders markdown with tables, code blocks, and **Mermaid diagrams as SVG** via the mermaid library.
- **Tone Selector** — header dropdown switches between Technical, Business, and Kid-friendly output styles.

### Files

| File | Purpose |
|------|---------|
| `src/App.tsx` | 8 tool panels, repo picker, tone selector, output display |
| `src/markdown.ts` | Markdown-to-HTML converter with Mermaid diagram rendering |
| `src/index.css` | Styles using LEGO Connect design tokens |

### How Mermaid Works

1. `markdownToHtmlWithMermaid()` extracts ` ```mermaid ``` ` blocks **before** HTML escaping (arrows use `>` and `"`)
2. Blocks replaced with `<div class="mermaid-diagram">` placeholders
3. After React inserts HTML into the DOM, `renderMermaidBlocks()` calls `mermaid.render()` to produce SVGs
4. On render failure, raw Mermaid source is shown so the user can debug

## Build Output

The build writes to `../ui/dist/` which the Python server (`ui/server.py`) serves as static files with SPA fallback.
