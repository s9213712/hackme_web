'use strict';

const MARKDOWN_ACTIONS = [
  ["bold", "粗體", "**", "**"],
  ["italic", "斜體", "*", "*"],
  ["code", "程式碼", "`", "`"],
  ["quote", "引用", "> ", ""],
  ["link", "連結", "[", "](https://example.com)"],
];

function markdownToSafeHtml(input) {
  let html = sanitize(input || "");
  html = html.replace(/^### (.*)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.*)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.*)$/gm, "<h1>$1</h1>");
  html = html.replace(/^&gt; (.*)$/gm, "<blockquote>$1</blockquote>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/`(.+?)`/g, "<code>$1</code>");
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return html.split(/\n{2,}/).map((block) => {
    if (/^<(h1|h2|h3|blockquote)/.test(block)) return block.replace(/\n/g, "<br>");
    return `<p>${block.replace(/\n/g, "<br>")}</p>`;
  }).join("");
}

function insertMarkdown(textarea, before, after) {
  const start = textarea.selectionStart || 0;
  const end = textarea.selectionEnd || 0;
  const selected = textarea.value.slice(start, end) || "文字";
  const next = textarea.value.slice(0, start) + before + selected + after + textarea.value.slice(end);
  textarea.value = next;
  const cursor = start + before.length + selected.length + after.length;
  textarea.focus();
  textarea.setSelectionRange(cursor, cursor);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function attachMarkdownEditor(textarea) {
  if (!textarea || textarea.dataset.markdownReady === "1") return;
  textarea.dataset.markdownReady = "1";
  const toolbar = document.createElement("div");
  toolbar.className = "markdown-toolbar";
  MARKDOWN_ACTIONS.forEach(([, label, before, after]) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn";
    btn.textContent = label;
    btn.addEventListener("click", () => insertMarkdown(textarea, before, after));
    toolbar.appendChild(btn);
  });
  const previewBtn = document.createElement("button");
  previewBtn.type = "button";
  previewBtn.className = "btn";
  previewBtn.textContent = "預覽";
  toolbar.appendChild(previewBtn);

  const preview = document.createElement("div");
  preview.className = "markdown-preview";
  previewBtn.addEventListener("click", () => {
    preview.classList.toggle("show");
    preview.innerHTML = markdownToSafeHtml(textarea.value || "");
  });
  textarea.addEventListener("input", () => {
    if (preview.classList.contains("show")) preview.innerHTML = markdownToSafeHtml(textarea.value || "");
  });

  textarea.parentNode.insertBefore(toolbar, textarea);
  textarea.parentNode.insertBefore(preview, textarea.nextSibling);
}

function initMarkdownEditors() {
  document.querySelectorAll("textarea[data-markdown-editor]").forEach(attachMarkdownEditor);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initMarkdownEditors);
} else {
  initMarkdownEditors();
}
