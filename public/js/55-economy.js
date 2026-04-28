let economyLedgerOffset = 0;

function economySetMsg(text, ok = true) {
  const el = $("economy-msg");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = ok ? "#4caf50" : "#ff4f6d";
}

function formatPointsCurrency(currency) {
  return currency === "hard" ? "hard" : "soft";
}

function renderEconomyWallet(wallet) {
  if (!wallet) return;
  if ($("economy-soft-balance")) $("economy-soft-balance").textContent = String(wallet.soft_balance || 0);
  if ($("economy-hard-balance")) $("economy-hard-balance").textContent = String(wallet.hard_balance || 0);
  if ($("economy-soft-frozen")) $("economy-soft-frozen").textContent = `凍結 ${wallet.soft_frozen || 0}`;
  if ($("economy-hard-frozen")) $("economy-hard-frozen").textContent = `凍結 ${wallet.hard_frozen || 0}`;
  if ($("economy-wallet-status")) $("economy-wallet-status").textContent = wallet.wallet_status || "-";
  if ($("economy-public-account")) $("economy-public-account").textContent = wallet.public_account_id || "-";
  const sidebarPoints = $("sidebar-points");
  if (sidebarPoints) {
    sidebarPoints.dataset.points = `${wallet.soft_balance || 0} / ${wallet.hard_balance || 0}`;
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
        <div class="drive-card-sub">${sanitize(item.category || "-")} · ${formatPointsCurrency(item.currency_type)} ${Number(item.base_price || 0)}</div>
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

async function fetchEconomyJson(url, options = {}) {
  await fetchCsrfToken({ force: true });
  const headers = { ...(options.headers || {}), "X-CSRF-Token": getCsrfToken() || "" };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await fetch(API + url, { credentials: "same-origin", ...options, headers });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
  return json;
}

async function loadEconomyDashboard() {
  if (!currentUser) return;
  try {
    const [wallet, ledger, catalog] = await Promise.all([
      fetchEconomyJson("/points/wallet"),
      fetchEconomyJson(`/points/ledger?limit=50&offset=${economyLedgerOffset}`),
      fetchEconomyJson("/points/catalog"),
    ]);
    renderEconomyWallet(wallet.wallet);
    renderEconomyLedger(ledger.ledger || []);
    renderEconomyCatalog(catalog.catalog || []);
    if (currentRole === "manager" || currentRole === "super_admin") {
      const card = $("economy-admin-card");
      if (card) card.style.display = "";
      loadEconomyAdmin();
    }
    const rootCard = $("economy-root-card");
    if (rootCard) rootCard.style.display = currentUser === "root" ? "" : "none";
    economySetMsg("");
  } catch (err) {
    economySetMsg(err.message || "PointsChain 讀取失敗", false);
  }
}

async function loadEconomyAdmin() {
  if (!(currentRole === "manager" || currentRole === "super_admin")) return;
  try {
    const [ledger, pending] = await Promise.all([
      fetchEconomyJson("/admin/points/ledger?limit=50"),
      fetchEconomyJson("/admin/points/pending-rewards?status=pending"),
    ]);
    renderEconomyLedger(ledger.ledger || [], "economy-admin-ledger-list");
    const pendingList = $("economy-pending-list");
    if (pendingList) {
      const rows = pending.pending_rewards || [];
      pendingList.innerHTML = rows.length ? rows.map((row) => `
        <div class="drive-file-row">
          <div>
            <strong>#${Number(row.id)} · user ${Number(row.user_id)} · ${Number(row.amount)} ${sanitize(row.currency_type)}</strong>
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
    economySetMsg(err.message || "管理資料讀取失敗", false);
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
  try {
    const payload = {
      user_id: Number($("economy-adjust-user-id")?.value || 0),
      currency_type: $("economy-adjust-currency")?.value || "soft",
      direction: $("economy-adjust-direction")?.value || "credit",
      amount: Number($("economy-adjust-amount")?.value || 0),
      reason: $("economy-adjust-reason")?.value || "",
    };
    const json = await fetchEconomyJson("/admin/points/adjust", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    economySetMsg(`已寫入 ledger：${json.ledger?.ledger_uuid || ""}`);
    await loadEconomyDashboard();
  } catch (err) {
    economySetMsg(err.message || "調整失敗", false);
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
    const status = $("economy-chain-status");
    if (status) status.textContent = JSON.stringify(json, null, 2);
    await loadEconomyDashboard();
  } catch (err) {
    economySetMsg(err.message || "封塊失敗", false);
  }
}

async function verifyPointsChain() {
  try {
    const json = await fetchEconomyJson("/root/points/chain/verify");
    const status = $("economy-chain-status");
    if (status) status.textContent = JSON.stringify(json.verification || json, null, 2);
  } catch (err) {
    economySetMsg(err.message || "驗證失敗", false);
  }
}

async function loadEconomyProof(ledgerUuid) {
  if (!ledgerUuid) return;
  try {
    const json = await fetchEconomyJson(`/points/ledger/${encodeURIComponent(ledgerUuid)}/proof`);
    const status = $("economy-chain-status") || $("economy-msg");
    if (status.tagName === "PRE") status.textContent = JSON.stringify(json.proof, null, 2);
    else status.textContent = JSON.stringify(json.proof);
  } catch (err) {
    economySetMsg(err.message || "Proof 讀取失敗", false);
  }
}
