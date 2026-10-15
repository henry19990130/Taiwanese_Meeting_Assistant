function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isTableSep(cells) {
  return cells.length > 0 && cells.every((cell) => /^:?-+:?$/.test(cell));
}

function splitRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderTable(rows) {
  const parsed = rows.map(splitRow).filter((cells) => !isTableSep(cells));
  if (!parsed.length) {
    return "";
  }
  const [head, ...body] = parsed;
  const thead = `<thead><tr>${head.map((cell) => `<th>${escapeHtml(cell)}</th>`).join("")}</tr></thead>`;
  const tbody = body.length
    ? `<tbody>${body.map((cells) => `<tr>${cells.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody>`
    : "";
  return `<table>${thead}${tbody}</table>`;
}

export function renderMarkdown(source) {
  const text = String(source || "").replace(/\r\n/g, "\n").trim();
  if (!text) {
    return "";
  }
  const lines = text.split("\n");
  const html = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (line.startsWith("## ")) {
      html.push(`<h2>${escapeHtml(line.slice(3).trim())}</h2>`);
      index += 1;
      continue;
    }
    if (line.startsWith("# ")) {
      html.push(`<h1>${escapeHtml(line.slice(2).trim())}</h1>`);
      index += 1;
      continue;
    }
    if (line.trim().startsWith("|")) {
      const rows = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        rows.push(lines[index]);
        index += 1;
      }
      html.push(renderTable(rows));
      continue;
    }
    if (/^\s*[-*] /.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*[-*] /.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*] /, ""));
        index += 1;
      }
      html.push(`<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`);
      continue;
    }
    const block = [line];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !lines[index].startsWith("#")
      && !lines[index].trim().startsWith("|")
      && !/^\s*[-*] /.test(lines[index])
    ) {
      block.push(lines[index]);
      index += 1;
    }
    html.push(`<p>${block.map((item) => escapeHtml(item)).join("<br>")}</p>`);
  }
  return html.join("");
}
