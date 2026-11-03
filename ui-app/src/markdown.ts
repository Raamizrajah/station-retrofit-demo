/**
 * Lightweight markdown-to-HTML converter for tool output.
 * Handles headings, bold, code, lists, tables, blockquotes, severity icons,
 * and Mermaid diagrams (rendered to SVG via the mermaid library).
 */

import mermaid from "mermaid";

// Initialize mermaid once — no auto-start, we render on demand
mermaid.initialize({
  startOnLoad: false,
  theme: "default",
  securityLevel: "loose",
  flowchart: { useMaxWidth: true, htmlLabels: true },
});

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Extract ```mermaid ... ``` blocks BEFORE HTML-escaping (arrows use > and ").
 * Returns the markdown with mermaid blocks replaced by placeholders,
 * plus a map of placeholder → raw mermaid source.
 */
function extractMermaidBlocks(md: string): {
  md: string;
  blocks: Map<string, string>;
} {
  const blocks = new Map<string, string>();
  let idx = 0;
  const replaced = md.replace(
    /```mermaid\s*\n([\s\S]*?)```/g,
    (_match, code: string) => {
      const id = `__MERMAID_${idx++}__`;
      blocks.set(id, code.trim());
      return id;
    },
  );
  return { md: replaced, blocks };
}

export function markdownToHtml(md: string): string {
  if (!md) return "";

  // Normalize CRLF to LF so table/blockquote regexes match consistently
  md = md.replace(/\r\n/g, "\n");

  // Pull out mermaid blocks before escaping
  const { md: safeMd, blocks } = extractMermaidBlocks(md);

  // Escape HTML first to prevent XSS from tool output
  let html = escapeHtml(safeMd);

  // Tables: header | sep | rows
  html = html.replace(
    /^(\|.+\|)\n(\|[-| :]+\|)\n((?:\|.+\|\n?)*)/gm,
    (_match, header: string, _sep: string, body: string) => {
      const ths = header
        .split("|")
        .filter((c: string) => c.trim())
        .map((c: string) => `<th>${c.trim()}</th>`)
        .join("");
      const rows = body
        .trim()
        .split("\n")
        .map((row: string) => {
          const tds = row
            .split("|")
            .filter((c: string) => c.trim())
            .map((c: string) => `<td>${c.trim()}</td>`)
            .join("");
          return `<tr>${tds}</tr>`;
        })
        .join("");
      return `<table><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
    },
  );

  // Generic code blocks: ```lang ... ```
  html = html.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    (_match, lang: string, code: string) =>
      `<pre><code class="language-${lang || "text"}">${code.trim()}</code></pre>`,
  );

  html = html
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(
      /`([^`]+)`/g,
      "<code>$1</code>",
    )
    .replace(/^- /gm, "• ")
    .replace(
      /^&gt; (.+)$/gm,
      "<blockquote>$1</blockquote>",
    )
    .replace(/\n/g, "<br/>");

  // Re-inject mermaid blocks as placeholder divs (rendered after DOM insertion)
  for (const [id, _code] of blocks) {
    html = html.replace(
      id,
      `<div class="mermaid-placeholder" data-mermaid-id="${id}"></div>`,
    );
  }

  return html;
}

/**
 * Store for mermaid source blocks from the last markdownToHtml call.
 * Components call renderMermaidBlocks() after the HTML is in the DOM.
 */
let pendingBlocks = new Map<string, string>();

/** Variant that also stashes mermaid blocks for later rendering. */
export function markdownToHtmlWithMermaid(md: string): string {
  if (!md) return "";

  md = md.replace(/\r\n/g, "\n");
  const { md: safeMd, blocks } = extractMermaidBlocks(md);
  pendingBlocks = blocks;

  let html = escapeHtml(safeMd);

  // Tables
  html = html.replace(
    /^(\|.+\|)\n(\|[-| :]+\|)\n((?:\|.+\|\n?)*)/gm,
    (_match, header: string, _sep: string, body: string) => {
      const ths = header
        .split("|")
        .filter((c: string) => c.trim())
        .map((c: string) => `<th>${c.trim()}</th>`)
        .join("");
      const rows = body
        .trim()
        .split("\n")
        .map((row: string) => {
          const tds = row
            .split("|")
            .filter((c: string) => c.trim())
            .map((c: string) => `<td>${c.trim()}</td>`)
            .join("");
          return `<tr>${tds}</tr>`;
        })
        .join("");
      return `<table><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
    },
  );

  // Generic code blocks
  html = html.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    (_match, lang: string, code: string) =>
      `<pre><code class="language-${lang || "text"}">${code.trim()}</code></pre>`,
  );

  html = html
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^- /gm, "• ")
    .replace(/^&gt; (.+)$/gm, "<blockquote>$1</blockquote>")
    .replace(/\n/g, "<br/>");

  // Inject mermaid placeholder divs
  for (const [id, _code] of blocks) {
    html = html.replace(
      id,
      `<div class="mermaid-diagram" data-mermaid-id="${id}"></div>`,
    );
  }

  return html;
}

/** Render all pending mermaid diagrams into their placeholder divs. */
export async function renderMermaidBlocks(): Promise<void> {
  for (const [id, code] of pendingBlocks) {
    const el = document.querySelector(`[data-mermaid-id="${id}"]`);
    if (!el) continue;
    try {
      const { svg } = await mermaid.render(`mermaid-${id}`, code);
      el.innerHTML = svg;
      el.classList.add("mermaid-rendered");
    } catch (err) {
      // Show the raw source on render failure so user can debug
      el.innerHTML = `<pre class="mermaid-error"><code>${escapeHtml(code)}</code></pre>`;
      el.classList.add("mermaid-error-container");
      console.warn("Mermaid render failed:", err);
    }
  }
  pendingBlocks.clear();
}
