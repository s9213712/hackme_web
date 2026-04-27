function formatDriveBytes(bytes) {
  if (bytes === null || bytes === undefined) return "無上限";
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function renderDriveGroupedStats(targetId, grouped, emptyText) {
  const el = $(targetId);
  if (!el) return;
  const entries = Object.entries(grouped || {});
  if (!entries.length) {
    el.innerHTML = `<div class="drive-empty">${sanitize(emptyText || "尚無資料")}</div>`;
    return;
  }
  el.innerHTML = entries.map(([name, item]) => `
    <div class="drive-pill">
      <strong>${sanitize(name)}</strong>
      <span>${Number(item.count || 0)} 個 · ${formatDriveBytes(item.bytes || 0)}</span>
    </div>
  `).join("");
}

function renderDriveDashboard(payload) {
  const security = payload && payload.security ? payload.security : {};
  const quota = security.usage || (payload && payload.quota) || {};
  const used = Number(quota.used_bytes || 0);
  const total = quota.total_bytes;
  const remaining = quota.remaining_bytes;
  const percent = total === null || total === undefined ? 0 : Math.max(0, Math.min(100, Number(quota.percent_used || 0)));

  const usedLabel = $("drive-used-label");
  const totalLabel = $("drive-total-label");
  const remainingLabel = $("drive-remaining-label");
  const limitLabel = $("drive-limit-label");
  const barFill = $("drive-quota-bar-fill");

  if (usedLabel) usedLabel.textContent = formatDriveBytes(used);
  if (totalLabel) totalLabel.textContent = total === null || total === undefined ? " / 無上限" : ` / ${formatDriveBytes(total)}`;
  if (remainingLabel) remainingLabel.textContent = `剩餘容量：${formatDriveBytes(remaining)}`;
  if (limitLabel) {
    const maxFile = formatDriveBytes(quota.max_file_size_bytes);
    const daily = quota.upload_rate_limit_per_day === null || quota.upload_rate_limit_per_day === undefined ? "無上限" : `${quota.upload_rate_limit_per_day} 次`;
    limitLabel.textContent = `單檔限制：${maxFile} · 每日上傳：${daily} · 檔案數：${Number(quota.file_count || 0)}`;
  }
  if (barFill) {
    barFill.style.width = `${percent}%`;
    barFill.dataset.warning = percent >= 90 ? "high" : percent >= 70 ? "medium" : "low";
  }

  const list = $("drive-security-list");
  if (list) {
    const restrictions = Array.isArray(security.restrictions) ? security.restrictions : [];
    list.innerHTML = restrictions.length
      ? restrictions.map((item) => `<li>${sanitize(item)}</li>`).join("")
      : "<li>目前沒有額外限制</li>";
  }

  renderDriveGroupedStats("drive-risk-summary", quota.by_risk_level, "尚無風險統計");
  renderDriveGroupedStats("drive-scan-summary", quota.by_scan_status, "尚無掃描狀態");
  renderDriveGroupedStats("drive-mode-summary", quota.by_privacy_mode, "尚無隱私模式統計");
}

async function loadDriveDashboard() {
  if (!currentUser || !canAccessModule("privacy_uploads")) return;
  const msg = $("drive-msg");
  try {
    const res = await fetch(API + "/files/security-policy", { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      if (msg) flash(msg, json.msg || "雲端硬碟狀態讀取失敗", false);
      return;
    }
    renderDriveDashboard(json);
    if (msg) msg.className = "msg";
  } catch (err) {
    if (msg) flash(msg, "雲端硬碟狀態讀取失敗", false);
  }
}
