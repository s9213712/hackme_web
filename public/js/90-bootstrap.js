function bindUiEvents() {
  const tabLogin    = $("tab-login");
  const tabRegister = $("tab-register");
  const tabModuleChat = $("tab-module-chat");
  const tabModuleCommunity = $("tab-module-community");
  const tabModuleDrive = $("tab-module-drive");
  const tabModuleAccounts = $("tab-module-accounts");
  const tabModuleServer = $("tab-module-server");
  const tabModuleAppeals = $("tab-module-appeals");
  const tabServerHealth = $("tab-server-health");
  const tabServerSettings = $("tab-server-settings");
  const tabServerEnv = $("tab-server-env");
  const tabSettingsSecurity = $("tab-settings-security");
  const tabSettingsFeatures = $("tab-settings-features");
  const tabSettingsAppearance = $("tab-settings-appearance");
  const tabSettingsSystem = $("tab-settings-system");
  const tabUsers    = $("tab-users");
  const tabAudit    = $("tab-audit");
  const tabViol     = $("tab-violations");
  const tabAppeals  = $("tab-appeals");
  const tabReports  = $("tab-reports");
  const liBtn       = $("li-btn");
  const regBtn      = $("reg-btn");
  const logoutBtn   = $("logout-btn");
  const selfEditBtn = $("self-edit-btn");
  const adminRefresh = $("admin-refresh");
  const adminBulkApproveBtn = $("admin-bulk-approve");
  const adminBulkRejectBtn = $("admin-bulk-reject");
  const adminOpenAddBtn  = $("admin-open-add-user");
  const adminAddBtn  = $("admin-add-btn");
  const adminAddCancelBtn = $("admin-add-cancel");
  const auditRefresh = $("audit-refresh");
  const violRefresh  = $("violations-refresh");
  const appealSubmit = $("appeal-submit-btn");
  const appealRefresh = $("appeal-refresh-btn");
  const reportRefresh = $("admin-reports-refresh");
  const adminAppealsBulkApproveBtn = $("admin-appeals-bulk-approve");
  const adminAppealsBulkRejectBtn = $("admin-appeals-bulk-reject");
  const adminReportsBulkApproveBtn = $("admin-reports-bulk-approve");
  const adminReportsBulkRejectBtn = $("admin-reports-bulk-reject");
  const settingsSave = $("settings-save-btn");
  const healthRefresh = $("health-refresh-btn");
  const integrityRepair = $("integrity-repair-btn");
  const restartBtn   = $("restart-server-btn");
  const editSaveBtn = $("user-edit-save");
  const editCancelBtn = $("user-edit-cancel");
  const chatCreateBtn = $("chat-create-room-btn");
  const chatJoinBtn = $("chat-join-room-btn");
  const chatRefreshRoomBtn = $("chat-room-refresh-btn");
  const chatRefreshMsgBtn = $("chat-refresh-msg-btn");
  const chatSendBtn = $("chat-send-btn");
  const chatInput = $("chat-message-input");
  const communityAnnouncementBtn = $("community-announcement-submit");
  const communityBoardRequestBtn = $("community-board-request-btn");
  const communityThreadSubmitBtn = $("community-thread-submit");
  const communityReplySubmitBtn = $("community-reply-submit");
  const communityThreadPrevBtn = $("community-thread-prev");
  const communityThreadNextBtn = $("community-thread-next");
  const communityThreadLockToggle = $("community-thread-lock-toggle");
  const communityThreadDeleteBtn = $("community-thread-delete-btn");
  const communityBoardSearch = $("community-board-search");
  const communityThreadSearch = $("community-thread-search");
  const driveRefreshBtn = $("drive-refresh-btn");
  const userEditOverlay = $("user-edit-overlay");
  const adminAddOverlay = $("admin-add-overlay");

  if (tabLogin)    tabLogin.addEventListener("click",    () => showTab("login"));
  if (tabRegister) tabRegister.addEventListener("click", () => showTab("register"));
  if (tabModuleChat) tabModuleChat.addEventListener("click", () => switchModuleTab("chat"));
  if (tabModuleCommunity) tabModuleCommunity.addEventListener("click", () => switchModuleTab("community"));
  if (tabModuleDrive) tabModuleDrive.addEventListener("click", () => switchModuleTab("drive"));
  if (tabModuleAppeals) tabModuleAppeals.addEventListener("click", () => switchModuleTab("appeals"));
  if (tabModuleAccounts) tabModuleAccounts.addEventListener("click", () => switchModuleTab("accounts"));
  if (tabModuleServer) tabModuleServer.addEventListener("click", () => switchModuleTab("server"));
  if (tabServerHealth) tabServerHealth.addEventListener("click", () => switchServerTab("health"));
  if (tabServerSettings) tabServerSettings.addEventListener("click", () => switchServerTab("settings"));
  if (tabServerEnv) tabServerEnv.addEventListener("click", () => switchServerTab("env"));
  if (tabSettingsSecurity) tabSettingsSecurity.addEventListener("click", () => switchSettingsSection("security"));
  if (tabSettingsFeatures) tabSettingsFeatures.addEventListener("click", () => switchSettingsSection("features"));
  if (tabSettingsAppearance) tabSettingsAppearance.addEventListener("click", () => switchSettingsSection("appearance"));
  if (tabSettingsSystem) tabSettingsSystem.addEventListener("click", () => switchSettingsSection("system"));
  if (tabUsers)    tabUsers.addEventListener("click",    () => switchAdminTab("users"));
  if (tabAudit)    tabAudit.addEventListener("click",    () => switchAdminTab("audit"));
  if (tabViol)     tabViol.addEventListener("click",     () => switchAdminTab("violations"));
  if (tabAppeals)  tabAppeals.addEventListener("click",   () => switchAdminTab("appeals"));
  if (tabReports)  tabReports.addEventListener("click",   () => switchAdminTab("reports"));
  if (liBtn)       liBtn.addEventListener("click",        doLogin);
  if (regBtn)      regBtn.addEventListener("click",       doRegister);
  if (logoutBtn)  logoutBtn.addEventListener("click",    doLogout);
  if (selfEditBtn) selfEditBtn.addEventListener("click", () => {
    if (currentUserId) editUser(currentUserId);
  });
  if (adminRefresh) adminRefresh.addEventListener("click", loadUsers);
  if (adminBulkApproveBtn) adminBulkApproveBtn.addEventListener("click", () => bulkReviewRegistrations("approve"));
  if (adminBulkRejectBtn) adminBulkRejectBtn.addEventListener("click", () => bulkReviewRegistrations("reject"));
  if (adminOpenAddBtn) adminOpenAddBtn.addEventListener("click", showAdminAddDialog);
  if (adminAddBtn)  adminAddBtn.addEventListener("click",  createUserByAdmin);
  if (adminAddCancelBtn) adminAddCancelBtn.addEventListener("click", hideAdminAddDialog);
  if (chatCreateBtn) chatCreateBtn.addEventListener("click", createChatRoom);
  if (chatJoinBtn) chatJoinBtn.addEventListener("click", joinChatRoom);
  if (chatRefreshRoomBtn) chatRefreshRoomBtn.addEventListener("click", loadChatRooms);
  if (chatRefreshMsgBtn) chatRefreshMsgBtn.addEventListener("click", () => {
    if (selectedChatRoomId) loadChatMessages(selectedChatRoomId, false);
  });
  if (chatSendBtn) chatSendBtn.addEventListener("click", sendChatMessage);
  if (communityAnnouncementBtn) communityAnnouncementBtn.addEventListener("click", publishAnnouncement);
  if (communityBoardRequestBtn) communityBoardRequestBtn.addEventListener("click", requestCommunityBoard);
  if (communityThreadSubmitBtn) communityThreadSubmitBtn.addEventListener("click", createCommunityThread);
  if (communityReplySubmitBtn) communityReplySubmitBtn.addEventListener("click", replyCommunityThread);
  if (communityThreadPrevBtn) communityThreadPrevBtn.addEventListener("click", () => {
    if (!selectedCommunityBoardId || communityThreadPage <= 0) return;
    communityThreadPage -= 1;
    openCommunityBoard(selectedCommunityBoardId);
  });
  if (communityThreadNextBtn) communityThreadNextBtn.addEventListener("click", () => {
    if (!selectedCommunityBoardId) return;
    communityThreadPage += 1;
    openCommunityBoard(selectedCommunityBoardId);
  });
  if (communityThreadLockToggle) communityThreadLockToggle.addEventListener("click", toggleCommunityThreadLock);
  if (communityThreadDeleteBtn) communityThreadDeleteBtn.addEventListener("click", deleteCommunityThread);
  if (communityBoardSearch) communityBoardSearch.addEventListener("input", (e) => {
    communityBoardQuery = e?.target?.value || "";
    renderCommunityBoards();
  });
  if (communityThreadSearch) communityThreadSearch.addEventListener("input", (e) => {
    communityThreadQuery = e?.target?.value || "";
    communityThreadPage = 0;
    if (selectedCommunityBoardId) openCommunityBoard(selectedCommunityBoardId);
  });
  if (driveRefreshBtn) driveRefreshBtn.addEventListener("click", loadDriveDashboard);
  if (editSaveBtn)   editSaveBtn.addEventListener("click", submitEditUser);
  if (editCancelBtn) editCancelBtn.addEventListener("click", hideUserEditDialog);
  if (userEditOverlay) userEditOverlay.addEventListener("click", (e) => {
    if (e.target === userEditOverlay) hideUserEditDialog();
  });
  if (adminAddOverlay) adminAddOverlay.addEventListener("click", (e) => {
    if (e.target === adminAddOverlay) hideAdminAddDialog();
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      hideUserEditDialog();
      hideAdminAddDialog();
    }
  });
  if (chatInput) chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      sendChatMessage();
    }
  });

  // Audit pagination
  if (auditRefresh) auditRefresh.addEventListener("click", () => loadAudit(auditPage));
  if ($("audit-prev")) $("audit-prev").addEventListener("click", () => loadAudit(Math.max(0, auditPage - 1)));
  if ($("audit-next")) $("audit-next").addEventListener("click", () => loadAudit(auditPage + 1));

  if (appealSubmit) appealSubmit.addEventListener("click", submitAppeal);
  if (appealRefresh) appealRefresh.addEventListener("click", loadUserAppeals);
  if ($("admin-appeal-status")) $("admin-appeal-status").addEventListener("change", (e) => {
    adminAppealStatus = e?.target?.value || "pending";
    loadAdminAppeals(1, adminAppealStatus);
  });
  if ($("admin-appeals-prev")) $("admin-appeals-prev").addEventListener("click", () => loadAdminAppeals(Math.max(1, adminAppealPage - 1), adminAppealStatus));
  if ($("admin-appeals-next")) $("admin-appeals-next").addEventListener("click", () => loadAdminAppeals(adminAppealPage + 1, adminAppealStatus));
  if ($("admin-appeals-refresh")) $("admin-appeals-refresh").addEventListener("click", () => loadAdminAppeals(adminAppealPage, adminAppealStatus));
  if (adminAppealsBulkApproveBtn) adminAppealsBulkApproveBtn.addEventListener("click", () => bulkReviewAppeals("approve"));
  if (adminAppealsBulkRejectBtn) adminAppealsBulkRejectBtn.addEventListener("click", () => bulkReviewAppeals("reject"));
  if ($("admin-report-status")) $("admin-report-status").addEventListener("change", (e) => {
    adminReportStatus = e?.target?.value || "pending";
    loadAdminReports(0, adminReportStatus);
  });
  if ($("admin-reports-prev")) $("admin-reports-prev").addEventListener("click", () => loadAdminReports(Math.max(0, adminReportPage - 1), adminReportStatus));
  if ($("admin-reports-next")) $("admin-reports-next").addEventListener("click", () => loadAdminReports(adminReportPage + 1, adminReportStatus));
  if (reportRefresh) reportRefresh.addEventListener("click", () => loadAdminReports(adminReportPage, adminReportStatus));
  if (adminReportsBulkApproveBtn) adminReportsBulkApproveBtn.addEventListener("click", () => bulkReviewMessageReports("approve"));
  if (adminReportsBulkRejectBtn) adminReportsBulkRejectBtn.addEventListener("click", () => bulkReviewMessageReports("reject"));

  // Violations
  if (violRefresh) violRefresh.addEventListener("click", () => loadViolations(violationsPage, violationTargetUser));
  if ($("violations-prev")) $("violations-prev").addEventListener("click", () => loadViolations(Math.max(0, violationsPage - 1), violationTargetUser));
  if ($("violations-next")) $("violations-next").addEventListener("click", () => loadViolations(violationsPage + 1, violationTargetUser));

  // Settings
  if (settingsSave) settingsSave.addEventListener("click", saveSettings);
  if (healthRefresh) healthRefresh.addEventListener("click", loadServerHealth);
  if (integrityRepair) integrityRepair.addEventListener("click", repairIntegrityChains);
  if (restartBtn)   restartBtn.addEventListener("click",   restartServer);
}

$("li-pw").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doLogin();
});
$("reg-pw").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doRegister();
});

(async function init() {
  await loadSiteConfig();
  try {
    startClock();
  } catch (err) {
    console.error("clock bootstrap failed", err);
  }
  setupInactivityTracking();
  _csrfToken = readCookie("csrf_token");
  bindUiEvents();
  // 帶 timeout 的 fetch，避免 server 無回應時 UI 卡死
  async function safeFetch(url, opts = {}) {
    const ctrl = new AbortController();
    const id = setTimeout(() => ctrl.abort(), 5000);
    try {
      const res = await fetch(url, { ...opts, signal: ctrl.signal });
      clearTimeout(id);
      return res;
    } catch (e) {
      clearTimeout(id);
      throw e;
    }
  }
  try {
    const res = await safeFetch(API + "/me", { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (json.ok) setAuthState(json);
  } catch (_) { /* 網路問題或 timeout，不影響操作 */ }
})();
