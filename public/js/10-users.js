function renderUsers() {
  const tbody = $("user-table")?.querySelector("tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const allowedPendingIds = new Set();
  for (const u of users) {
    const blocked = u.blocked_until && new Date(u.blocked_until) > new Date();
    const isBlocked = blocked;
    const isSelf = String(u.username || "") === String(currentUser || "");
    const canReviewPending = (currentRole === "manager" || currentRole === "super_admin") && u.status === "pending" && !isSelf;
    if (canReviewPending) {
      allowedPendingIds.add(String(u.id));
    }
    const actionButtons = [];
    if (canReviewPending) {
      const approveBtn = document.createElement("button");
      approveBtn.className = "btn btn-primary";
      approveBtn.type = "button";
      approveBtn.textContent = "核准";
      approveBtn.addEventListener("click", () => reviewRegistration(u.id, "approve"));
      actionButtons.push(approveBtn);

      const rejectBtn = document.createElement("button");
      rejectBtn.className = "btn";
      rejectBtn.type = "button";
      rejectBtn.textContent = "駁回";
      rejectBtn.style.color = "#ff8a80";
      rejectBtn.addEventListener("click", () => reviewRegistration(u.id, "reject"));
      actionButtons.push(rejectBtn);
    }
    if (currentRole === "manager" || currentRole === "super_admin") {
      if (u.role !== "super_admin" && !isSelf) {
        const blockBtn = document.createElement("button");
        blockBtn.className = "btn btn-primary";
        blockBtn.type = "button";
        blockBtn.textContent = isBlocked ? "解除封鎖" : "封鎖";
        blockBtn.dataset.userId = String(u.id);
        blockBtn.addEventListener("click", () => toggleBlock(u.id, isBlocked));
        actionButtons.push(blockBtn);
      }
    }
    if ((currentRole === "manager" || currentRole === "super_admin") && u.role === "user" && !isSelf) {
      const levelWrap = document.createElement("span");
      levelWrap.style.display = "inline-flex";
      levelWrap.style.gap = ".25rem";
      levelWrap.style.alignItems = "center";
      const levelSelect = document.createElement("select");
      levelSelect.id = `member-level-select-${u.id}`;
      levelSelect.style.maxWidth = "105px";
      const levelOptions = currentRole === "super_admin"
        ? ["newbie", "normal", "trusted", "vip", "restricted", "suspended"]
        : ["newbie", "normal", "trusted", "vip"];
      levelOptions.forEach((level) => {
        const opt = document.createElement("option");
        opt.value = level;
        opt.textContent = level;
        if ((u.effective_level || u.base_level || u.member_level || "normal") === level) opt.selected = true;
        levelSelect.appendChild(opt);
      });
      const levelBtn = document.createElement("button");
      levelBtn.className = "btn";
      levelBtn.type = "button";
      levelBtn.textContent = "套用等級";
      levelBtn.style.color = "#82b1ff";
      levelBtn.addEventListener("click", () => updateUserMemberLevel(u.id, u.username));
      levelWrap.appendChild(levelSelect);
      levelWrap.appendChild(levelBtn);
      actionButtons.push(levelWrap);
    }
    // Promote button (super_admin only: user -> manager)
    if (currentRole === "super_admin" && u.role === "user" && !isSelf) {
      const promoteBtn = document.createElement("button");
      promoteBtn.className = "btn";
      promoteBtn.type = "button";
      promoteBtn.textContent = "升級";
      promoteBtn.title = "升級為管理者";
      promoteBtn.style.color = "#82b1ff";
      promoteBtn.addEventListener("click", () => promoteUser(u.id, u.username));
      actionButtons.push(promoteBtn);
    }
    // Demote button (super_admin only: manager→user, user→delete)
    if (currentRole === "super_admin" && u.role === "manager" && !isSelf) {
      const demBtn = document.createElement("button");
      demBtn.className = "btn";
      demBtn.type = "button";
      demBtn.textContent = "⬇ 降級";
      demBtn.style.color = "#ff8a80";
      demBtn.addEventListener("click", () => demoteUser(u.id, u.username, u.role));
      actionButtons.push(demBtn);
    }
    // Violation controls (manager/super_admin)
    if ((currentRole === "manager" || currentRole === "super_admin") && u.role !== "super_admin" && !isSelf) {
      const violCount = u.violation_count || 0;
      const violBtn = document.createElement("button");
      violBtn.className = "btn";
      violBtn.type = "button";
      violBtn.textContent = `⚠ ${violCount}`;
      violBtn.style.color = violCount > 0 ? "#ff4f6d" : "#888";
      violBtn.addEventListener("click", () => addViolation(u.id));
      actionButtons.push(violBtn);
      if (currentRole === "super_admin") {
        const detailBtn = document.createElement("button");
        detailBtn.className = "btn";
        detailBtn.type = "button";
        detailBtn.textContent = "明細";
        detailBtn.title = "查看違規原因";
        detailBtn.style.color = "#82b1ff";
        detailBtn.addEventListener("click", () => {
          switchAdminTab("violations");
          loadViolations(0, u.username);
        });
        actionButtons.push(detailBtn);
      }
      const governanceBtn = document.createElement("button");
      governanceBtn.className = "btn";
      governanceBtn.type = "button";
      governanceBtn.textContent = "治理";
      governanceBtn.title = "建立治理提案";
      governanceBtn.style.color = "#ffb74d";
      governanceBtn.addEventListener("click", () => openGovernanceProposalForUser(u.id, u.username));
      actionButtons.push(governanceBtn);
      if (violCount > 0) {
        const resetBtn = document.createElement("button");
        resetBtn.className = "btn";
        resetBtn.type = "button";
        resetBtn.textContent = "↺";
        resetBtn.title = "歸零違規";
        resetBtn.style.color = "#4caf50";
        resetBtn.addEventListener("click", () => resetViolations(u.id));
        actionButtons.push(resetBtn);
      }
    }
    if (canManageUsers || isSelf) {
      const editBtn = document.createElement("button");
      editBtn.className = "btn btn-primary";
      editBtn.type = "button";
      editBtn.textContent = isSelf ? "我的資料" : "修改";
      editBtn.addEventListener("click", () => editUser(u.id));
      editBtn.classList.add("action-edit-user");
      actionButtons.push(editBtn);
    }
    // PM button: any logged-in user can PM anyone except self
    if (!isSelf) {
      const pmBtn = document.createElement("button");
      pmBtn.className = "btn";
      pmBtn.type = "button";
      pmBtn.textContent = "💬 私訊";
      pmBtn.style.color = "#82b1ff";
      pmBtn.title = `傳送私人訊息給 ${u.username}`;
      pmBtn.addEventListener("click", () => openPmWithUser(u.username));
      actionButtons.push(pmBtn);
    }
    if ((currentRole === "manager" || currentRole === "super_admin") && u.username !== "root" && !isSelf) {
      const noticeBtn = document.createElement("button");
      noticeBtn.className = "btn";
      noticeBtn.type = "button";
      noticeBtn.textContent = "通知";
      noticeBtn.style.color = "#82b1ff";
      noticeBtn.title = `發送管理通知給 ${u.username}`;
      noticeBtn.addEventListener("click", () => openAdminNoticeForUser(u.id));
      actionButtons.push(noticeBtn);
    }
    if (canManageUsers && !isSelf) {
      const delBtn = document.createElement("button");
      delBtn.className = "btn btn-danger";
      delBtn.type = "button";
      delBtn.textContent = "刪除";
      delBtn.addEventListener("click", () => removeUser(u.id));
      delBtn.classList.add("action-remove-user");
      actionButtons.push(delBtn);
    }
    const tr = document.createElement("tr");
    if (isBlocked) tr.style.opacity = "0.5";
    const appendTextCell = (value) => {
      const td = document.createElement("td");
      td.textContent = value == null ? "" : String(value);
      tr.appendChild(td);
      return td;
    };
    const selectCell = document.createElement("td");
    if (canReviewPending) {
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selectedPendingUserIds.has(String(u.id));
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) selectedPendingUserIds.add(String(u.id));
        else selectedPendingUserIds.delete(String(u.id));
        updatePendingSelectionUi();
      });
      selectCell.appendChild(checkbox);
    } else {
      selectCell.textContent = "—";
      selectCell.style.color = "var(--muted)";
    }
    const actions = document.createElement("div");
    actions.className = "action";
    actionButtons.forEach((btn) => actions.appendChild(btn));
    appendTextCell(u.id);
    appendTextCell(u.username || "");
    appendTextCell(u.nickname || "");
    appendTextCell(u.real_name || "");
    appendTextCell(u.role_label || u.role || "");
    appendTextCell(u.member_level_label || `${u.effective_level || u.member_level || "-"}${u.base_level && u.base_level !== u.effective_level ? ` (${u.base_level})` : ""}`);
    const statusCell = document.createElement("td");
    const statusSpan = document.createElement("span");
    statusSpan.textContent = "正常";
    statusSpan.style.color = "#4caf50";
    if (u.status === "pending") {
      statusSpan.textContent = "待審核";
      statusSpan.style.color = "#ffb74d";
    } else if (u.status === "rejected") {
      statusSpan.textContent = "已駁回";
      statusSpan.style.color = "#ff4f6d";
    } else if (u.status === "inactive") {
      statusSpan.textContent = "停用";
      statusSpan.style.color = "#9e9e9e";
    }
    if (isBlocked) {
      statusSpan.textContent = "封鎖中";
      statusSpan.style.color = "#ff4f6d";
    }
    statusCell.appendChild(statusSpan);
    tr.appendChild(statusCell);
    const violationCell = document.createElement("td");
    const violationCount = u.violation_count || 0;
    if (violationCount > 0) {
      const violationSpan = document.createElement("span");
      violationSpan.textContent = String(violationCount);
      violationSpan.style.color = "#ff4f6d";
      violationSpan.style.fontWeight = "bold";
      violationCell.appendChild(violationSpan);
    } else {
      violationCell.textContent = "0";
    }
    tr.appendChild(violationCell);
    tr.insertBefore(selectCell, tr.firstChild);
    const actionCell = document.createElement("td");
    actionCell.appendChild(actions);
    tr.appendChild(actionCell);
    tbody.appendChild(tr);
  }
  selectedPendingUserIds = new Set([...selectedPendingUserIds].filter((id) => allowedPendingIds.has(id)));
  updatePendingSelectionUi();
  // Role quota info
  const managerCount = users.filter(u => u.role === "manager").length;
  const infoEl = $("role-limit-info");
  if (infoEl) {
    infoEl.textContent = `管理者 ${managerCount}/5 · 超級管理者 1/1`;
    infoEl.style.color = managerCount >= 5 ? "#ff4f6d" : "#888";
  }
}

function updatePendingSelectionUi() {
  const count = selectedPendingUserIds.size;
  const info = $("pending-selection-info");
  if (info) info.textContent = `已選 ${count} 筆待審核`;
  const approveBtn = $("admin-bulk-approve");
  const rejectBtn = $("admin-bulk-reject");
  if (approveBtn) approveBtn.disabled = count === 0;
  if (rejectBtn) rejectBtn.disabled = count === 0;
}

async function loadUsers() {
  if (!currentUser) return;
  if (!["manager","super_admin"].includes(currentRole)) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await apiFetch(API + "/admin/users", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json();
    if (!json.ok) return;
    users = Array.isArray(json.users) ? json.users : [];
    canManageUsers = !!json.can_manage;
    renderUsers();
    if (typeof renderAdminNoticeTargetOptions === "function") renderAdminNoticeTargetOptions();
  } catch (_) {}
}
