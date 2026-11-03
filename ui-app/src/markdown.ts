/**
 * Lightweight markdown-to-HTML converter for tool output.
 * Handles headings, bold, code, lists, tables, blockquotes, and severity icons.
 */

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function markdownToHtml(md: string): string {
  if (!md) return "";

  // Normalize CRLF to LF so table/blockquote regexes match consistently
  md = md.replace(/\r\n/g, "\n");

  // Escape HTML first to prevent XSS from tool output
  let html = escapeHtml(md);

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

  return html;
}
