'use strict';

const MARKDOWN_ACTIONS = [
  ["bold", "粗體", "**", "**"],
  ["italic", "斜體", "*", "*"],
  ["code", "程式碼", "`", "`"],
  ["quote", "引用", "> ", ""],
  ["link", "連結", "[", "](https://example.com)"],
];

const MARKDOWN_COMMUNITY_MEDIA_RE = /\[\[community-media:(image|video|audio|file):([A-Za-z0-9_-]+)(?:\|([^\]\n]{0,160}))?\]\]/g;
const MARKDOWN_COMFYUI_IMAGE_RE = /\[\[comfyui-image:([A-Za-z0-9_-]+)\]\]/g;

function markdownCommunityMediaHtml(kind, token, name = "") {
  const mediaKind = ["image", "video", "audio", "file"].includes(kind) ? kind : "file";
  const safeToken = String(token || "").match(/^[A-Za-z0-9_-]+$/) ? String(token) : "";
  if (!safeToken) return "";
  const safeName = sanitize(name || "討論區媒體");
  const contentUrl = `/api/storage/shared/${encodeURIComponent(safeToken)}/preview/content`;
  const pageUrl = `/shared/files/${encodeURIComponent(safeToken)}`;
  if (mediaKind === "image") {
    return `<figure class="community-inline-media community-inline-media-image"><img src="${sanitize(contentUrl)}" alt="${safeName}" loading="lazy" /><figcaption>${safeName}</figcaption></figure>`;
  }
  if (mediaKind === "video") {
    return `<figure class="community-inline-media community-inline-media-video"><video src="${sanitize(contentUrl)}" controls preload="metadata"></video><figcaption>${safeName}</figcaption></figure>`;
  }
  if (mediaKind === "audio") {
    return `<figure class="community-inline-media community-inline-media-audio"><audio src="${sanitize(contentUrl)}" controls preload="metadata"></audio><figcaption>${safeName}</figcaption></figure>`;
  }
  return `<figure class="community-inline-media community-inline-media-file"><a href="${sanitize(pageUrl)}" target="_blank" rel="noopener noreferrer">${safeName}</a></figure>`;
}

function markdownComfyuiImageHtml(fileId) {
  const safeFileId = String(fileId || "").match(/^[A-Za-z0-9_-]+$/) ? String(fileId) : "";
  if (!safeFileId) return "";
  const contentUrl = `/api/cloud-drive/files/${encodeURIComponent(safeFileId)}/preview/content`;
  return `<figure class="community-inline-media community-inline-media-image"><img src="${sanitize(contentUrl)}" alt="ComfyUI shared image" loading="lazy" /><figcaption>ComfyUI image</figcaption></figure>`;
}

function markdownToSafeHtml(input) {
  const links = [];
  const media = [];
  const protectedMediaText = String(input || "")
    .replace(MARKDOWN_COMMUNITY_MEDIA_RE, (_token, kind, token, name) => {
      const marker = `@@MD_MEDIA_${media.length}@@`;
      media.push(markdownCommunityMediaHtml(kind, token, name));
      return `\n\n${marker}\n\n`;
    })
    .replace(MARKDOWN_COMFYUI_IMAGE_RE, (_token, fileId) => {
      const marker = `@@MD_MEDIA_${media.length}@@`;
      media.push(markdownComfyuiImageHtml(fileId));
      return `\n\n${marker}\n\n`;
    });
  const protectedText = protectedMediaText.replace(/\[([^\]]{1,120})\]\((https?:\/\/[^\s)]+)\)/g, (_, text, url) => {
    let parsed;
    try {
      parsed = new URL(url);
    } catch (_err) {
      return `[${text}](${url})`;
    }
    if (!["http:", "https:"].includes(parsed.protocol)) return `[${text}](${url})`;
    const token = `@@MD_LINK_${links.length}@@`;
    links.push(`<a href="${sanitize(parsed.href)}" target="_blank" rel="noopener noreferrer">${sanitize(text)}</a>`);
    return token;
  });
  let html = sanitize(protectedText);
  html = html.replace(/^### (.*)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.*)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.*)$/gm, "<h1>$1</h1>");
  html = html.replace(/^&gt; (.*)$/gm, "<blockquote>$1</blockquote>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/`(.+?)`/g, "<code>$1</code>");
  links.forEach((link, index) => {
    html = html.replace(`@@MD_LINK_${index}@@`, link);
  });
  media.forEach((item, index) => {
    html = html.replace(`@@MD_MEDIA_${index}@@`, item);
  });
  return html.split(/\n{2,}/).map((block) => {
    const trimmed = block.trim();
    if (!trimmed) return "";
    if (/^<(h1|h2|h3|blockquote|figure)/.test(trimmed)) return trimmed.replace(/\n/g, "<br>");
    return `<p>${block.replace(/\n/g, "<br>")}</p>`;
  }).filter(Boolean).join("");
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
