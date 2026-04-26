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
    // Promote button (manager/super_admin can promote user→manager)
    if ((currentRole === "manager" || currentRole === "super_admin") && u.role === "user" && !isSelf) {
      const promBtn = document.createElement("button");
      promBtn.className = "btn";
      promBtn.type = "button";
      promBtn.textContent = "⬆ 升級";
      promBtn.style.color = "#82b1ff";
      promBtn.addEventListener("click", () => promoteUser(u.id, u.username));
      actionButtons.push(promBtn);
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
      if (canManageUsers && !isSelf) {
        const delBtn = document.createElement("button");
        delBtn.className = "btn btn-danger";
        delBtn.type = "button";
        delBtn.textContent = "刪除";
        delBtn.addEventListener("click", () => removeUser(u.id));
        delBtn.classList.add("action-remove-user");
        actionButtons.push(delBtn);
      }
    }
    const tr = document.createElement("tr");
    if (isBlocked) tr.style.opacity = "0.5";
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
    let statusLabel = `<span style="color:#4caf50;">正常</span>`;
    if (u.status === "pending") statusLabel = `<span style="color:#ffb74d;">待審核</span>`;
    else if (u.status === "rejected") statusLabel = `<span style="color:#ff4f6d;">已駁回</span>`;
    else if (u.status === "inactive") statusLabel = `<span style="color:#9e9e9e;">停用</span>`;
    if (isBlocked) statusLabel = `<span style="color:#ff4f6d;">封鎖中</span>`;
    const violDisplay = (u.violation_count || 0) > 0 ? `<span style="color:#ff4f6d;font-weight:bold;">${u.violation_count}</span>` : "0";
    tr.innerHTML = `
      <td>${u.id}</td>
      <td>${sanitize(u.username || "")}</td>
      <td>${sanitize(u.nickname || "")}</td>
      <td>${sanitize(u.real_name || "")}</td>
      <td>${sanitize(u.role_label || u.role || "")}</td>
      <td>${statusLabel}</td>
      <td>${violDisplay}</td>
    `;
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
    const res = await fetch(API + "/admin/users", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json();
    if (!json.ok) return;
    users = Array.isArray(json.users) ? json.users : [];
    canManageUsers = !!json.can_manage;
    renderUsers();
  } catch (_) {}
}
