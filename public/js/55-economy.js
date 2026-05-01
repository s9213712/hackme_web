let economyLedgerOffset = 0;
let economyBlockCountdownTimer = null;
let economyBlockSchedule = null;
let economyInlineEventsBound = false;

function economySetMsg(text, ok = true) {
  const el = $("economy-msg");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = ok ? "#4caf50" : "#ff4f6d";
}

function economyRequestId(prefix = "economy") {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return `${prefix}:${window.crypto.randomUUID()}`;
  }
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
}

function formatPointsCurrency(currency) {
  return "點";
}

function formatEconomyCountdown(seconds) {
  const safe = Math.max(0, Number(seconds || 0));
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function stopEconomyBlockCountdown() {
  if (economyBlockCountdownTimer) {
    clearInterval(economyBlockCountdownTimer);
    economyBlockCountdownTimer = null;
  }
}

function canManageEconomyPoints() {
  return currentUser === "root" || currentRole === "manager" || currentRole === "super_admin";
}

function updateEconomyBlockCountdown() {
  const el = $("economy-chain-countdown");
  if (!el || !economyBlockSchedule) return;
  const unsealed = Number(economyBlockSchedule.unsealed_entries || 0);
  const threshold = Number(economyBlockSchedule.ledger_threshold || 10);
  if (economyBlockSchedule.mode === "hybrid" || economyBlockSchedule.mode === "ledger_count") {
    const remainingEntries = Math.max(0, threshold - unsealed);
    const target = economyBlockSchedule.nextSealAtMs || 0;
    const remainingSeconds = target ? Math.max(0, Math.ceil((target - Date.now()) / 1000)) : null;
    if (!unsealed) {
      el.textContent = `封塊進度：目前沒有未封 ledger；累積 ${threshold} 筆或最長等待 ${economyBlockSchedule.max_interval_minutes || "-"} 分鐘自動封塊`;
    } else if (remainingEntries) {
      const timeText = remainingSeconds === null ? "" : `，時間還剩 ${formatEconomyCountdown(remainingSeconds)}`;
      el.textContent = `封塊進度：${unsealed}/${threshold} 筆，還差 ${remainingEntries} 筆${timeText}`;
    } else {
      el.textContent = `封塊進度：${unsealed}/${threshold} 筆，可自動封塊`;
    }
    return;
  }
  const interval = Number(economyBlockSchedule.interval_minutes || 0);
  if (!unsealed) {
    el.textContent = `封塊倒數：目前沒有未封 ledger；設定為每 ${interval || "-"} 分鐘封塊一次`;
    return;
  }
  const target = economyBlockSchedule.nextSealAtMs || 0;
  const remaining = Math.max(0, Math.ceil((target - Date.now()) / 1000));
  el.textContent = remaining
    ? `封塊倒數：${formatEconomyCountdown(remaining)}（每 ${interval || "-"} 分鐘封塊一次）`
    : `封塊倒數：可封塊（每 ${interval || "-"} 分鐘封塊一次）`;
}

function startEconomyBlockCountdown(schedule) {
  stopEconomyBlockCountdown();
  economyBlockSchedule = null;
  if (!schedule) {
    const el = $("economy-chain-countdown");
    if (el) el.textContent = "封塊進度：-";
    return;
  }
  const nextMs = schedule.next_seal_at ? Date.parse(schedule.next_seal_at) : 0;
  economyBlockSchedule = { ...schedule, nextSealAtMs: Number.isFinite(nextMs) ? nextMs : 0 };
  updateEconomyBlockCountdown();
  economyBlockCountdownTimer = setInterval(updateEconomyBlockCountdown, 1000);
}

function renderEconomyWallet(wallet) {
  if (!wallet) return;
  const pointsBalance = wallet.points_balance !== undefined
    ? Number(wallet.points_balance || 0)
    : Number(wallet.soft_balance || 0) + Number(wallet.hard_balance || 0);
  const pointsFrozen = wallet.points_frozen !== undefined
    ? Number(wallet.points_frozen || 0)
    : Number(wallet.soft_frozen || 0) + Number(wallet.hard_frozen || 0);
  const pointsEarned = wallet.total_points_earned !== undefined
    ? Number(wallet.total_points_earned || 0)
    : Number(wallet.total_soft_earned || 0) + Number(wallet.total_hard_earned || 0);
  const pointsSpent = wallet.total_points_spent !== undefined
    ? Number(wallet.total_points_spent || 0)
    : Number(wallet.total_soft_spent || 0) + Number(wallet.total_hard_spent || 0);
  if ($("economy-points-balance")) $("economy-points-balance").textContent = String(pointsBalance);
  if ($("economy-points-frozen")) $("economy-points-frozen").textContent = `凍結 ${pointsFrozen}`;
  if ($("economy-points-earned")) $("economy-points-earned").textContent = `收入 ${pointsEarned}`;
  if ($("economy-points-spent")) $("economy-points-spent").textContent = `支出 ${pointsSpent}`;
  if ($("economy-soft-balance")) $("economy-soft-balance").textContent = String(pointsBalance);
  if ($("economy-hard-balance")) $("economy-hard-balance").textContent = "0";
  if ($("economy-soft-frozen")) $("economy-soft-frozen").textContent = `凍結 ${pointsFrozen}`;
  if ($("economy-hard-frozen")) $("economy-hard-frozen").textContent = "凍結 0";
  if ($("economy-wallet-status")) $("economy-wallet-status").textContent = wallet.wallet_status || "-";
  if ($("economy-public-account")) $("economy-public-account").textContent = wallet.public_account_id || "-";
  const sidebarPoints = $("sidebar-points");
  if (sidebarPoints) {
    sidebarPoints.dataset.points = String(pointsBalance);
    updateSidebarIdentity();
  }
}

function renderEconomyCatalog(items) {
  const list = $("economy-catalog-list");
  if (!list) return;
  if (!items || !items.length) {
    list.innerHTML = `<div class="drive-empty">尚無服務價格</div>`;
    return;
  }
  list.innerHTML = items.map((item) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(item.item_name || item.item_key)}</strong>
        <div class="drive-card-sub">${sanitize(item.category || "-")} · ${Number(item.base_price || 0)} ${formatPointsCurrency(item.currency_type)}</div>
      </div>
      <button class="btn" type="button" data-economy-spend="${sanitize(item.item_key)}">試扣</button>
    </div>
  `).join("");
  list.querySelectorAll("[data-economy-spend]").forEach((btn) => {
    btn.addEventListener("click", () => spendEconomyItem(btn.dataset.economySpend || ""));
  });
}

function renderEconomyLedger(rows, targetId = "economy-ledger-list") {
  const list = $(targetId);
  if (!list) return;
  if (!rows || !rows.length) {
    list.innerHTML = `<div class="drive-empty">尚無帳本紀錄</div>`;
    return;
  }
  list.innerHTML = rows.map((row) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(row.direction)} ${Number(row.amount || 0)} ${formatPointsCurrency(row.currency_type)}</strong>
        <div class="drive-card-sub">${sanitize(row.action_type || "-")} · ${sanitize(row.created_at || "")}</div>
        <div class="economy-ledger-hash">${sanitize(row.ledger_hash || "")}</div>
      </div>
      <button class="btn" type="button" data-economy-proof="${sanitize(row.ledger_uuid || "")}">Proof</button>
    </div>
  `).join("");
  list.querySelectorAll("[data-economy-proof]").forEach((btn) => {
    btn.addEventListener("click", () => loadEconomyProof(btn.dataset.economyProof || ""));
  });
}

function renderEconomyRootList(rows, targetId, emptyText, renderRow) {
  const list = $(targetId);
  if (!list) return;
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) {
    list.innerHTML = `<div class="drive-empty">${sanitize(emptyText)}</div>`;
    return;
  }
  list.innerHTML = safeRows.map(renderRow).join("");
}

function setEconomyChainStatus(text, ok = true) {
  const status = $("economy-chain-status");
  if (!status) return;
  status.textContent = text || "";
  status.className = ok ? "drive-card-sub economy-chain-status ok" : "drive-card-sub economy-chain-status err";
}

function formatEconomyVerificationSummary(verification) {
  const safe = verification && typeof verification === "object" ? verification : {};
  const counts = safe.counts && typeof safe.counts === "object" ? safe.counts : {};
  const state = safe.ok === true ? "全鏈驗證正常" : (safe.ok === false ? "全鏈驗證異常" : "全鏈狀態未知");
  return `${state}：${Number(counts.ledger_entries || 0)} 筆 ledger，${Number(counts.sealed_blocks || 0)} 個封塊，${Number(counts.unsealed_entries || 0)} 筆未封，${Number(counts.audit_events || 0)} 筆審計事件`;
}

function formatEconomyRecoveryResult(result) {
  const safe = result && typeof result === "object" ? result : {};
  const rebuild = safe.wallet_rebuild && typeof safe.wallet_rebuild === "object" ? safe.wallet_rebuild : {};
  const verification = safe.verification && typeof safe.verification === "object" ? safe.verification : {};
  const counts = verification.counts && typeof verification.counts === "object" ? verification.counts : {};
  if (safe.ok !== true) return safe.msg || "PointsChain 恢復失敗";
  return [
    "PointsChain 已恢復並完成驗證",
    `備份：${safe.backup_id || "-"}`,
    `錢包重建：${Number(rebuild.wallets_rebuilt || 0)} 個`,
    `ledger：${Number(counts.ledger_entries || 0)} 筆`,
    `封塊：${Number(counts.sealed_blocks || 0)} 個`,
    `safe mode：${(safe.recovery || {}).safe_mode ? "仍啟用" : "已解除"}`,
  ].join("；");
}

function renderEconomyRootReport(report) {
  const safeReport = report && typeof report === "object" ? report : {};
  const verification = safeReport.verification && typeof safeReport.verification === "object" ? safeReport.verification : {};
  const counts = verification.counts && typeof verification.counts === "object" ? verification.counts : {};
  if ($("economy-chain-ok")) {
    $("economy-chain-ok").textContent = verification.ok === true ? "完整" : (verification.ok === false ? "異常" : "未知");
  }
  if ($("economy-chain-counts")) $("economy-chain-counts").textContent = `${Number(counts.ledger_entries || 0)} 筆 ledger`;
  if ($("economy-chain-blocks")) $("economy-chain-blocks").textContent = String(counts.sealed_blocks || 0);
  if ($("economy-chain-unsealed")) $("economy-chain-unsealed").textContent = `未封 ${Number(counts.unsealed_entries || 0)}`;
  if ($("economy-chain-audit-count")) $("economy-chain-audit-count").textContent = String(counts.audit_events || 0);
  startEconomyBlockCountdown(safeReport.block_schedule || null);
  renderEconomyRecovery(safeReport.recovery || {}, safeReport.ledger_backups || []);
  renderEconomyRootList(safeReport.blocks, "economy-block-list", "尚無封塊", (block) => `
    <div class="drive-file-row">
      <div>
        <strong>#${Number(block.block_number || 0)} · ${Number(block.ledger_count || 0)} 筆</strong>
        <div class="drive-card-sub">${sanitize(block.sealed_at || "")} · ${sanitize(block.anchor_status || "local_only")} · ${sanitize(block.signature_algorithm || "unsigned")}</div>
        <div class="economy-ledger-hash">${sanitize(block.block_hash || "")}</div>
      </div>
    </div>
  `);
  renderEconomyRootList(safeReport.audit_logs, "economy-audit-list", "尚無審計事件", (row) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(row.event_type || "-")} · ${sanitize(row.severity || "-")}</strong>
        <div class="drive-card-sub">${sanitize(row.created_at || "")} · actor=${sanitize(row.actor_user_id || "-")} · target=${sanitize(row.target_user_id || "-")}</div>
        <div class="drive-card-sub">${sanitize(row.message || "")}</div>
      </div>
    </div>
  `);
  renderEconomyRootList(safeReport.high_risk_ledger, "economy-risk-ledger-list", "尚無異常帳本", (row) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(row.verification_status || row.status || "-")} · ${sanitize(row.direction)} ${Number(row.amount || 0)} ${formatPointsCurrency(row.currency_type)}</strong>
        <div class="drive-card-sub">ledger #${Number(row.id || 0)} · user ${Number(row.user_id || 0)} · ${sanitize(row.action_type || "-")} · risk=${sanitize(row.risk_flag || "none")}</div>
        ${(Array.isArray(row.verification_errors) ? row.verification_errors : []).map((issue) => `
          <div class="drive-card-sub">
            驗證異常：${sanitize(issue.type || "-")} · ${sanitize(issue.message || "")}
          </div>
          ${issue.expected_ledger_hash || issue.actual_ledger_hash ? `<div class="economy-ledger-hash">expected=${sanitize(issue.expected_ledger_hash || "-")} · actual=${sanitize(issue.actual_ledger_hash || "-")}</div>` : ""}
          ${issue.expected_previous_ledger_hash || issue.actual_previous_ledger_hash ? `<div class="economy-ledger-hash">prev expected=${sanitize(issue.expected_previous_ledger_hash || "-")} · prev actual=${sanitize(issue.actual_previous_ledger_hash || "-")}</div>` : ""}
        `).join("")}
        <div class="economy-ledger-hash">${sanitize(row.ledger_uuid || "")}</div>
      </div>
      <button class="btn" type="button" data-economy-proof="${sanitize(row.ledger_uuid || "")}">Proof</button>
    </div>
  `);
  const riskList = $("economy-risk-ledger-list");
  if (riskList) {
    riskList.querySelectorAll("[data-economy-proof]").forEach((btn) => {
      btn.addEventListener("click", () => loadEconomyProof(btn.dataset.economyProof || ""));
    });
  }
  renderEconomyRootList(safeReport.adjustments, "economy-adjustment-list", "尚無加減分明細", (row) => {
    const signed = Number(row.signed_amount || 0);
    const directionText = signed >= 0 ? `+${signed}` : String(signed);
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(row.actor_username || "system")} → ${sanitize(row.target_username || `user:${row.user_id || "-"}`)} · ${directionText} ${formatPointsCurrency(row.currency_type)}</strong>
          <div class="drive-card-sub">原因：${sanitize(row.reason || "-")} · ${sanitize(row.created_at || "")}</div>
          <div class="drive-card-sub">動作：${sanitize(row.action_type || "-")} · 狀態：${sanitize(row.status || "-")}</div>
          <div class="economy-ledger-hash">${sanitize(row.ledger_uuid || "")}</div>
        </div>
        <button class="btn" type="button" data-economy-proof="${sanitize(row.ledger_uuid || "")}">Proof</button>
      </div>
    `;
  });
  const adjustmentList = $("economy-adjustment-list");
  if (adjustmentList) {
    adjustmentList.querySelectorAll("[data-economy-proof]").forEach((btn) => {
      btn.addEventListener("click", () => loadEconomyProof(btn.dataset.economyProof || ""));
    });
  }
  const loadedAt = new Date().toLocaleTimeString("zh-TW", { hour12: false });
  if ($("economy-chain-loaded-at")) $("economy-chain-loaded-at").textContent = `最後更新 ${loadedAt}`;
  setEconomyChainStatus(formatEconomyVerificationSummary(verification), verification.ok !== false);
}

function renderEconomyRecovery(recovery, backups) {
  const safe = recovery && typeof recovery === "object" ? recovery : {};
  const plan = safe.restore_plan && typeof safe.restore_plan === "object" ? safe.restore_plan : {};
  const rows = Array.isArray(backups) ? backups : [];
  const status = $("economy-recovery-status");
  if (status) {
    status.textContent = safe.safe_mode
      ? `safe mode：啟用 · ${safe.reason || "-"} · forensic=${safe.forensic_bundle_id || "-"}`
      : "safe mode：未啟用";
    status.style.color = safe.safe_mode ? "#ffb74d" : "var(--muted)";
  }
  const select = $("economy-recovery-backup-id");
  if (select) {
    const recommended = plan.recommended_backup_id || "";
    select.innerHTML = rows.length
      ? rows.map((backup) => {
          const label = `${backup.backup_id} · height ${backup.chain_height || 0} · ${backup.created_at || ""}`;
          return `<option value="${sanitize(backup.backup_id || "")}" ${backup.backup_id === recommended ? "selected" : ""}>${sanitize(label)}</option>`;
        }).join("")
      : `<option value="">尚無可用備份</option>`;
  }
  renderEconomyRootList([plan], "economy-restore-plan-list", "目前沒有恢復方案", (item) => `
    <div class="drive-file-row">
      <div>
        <strong>建議備份：${sanitize(item.recommended_backup_id || "無")}</strong>
        <div class="drive-card-sub">目前 height ${Number(item.current_chain_height || 0)} → 備份 height ${Number(item.backup_chain_height || 0)}；wallet 來源：${sanitize(item.wallet_rebuild_source || "-")}</div>
        <div class="drive-card-sub">可能遺失交易：${Number((item.lost_ledger_range || {}).count || 0)} 筆（${sanitize((item.lost_ledger_range || {}).from_id || "-")} - ${sanitize((item.lost_ledger_range || {}).to_id || "-")}）</div>
      </div>
    </div>
  `);
  renderEconomyRootList(rows.slice(0, 12), "economy-backup-list", "尚無 ledger backup", (backup) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(backup.kind || "backup")} · height ${Number(backup.chain_height || 0)} · ${backup.verified ? "已驗證" : "驗證失敗"}</strong>
        <div class="drive-card-sub">${sanitize(backup.created_at || "")} · ledger ${Number(backup.ledger_row_count || 0)} · wallet snapshot ${Number(backup.wallet_count || 0)}</div>
        <div class="economy-ledger-hash">${sanitize(backup.latest_block_hash || backup.backup_id || "")}</div>
      </div>
    </div>
  `);
}

function renderEconomyAccountLookup(wallet, ledger) {
  const safeWallet = wallet && typeof wallet === "object" ? wallet : {};
  const pointsBalance = Number(safeWallet.points_balance || 0);
  const pointsFrozen = Number(safeWallet.points_frozen || 0);
  const pointsEarned = Number(safeWallet.total_points_earned || 0);
  const pointsSpent = Number(safeWallet.total_points_spent || 0);
  if ($("economy-query-points-balance")) $("economy-query-points-balance").textContent = String(pointsBalance);
  if ($("economy-query-points-frozen")) $("economy-query-points-frozen").textContent = `凍結 ${pointsFrozen}`;
  if ($("economy-query-points-earned")) $("economy-query-points-earned").textContent = `收入 ${pointsEarned}`;
  if ($("economy-query-points-spent")) $("economy-query-points-spent").textContent = `支出 ${pointsSpent}`;
  if ($("economy-query-wallet-status")) $("economy-query-wallet-status").textContent = safeWallet.wallet_status || "-";
  if ($("economy-query-public-account")) $("economy-query-public-account").textContent = safeWallet.public_account_id || "-";
  if ($("economy-wallet-sanction-status")) $("economy-wallet-sanction-status").value = safeWallet.wallet_status || "active";
  if ($("economy-wallet-sanction-risk")) $("economy-wallet-sanction-risk").value = safeWallet.risk_level || "normal";
  renderEconomyLedger(Array.isArray(ledger) ? ledger.slice(0, 12) : [], "economy-query-ledger-list");
}

async function fetchEconomyJson(url, options = {}) {
  await fetchCsrfToken({ force: true });
  const headers = { ...(options.headers || {}), "X-CSRF-Token": getCsrfToken() || "" };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await apiFetch(API + url, { credentials: "same-origin", ...options, headers });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
  return json;
}

async function loadEconomyDashboard() {
  if (!currentUser) return;
  try {
    const rootMode = currentUser === "root";
    const canManagePoints = canManageEconomyPoints();
    const adminCard = $("economy-admin-card");
    if ($("economy-page-title")) $("economy-page-title").textContent = rootMode ? "積分系統" : "積分錢包";
    if ($("economy-user-summary-grid")) $("economy-user-summary-grid").style.display = rootMode ? "none" : "";
    if ($("economy-user-ledger-card")) $("economy-user-ledger-card").style.display = rootMode ? "none" : "";
    if (adminCard) adminCard.style.display = canManagePoints ? "" : "none";
    if (rootMode) {
      if ($("economy-chain-ok")) $("economy-chain-ok").textContent = "讀取中";
      if ($("economy-chain-countdown")) $("economy-chain-countdown").textContent = "封塊進度：讀取中...";
      const sidebarPoints = $("sidebar-points");
      if (sidebarPoints) {
        sidebarPoints.dataset.points = "root: server resources";
        updateSidebarIdentity();
      }
    } else {
      stopEconomyBlockCountdown();
      const [wallet, ledger, catalog] = await Promise.all([
        fetchEconomyJson("/points/wallet"),
        fetchEconomyJson(`/points/ledger?limit=50&offset=${economyLedgerOffset}`),
        fetchEconomyJson("/points/catalog"),
      ]);
      renderEconomyWallet(wallet.wallet);
      renderEconomyLedger(ledger.ledger || []);
      renderEconomyCatalog(catalog.catalog || []);
    }
    if (canManagePoints) {
      loadEconomyAdmin();
    } else {
      if ($("economy-admin-ledger-list")) $("economy-admin-ledger-list").innerHTML = "";
      if ($("economy-pending-list")) $("economy-pending-list").innerHTML = "";
    }
    const rootCard = $("economy-root-card");
    if (rootCard) rootCard.style.display = currentUser === "root" ? "" : "none";
    const rootReportOk = rootMode ? await loadEconomyRootReport() : true;
    if (rootReportOk !== false) economySetMsg("");
  } catch (err) {
    economySetMsg(err.message || "PointsChain 讀取失敗", false);
  }
}

async function loadEconomyRootReport() {
  if (currentUser !== "root") return true;
  setEconomyChainStatus("讀取 PointsChain 狀態中...");
  try {
    const json = await fetchEconomyJson("/root/points/report");
    renderEconomyRootReport(json.report || {});
    economySetMsg("");
    return true;
  } catch (err) {
    stopEconomyBlockCountdown();
    if ($("economy-chain-ok")) $("economy-chain-ok").textContent = "讀取失敗";
    if ($("economy-chain-countdown")) $("economy-chain-countdown").textContent = "封塊進度：讀取失敗";
    setEconomyChainStatus(err.message || "PointsChain 狀態讀取失敗", false);
    economySetMsg(err.message || "PointsChain 狀態讀取失敗", false);
    return false;
  }
}

async function loadEconomyAdmin() {
  if (!canManageEconomyPoints()) return;
  try {
    const rootMode = currentUser === "root";
    const [ledger, pending, userList] = await Promise.all([
      fetchEconomyJson("/admin/points/ledger?limit=50"),
      fetchEconomyJson("/admin/points/pending-rewards?status=pending"),
      fetchEconomyJson("/admin/users"),
    ]);
    renderEconomyAdjustUserOptions(userList.users || []);
    const adminTitle = $("economy-admin-card-title");
    const adminSub = $("economy-admin-card-sub");
    const adminLedgerList = $("economy-admin-ledger-list");
    const adjustPanel = $("economy-adjust-panel");
    if (adjustPanel) adjustPanel.style.display = rootMode ? "" : "none";
    if (adminTitle) adminTitle.textContent = rootMode ? "手動加減分與待審核" : "待審核獎勵";
    if (adminSub) {
      adminSub.textContent = rootMode
        ? "這裡只負責送出補償、扣回與審核；加減分歷史統一在下方明細查看"
        : "manager 可處理待審核獎勵；手動加減分只允許 root 操作";
    }
    if (adminLedgerList) {
      adminLedgerList.style.display = rootMode ? "none" : "";
      if (rootMode) {
        adminLedgerList.innerHTML = "";
      } else {
        renderEconomyLedger(ledger.ledger || [], "economy-admin-ledger-list");
      }
    }
    const pendingList = $("economy-pending-list");
    if (pendingList) {
      const rows = pending.pending_rewards || [];
      pendingList.innerHTML = rows.length ? rows.map((row) => `
        <div class="drive-file-row">
          <div>
            <strong>#${Number(row.id)} · user ${Number(row.user_id)} · ${Number(row.amount)} ${formatPointsCurrency(row.currency_type)}</strong>
            <div class="drive-card-sub">${sanitize(row.action_type || "-")} · ${sanitize(row.created_at || "")}</div>
          </div>
          <div class="drive-file-actions">
            <button class="btn" type="button" data-pending-review="${Number(row.id)}" data-decision="approve">通過</button>
            <button class="btn btn-danger" type="button" data-pending-review="${Number(row.id)}" data-decision="reject">拒絕</button>
          </div>
        </div>
      `).join("") : `<div class="drive-empty">沒有待審核獎勵</div>`;
      pendingList.querySelectorAll("[data-pending-review]").forEach((btn) => {
        btn.addEventListener("click", () => reviewEconomyPendingReward(btn.dataset.pendingReview, btn.dataset.decision));
      });
    }
  } catch (err) {
    const select = $("economy-adjust-user-id");
    if (select) select.innerHTML = `<option value="">會員讀取失敗</option>`;
    economySetMsg(err.message || "管理資料讀取失敗", false);
  }
}

function renderEconomyAdjustUserOptions(rows) {
  const members = (Array.isArray(rows) ? rows : []).filter((user) => {
    const username = String(user.username || "").toLowerCase();
    return username !== "root";
  });
  const fillSelect = (select, emptyText) => {
    if (!select) return;
    const previous = select.value;
    if (!members.length) {
      select.innerHTML = `<option value="">${sanitize(emptyText)}</option>`;
      return;
    }
    select.innerHTML = `<option value="">請選擇會員</option>` + members.map((user) => {
      const id = Number(user.id);
      const username = sanitize(user.username || `user ${id}`);
      const role = sanitize(user.role || "-");
      const status = sanitize(user.status || "-");
      return `<option value="${id}">${username}（#${id} / ${role} / ${status}）</option>`;
    }).join("");
    if (previous && Array.from(select.options).some((option) => option.value === previous)) {
      select.value = previous;
    }
  };
  fillSelect($("economy-adjust-user-id"), "沒有可調整會員");
  fillSelect($("economy-query-user-id"), "沒有可查詢會員");
}

async function loadEconomyAccountLookup() {
  if (currentUser !== "root") return;
  const select = $("economy-query-user-id");
  const userId = Number(select?.value || 0);
  if (!Number.isFinite(userId) || userId <= 0) {
    economySetMsg("請先選擇要查詢的會員", false);
    return;
  }
  const btn = $("economy-account-query-btn");
  const oldText = btn ? btn.textContent : "";
  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "查詢中...";
    }
    const json = await fetchEconomyJson(`/admin/points/wallets/${encodeURIComponent(userId)}`);
    renderEconomyAccountLookup(json.wallet, json.ledger || []);
    economySetMsg("已更新指定帳戶積分");
  } catch (err) {
    economySetMsg(err.message || "帳戶積分查詢失敗", false);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "查詢";
    }
  }
}

async function sanctionEconomyWallet() {
  if (currentUser !== "root") return;
  const select = $("economy-query-user-id");
  const userId = Number(select?.value || 0);
  if (!Number.isFinite(userId) || userId <= 0) {
    economySetMsg("請先選擇要處分的會員", false);
    return;
  }
  const reason = $("economy-wallet-sanction-reason")?.value?.trim() || "";
  if (!reason) {
    economySetMsg("請輸入錢包處分原因", false);
    return;
  }
  const btn = $("economy-wallet-sanction-btn");
  const oldText = btn ? btn.textContent : "";
  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "處理中...";
    }
    await fetchEconomyJson(`/root/points/wallets/${encodeURIComponent(userId)}/sanction`, {
      method: "POST",
      body: JSON.stringify({
        wallet_status: $("economy-wallet-sanction-status")?.value || "active",
        risk_level: $("economy-wallet-sanction-risk")?.value || "normal",
        freeze_amount: Number($("economy-wallet-freeze-amount")?.value || 0),
        unfreeze_amount: Number($("economy-wallet-unfreeze-amount")?.value || 0),
        reason,
      }),
    });
    const refreshed = await fetchEconomyJson(`/admin/points/wallets/${encodeURIComponent(userId)}`);
    renderEconomyAccountLookup(refreshed.wallet, refreshed.ledger || []);
    if ($("economy-wallet-freeze-amount")) $("economy-wallet-freeze-amount").value = "0";
    if ($("economy-wallet-unfreeze-amount")) $("economy-wallet-unfreeze-amount").value = "0";
    economySetMsg("已套用錢包處分");
    await loadEconomyRootReport();
  } catch (err) {
    economySetMsg(err.message || "錢包處分失敗", false);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "套用處分";
    }
  }
}

async function spendEconomyItem(itemKey) {
  if (!itemKey) return;
  try {
    const json = await fetchEconomyJson("/points/spend", {
      method: "POST",
      body: JSON.stringify({ item_key: itemKey, quantity: 1, reference_type: "manual_ui_test", reference_id: String(Date.now()) }),
    });
    renderEconomyWallet(json.wallet);
    await loadEconomyDashboard();
    economySetMsg("已依 catalog 扣點");
  } catch (err) {
    economySetMsg(err.message || "扣點失敗", false);
  }
}

async function submitEconomyAdjustment() {
  const btn = $("economy-adjust-btn");
  const oldText = btn ? btn.textContent : "";
  try {
    if (currentUser !== "root") {
      economySetMsg("只有 root 可以手動調整積分", false);
      return;
    }
    const userId = Number($("economy-adjust-user-id")?.value || 0);
    if (!Number.isFinite(userId) || userId <= 0) {
      economySetMsg("請先選擇要調整的會員", false);
      return;
    }
    economySetMsg("正在送出點數調整...");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "送出中...";
    }
    const payload = {
      user_id: userId,
      direction: $("economy-adjust-direction")?.value || "credit",
      amount: Number($("economy-adjust-amount")?.value || 0),
      reason: $("economy-adjust-reason")?.value || "",
      idempotency_key: economyRequestId("admin-adjust"),
    };
    const json = await fetchEconomyJson("/admin/points/adjust", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    economySetMsg(`已寫入 ledger：${json.ledger?.ledger_uuid || ""}`);
    await loadEconomyDashboard();
    if (currentUser === "root") await loadEconomyRootReport();
    if (currentUser === "root" && String($("economy-query-user-id")?.value || "") === String(userId)) {
      await loadEconomyAccountLookup();
    }
  } catch (err) {
    const message = err.message || "調整失敗";
    economySetMsg(message, false);
    alert(message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "送出調整";
    }
  }
}

async function reviewEconomyPendingReward(id, decision) {
  try {
    await fetchEconomyJson(`/admin/points/pending-rewards/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body: JSON.stringify({ decision, review_note: decision === "approve" ? "approved in economy center" : "rejected in economy center" }),
    });
    economySetMsg("待審核獎勵已處理");
    await loadEconomyAdmin();
  } catch (err) {
    economySetMsg(err.message || "審核失敗", false);
  }
}

async function sealPointsChainBlock() {
  try {
    const json = await fetchEconomyJson("/root/points/chain/seal", {
      method: "POST",
      body: JSON.stringify({ limit: 100 }),
    });
    const block = json.block || {};
    setEconomyChainStatus(json.sealed
      ? `已封存區塊 #${Number(block.block_number || 0)}，包含 ${Number(block.ledger_count || 0)} 筆 ledger`
      : (json.msg || "目前沒有未封 ledger 可封存"));
    await loadEconomyDashboard();
  } catch (err) {
    economySetMsg(err.message || "封塊失敗", false);
    setEconomyChainStatus(err.message || "封塊失敗", false);
  }
}

async function verifyPointsChain() {
  try {
    const json = await fetchEconomyJson("/root/points/chain/verify");
    setEconomyChainStatus(formatEconomyVerificationSummary(json.verification || json), (json.verification || json).ok !== false);
    if (currentUser === "root") await loadEconomyRootReport();
  } catch (err) {
    economySetMsg(err.message || "驗證失敗", false);
    setEconomyChainStatus(err.message || "驗證失敗", false);
  }
}

async function createPointsChainBackup() {
  if (currentUser !== "root") return;
  try {
    const json = await fetchEconomyJson("/root/points/chain/backups", {
      method: "POST",
      body: JSON.stringify({}),
    });
    economySetMsg(json.ok ? `已建立 ledger backup：${json.backup_id || ""}` : "建立備份失敗", !!json.ok);
    await loadEconomyRootReport();
  } catch (err) {
    economySetMsg(err.message || "建立備份失敗", false);
  }
}

async function approvePointsChainRecovery() {
  if (currentUser !== "root") return;
  const backupId = $("economy-recovery-backup-id")?.value || "";
  const confirmText = $("economy-recovery-confirm")?.value || "";
  if (!backupId || confirmText !== "RESTORE POINTSCHAIN") {
    economySetMsg("請選擇備份，並輸入確認字串 RESTORE POINTSCHAIN", false);
    return;
  }
  if (!confirm("確認要用選定 ledger backup 恢復 PointsChain？wallet 會由 ledger 重建。")) return;
  try {
    const json = await fetchEconomyJson("/root/points/chain/recovery/approve", {
      method: "POST",
      body: JSON.stringify({ backup_id: backupId, confirm: confirmText }),
    });
    const resultMessage = formatEconomyRecoveryResult(json);
    if ($("economy-recovery-confirm")) $("economy-recovery-confirm").value = "";
    await loadEconomyDashboard();
    economySetMsg(resultMessage, !!json.ok);
    setEconomyChainStatus(formatEconomyVerificationSummary(json.verification || {}), (json.verification || {}).ok !== false);
  } catch (err) {
    economySetMsg(err.message || "恢復失敗", false);
  }
}

async function autoHandlePointsChainRecovery() {
  if (currentUser !== "root") return;
  if (!confirm("一鍵處理會先驗證 PointsChain；若已進入 safe mode 且有建議健康備份，會自動套用該備份並由 ledger 重建 wallet。是否繼續？")) return;
  const btn = $("economy-recovery-auto-handle-btn");
  const oldText = btn ? btn.textContent : "";
  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "處理中...";
    }
    economySetMsg("正在驗證 PointsChain 並準備處理異常...");
    const json = await fetchEconomyJson("/root/points/chain/recovery/auto-handle", {
      method: "POST",
      body: JSON.stringify({ confirm: "AUTO HANDLE POINTSCHAIN" }),
    });
    await loadEconomyDashboard();
    if (json.action === "verified_clean") {
      economySetMsg(json.msg || "PointsChain 驗證正常");
      setEconomyChainStatus(formatEconomyVerificationSummary(json.verification || {}), true);
      return;
    }
    const resultMessage = formatEconomyRecoveryResult(json);
    economySetMsg(json.msg || resultMessage || "異常鏈處理完成", !!json.ok);
    setEconomyChainStatus(formatEconomyVerificationSummary(json.verification || json.initial_verification || {}), !!json.ok);
  } catch (err) {
    economySetMsg(err.message || "一鍵處理異常鏈失敗", false);
    setEconomyChainStatus(err.message || "一鍵處理異常鏈失敗", false);
    await loadEconomyRootReport();
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "一鍵處理異常鏈";
    }
  }
}

async function rollbackEconomyLedger() {
  if (currentUser !== "root") return;
  const ledgerUuid = $("economy-rollback-ledger-uuid")?.value?.trim() || "";
  const reason = $("economy-rollback-reason")?.value?.trim() || "";
  if (!ledgerUuid || !reason) {
    economySetMsg("ledger UUID 與 rollback 原因都必填", false);
    return;
  }
  try {
    const json = await fetchEconomyJson(`/root/points/ledger/${encodeURIComponent(ledgerUuid)}/rollback`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    if ($("economy-rollback-ledger-uuid")) $("economy-rollback-ledger-uuid").value = "";
    if ($("economy-rollback-reason")) $("economy-rollback-reason").value = "";
    economySetMsg(`已建立 rollback ledger：${json.rollback_ledger?.ledger_uuid || ""}`);
    await loadEconomyRootReport();
    await loadEconomyAdmin();
  } catch (err) {
    economySetMsg(err.message || "Rollback 失敗", false);
  }
}

function bindEconomyInlineEvents() {
  if (economyInlineEventsBound) return;
  economyInlineEventsBound = true;
  const bindings = [
    ["economy-refresh-btn", loadEconomyDashboard],
    ["economy-admin-refresh-btn", loadEconomyAdmin],
    ["economy-adjust-btn", submitEconomyAdjustment],
    ["economy-account-query-btn", loadEconomyAccountLookup],
    ["economy-wallet-sanction-btn", sanctionEconomyWallet],
    ["economy-root-report-btn", loadEconomyRootReport],
    ["economy-backup-btn", createPointsChainBackup],
    ["economy-recovery-auto-handle-btn", autoHandlePointsChainRecovery],
    ["economy-recovery-approve-btn", approvePointsChainRecovery],
    ["economy-rollback-btn", rollbackEconomyLedger],
    ["economy-seal-btn", sealPointsChainBlock],
    ["economy-verify-btn", verifyPointsChain],
  ];
  bindings.forEach(([id, handler]) => {
    const el = $(id);
    if (!el || el.dataset.economyInlineBound === "1") return;
    el.dataset.economyInlineBound = "1";
    el.addEventListener("click", handler);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindEconomyInlineEvents);
} else {
  bindEconomyInlineEvents();
}

async function loadEconomyProof(ledgerUuid) {
  if (!ledgerUuid) return;
  try {
    const json = await fetchEconomyJson(`/points/ledger/${encodeURIComponent(ledgerUuid)}/proof`);
    const proof = json.proof || {};
    const text = proof.sealed
      ? `Proof 已封塊：ledger ${sanitize(ledgerUuid)} 位於區塊 #${Number(proof.block_number || 0)}，Merkle path ${Array.isArray(proof.merkle_path) ? proof.merkle_path.length : 0} 層`
      : `Proof 尚未封塊：ledger ${sanitize(ledgerUuid)} 仍在未封 ledger 中`;
    setEconomyChainStatus(text);
  } catch (err) {
    economySetMsg(err.message || "Proof 讀取失敗", false);
    setEconomyChainStatus(err.message || "Proof 讀取失敗", false);
  }
}
