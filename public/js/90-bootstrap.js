function bindUiEvents() {
  if (typeof decorateSidebarMenu === "function") decorateSidebarMenu();
  const tabLogin    = $("tab-login");
  const tabRegister = $("tab-register");
  const tabModuleChat = $("tab-module-chat");
  const tabModuleDm = $("tab-module-dm");
  const tabModuleAnnouncements = $("tab-module-announcements");
  const tabModuleCommunity = $("tab-module-community");
  const tabModuleDrive = $("tab-module-drive");
  const tabModuleAlbums = $("tab-module-albums");
  const tabModuleComfyui = $("tab-module-comfyui");
  const tabModuleAccounts = $("tab-module-accounts");
  const tabModuleServer = $("tab-module-server");
  const tabModuleAppeals = $("tab-module-appeals");
  const tabServerHealth = $("tab-server-health");
  const tabServerSecurity = $("tab-server-security");
  const tabServerAudit = $("tab-server-audit");
  const tabServerIntegrity = $("tab-server-integrity");
  const tabServerSettings = $("tab-server-settings");
  const tabServerEnv = $("tab-server-env");
  const tabSettingsSecurity = $("tab-settings-security");
  const tabSettingsFeatures = $("tab-settings-features");
  const tabSettingsAppearance = $("tab-settings-appearance");
  const tabSettingsSystem = $("tab-settings-system");
  const tabSettingsDrive = $("tab-settings-drive");
  const tabSettingsMemberLevels = $("tab-settings-member-levels");
  const tabUsers    = $("tab-users");
  const tabViol     = $("tab-violations");
  const tabGovernance = $("tab-governance");
  const tabAppeals  = $("tab-appeals");
  const tabReports  = $("tab-reports");
  const liBtn       = $("li-btn");
  const regBtn      = $("reg-btn");
  const recoveryToggle = $("recovery-toggle");
  const resetRequestBtn = $("reset-request-btn");
  const resetConfirmBtn = $("reset-confirm-btn");
  const verifyRequestBtn = $("verify-request-btn");
  const verifyConfirmBtn = $("verify-confirm-btn");
  const captchaRefresh = $("captcha-refresh");
  const logoutBtn   = $("logout-btn");
  const bugReportOpenBtn = $("bug-report-open-btn");
  const bugReportSubmitBtn = $("bug-report-submit-btn");
  const bugReportCancelBtn = $("bug-report-cancel-btn");
  const notificationToggle = $("notification-toggle");
  const notificationReadAll = $("notification-read-all");
  const selfEditBtn = $("self-edit-btn");
  const adminRefresh = $("admin-refresh");
  const adminBulkApproveBtn = $("admin-bulk-approve");
  const adminBulkRejectBtn = $("admin-bulk-reject");
  const adminOpenAddBtn  = $("admin-open-add-user");
  const adminAddBtn  = $("admin-add-btn");
  const adminAddCancelBtn = $("admin-add-cancel");
  const auditRefresh = $("audit-refresh");
  const violRefresh  = $("violations-refresh");
  const governanceRefresh = $("governance-refresh");
  const governanceCreate = $("governance-create-proposal");
  const appealSubmit = $("appeal-submit-btn");
  const appealRefresh = $("appeal-refresh-btn");
  const reportRefresh = $("admin-reports-refresh");
  const adminAppealsBulkApproveBtn = $("admin-appeals-bulk-approve");
  const adminAppealsBulkRejectBtn = $("admin-appeals-bulk-reject");
  const adminReportsBulkApproveBtn = $("admin-reports-bulk-approve");
  const adminReportsBulkRejectBtn = $("admin-reports-bulk-reject");
  const settingsSave = $("settings-save-btn");
  const cloudDrivePolicySave = $("cloud-drive-policy-save-btn");
  const serverModeApply = $("server-mode-apply-btn");
  const healthRefresh = $("health-refresh-btn");
  const integrityRefresh = $("integrity-refresh-btn");
  const integrityRescan = $("integrity-rescan-btn");
  const integrityExport = $("integrity-export-btn");
  const integrityBulkApprove = $("integrity-bulk-approve-btn");
  const integrityBulkReject = $("integrity-bulk-reject-btn");
  const integrityBulkIgnore = $("integrity-bulk-ignore-btn");
  const integrityRepair = $("integrity-repair-btn");
  const restartBtn   = $("restart-server-btn");
  const securityCenterRefresh = $("security-center-refresh-btn");
  const securityControlsSave = $("security-controls-save-btn");
  const securityThresholdsSave = $("security-thresholds-save-btn");
  const securityModeApply = $("security-mode-apply-btn");
  const securityProfileSave = $("security-profile-save-btn");
  const editSaveBtn = $("user-edit-save");
  const editCancelBtn = $("user-edit-cancel");
  const avatarUploadBtn = $("edit-user-avatar-upload");
  const chatCreateBtn = $("chat-create-room-btn");
  const chatJoinBtn = $("chat-join-room-btn");
  const chatRefreshRoomBtn = $("chat-room-refresh-btn");
  const chatRefreshMsgBtn = $("chat-refresh-msg-btn");
  const chatSendBtn = $("chat-send-btn");
  const chatAttachmentUploadBtn = $("chat-attachment-upload-btn");
  const chatAttachmentExistingBtn = $("chat-attachment-existing-btn");
  const chatInput = $("chat-message-input");
  const dmCreateBtn = $("dm-create-thread-btn");
  const dmRefreshBtn = $("dm-refresh-btn");
  const dmSendBtn = $("dm-send-btn");
  const dmAttachmentUploadBtn = $("dm-attachment-upload-btn");
  const dmAttachmentExistingBtn = $("dm-attachment-existing-btn");
  const dmInput = $("dm-message-input");
  const dmBlockBtn = $("dm-block-user-btn");
  const communityAnnouncementBtn = $("community-announcement-submit");
  const communityAnnouncementOpenBtn = $("community-announcement-open-btn");
  const communityAnnouncementCancelBtn = $("community-announcement-cancel-btn");
  const announcementAttachmentUploadBtn = $("announcement-attachment-upload-btn");
  const announcementAttachmentExistingBtn = $("announcement-attachment-existing-btn");
  const communityCategoryCreateBtn = $("community-category-create-btn");
  const communityCategoryManagerOpenBtn = $("community-category-manager-open-btn");
  const communityCategoryManagerCloseBtn = $("community-category-manager-close-btn");
  const communityBoardRequestOpenBtn = $("community-board-request-open-btn");
  const communityBoardRequestCancelBtn = $("community-board-request-cancel-btn");
  const communityBoardRequestBtn = $("community-board-request-btn");
  const communityThreadCreateOpenBtn = $("community-thread-create-open-btn");
  const communityThreadCreateCancelBtn = $("community-thread-create-cancel-btn");
  const communityThreadSubmitBtn = $("community-thread-submit");
  const communityReplySubmitBtn = $("community-reply-submit");
  const communityThreadPrevBtn = $("community-thread-prev");
  const communityThreadNextBtn = $("community-thread-next");
  const communityThreadLockToggle = $("community-thread-lock-toggle");
  const communityThreadDeleteBtn = $("community-thread-delete-btn");
  const communityToolsToggleBtn = $("community-tools-toggle-btn");
  const communityReviewTabBtn = $("community-review-tab-btn");
  const communityBackBoardsBtn = $("community-back-boards-btn");
  const communityBackThreadsBtn = $("community-back-threads-btn");
  const communityBoardSearch = $("community-board-search");
  const communityThreadSearch = $("community-thread-search");
  const driveRefreshBtn = $("drive-refresh-btn");
  const driveUploadBtn = $("drive-upload-btn");
  const driveRemoteCapabilityBtn = $("drive-remote-capability-btn");
  const driveRemoteDownloadBtn = $("drive-remote-download-btn");
  const storageUploadBtn = $("storage-upload-btn");
  const storageRefreshBtn = $("storage-refresh-btn");
  const storageUploadFile = $("storage-upload-file");
  const storageFolderCreateBtn = $("storage-folder-create-btn");
  const storageOrganizeBtn = $("storage-organize-btn");
  const storageFolderMoveBtn = $("storage-folder-move-btn");
  const albumCreateBtn = $("album-create-btn");
  const comfyuiRefreshBtn = $("comfyui-refresh-btn");
  const comfyuiGenerateBtn = $("comfyui-generate-btn");
  const comfyuiSaveBtn = $("comfyui-save-btn");
  const comfyuiDiscardBtn = $("comfyui-discard-btn");
  const sidebarToggle = $("sidebar-toggle");
  const userEditOverlay = $("user-edit-overlay");
  const adminAddOverlay = $("admin-add-overlay");
  const bugReportOverlay = $("bug-report-overlay");

  if (tabLogin)    tabLogin.addEventListener("click",    () => showTab("login"));
  if (tabRegister) tabRegister.addEventListener("click", () => showTab("register"));
  if (tabModuleChat) tabModuleChat.addEventListener("click", () => switchModuleTab("chat"));
  if (tabModuleDm) tabModuleDm.addEventListener("click", () => switchModuleTab("dm"));
  if (tabModuleAnnouncements) tabModuleAnnouncements.addEventListener("click", () => switchModuleTab("announcements"));
  if (tabModuleCommunity) tabModuleCommunity.addEventListener("click", () => switchModuleTab("community"));
  if (tabModuleDrive) tabModuleDrive.addEventListener("click", () => switchModuleTab("drive"));
  if (tabModuleAlbums) tabModuleAlbums.addEventListener("click", () => switchModuleTab("albums"));
  if (tabModuleComfyui) tabModuleComfyui.addEventListener("click", () => switchModuleTab("comfyui"));
  if (tabModuleAppeals) tabModuleAppeals.addEventListener("click", () => switchModuleTab("appeals"));
  if (tabModuleAccounts) tabModuleAccounts.addEventListener("click", () => switchModuleTab("accounts"));
  if (tabModuleServer) tabModuleServer.addEventListener("click", () => switchModuleTab("server"));
  if (tabServerSecurity) tabServerSecurity.addEventListener("click", () => switchServerTab("security"));
  if (tabServerAudit) tabServerAudit.addEventListener("click", () => switchServerTab("audit"));
  if (tabServerHealth) tabServerHealth.addEventListener("click", () => switchServerTab("health"));
  if (tabServerIntegrity) tabServerIntegrity.addEventListener("click", () => switchServerTab("integrity"));
  if (tabServerSettings) tabServerSettings.addEventListener("click", () => switchServerTab("settings"));
  if (tabServerEnv) tabServerEnv.addEventListener("click", () => switchServerTab("env"));
  if (tabSettingsSecurity) tabSettingsSecurity.addEventListener("click", () => switchSettingsSection("security"));
  if (tabSettingsFeatures) tabSettingsFeatures.addEventListener("click", () => switchSettingsSection("features"));
  if (tabSettingsAppearance) tabSettingsAppearance.addEventListener("click", () => switchSettingsSection("appearance"));
  if (tabSettingsSystem) tabSettingsSystem.addEventListener("click", () => switchSettingsSection("system"));
  if (tabSettingsDrive) tabSettingsDrive.addEventListener("click", () => switchSettingsSection("drive"));
  if (tabSettingsMemberLevels) tabSettingsMemberLevels.addEventListener("click", () => switchSettingsSection("member-levels"));
  if (tabUsers)    tabUsers.addEventListener("click",    () => switchAdminTab("users"));
  if (tabViol)     tabViol.addEventListener("click",     () => switchAdminTab("violations"));
  if (tabGovernance) tabGovernance.addEventListener("click", () => switchAdminTab("governance"));
  if (tabAppeals)  tabAppeals.addEventListener("click",   () => switchAdminTab("appeals"));
  if (tabReports)  tabReports.addEventListener("click",   () => switchAdminTab("reports"));
  if (liBtn)       liBtn.addEventListener("click",        doLogin);
  if (regBtn)      regBtn.addEventListener("click",       doRegister);
  if (recoveryToggle) recoveryToggle.addEventListener("click", toggleRecoveryPanel);
  if (resetRequestBtn) resetRequestBtn.addEventListener("click", requestPasswordReset);
  if (resetConfirmBtn) resetConfirmBtn.addEventListener("click", confirmPasswordReset);
  if (verifyRequestBtn) verifyRequestBtn.addEventListener("click", requestEmailVerification);
  if (verifyConfirmBtn) verifyConfirmBtn.addEventListener("click", confirmEmailVerification);
  if (captchaRefresh) captchaRefresh.addEventListener("click", loadCaptchaChallenge);
  if (logoutBtn)  logoutBtn.addEventListener("click",    doLogout);
  if (bugReportOpenBtn) bugReportOpenBtn.addEventListener("click", showBugReportDialog);
  if (bugReportSubmitBtn) bugReportSubmitBtn.addEventListener("click", submitBugReport);
  if (bugReportCancelBtn) bugReportCancelBtn.addEventListener("click", hideBugReportDialog);
  if (notificationToggle) notificationToggle.addEventListener("click", toggleNotificationPanel);
  if (notificationReadAll) notificationReadAll.addEventListener("click", markAllNotificationsRead);
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
  if (chatAttachmentUploadBtn) chatAttachmentUploadBtn.addEventListener("click", uploadChatAttachment);
  if (chatAttachmentExistingBtn) chatAttachmentExistingBtn.addEventListener("click", attachExistingChatFile);
  if (dmCreateBtn) dmCreateBtn.addEventListener("click", createDmThread);
  if (dmRefreshBtn) dmRefreshBtn.addEventListener("click", loadDmThreads);
  if (dmSendBtn) dmSendBtn.addEventListener("click", sendDmMessage);
  if (dmAttachmentUploadBtn) dmAttachmentUploadBtn.addEventListener("click", uploadDmAttachment);
  if (dmAttachmentExistingBtn) dmAttachmentExistingBtn.addEventListener("click", attachExistingDmFile);
  if (dmBlockBtn) dmBlockBtn.addEventListener("click", blockSelectedDmUser);
  if (communityAnnouncementBtn) communityAnnouncementBtn.addEventListener("click", publishAnnouncement);
  if (communityAnnouncementOpenBtn) communityAnnouncementOpenBtn.addEventListener("click", () => toggleCommunityAnnouncementEditor(true));
  if (communityAnnouncementCancelBtn) communityAnnouncementCancelBtn.addEventListener("click", () => toggleCommunityAnnouncementEditor(false));
  if (announcementAttachmentUploadBtn) announcementAttachmentUploadBtn.addEventListener("click", uploadAnnouncementAttachmentRequest);
  if (announcementAttachmentExistingBtn) announcementAttachmentExistingBtn.addEventListener("click", attachExistingAnnouncementFile);
  if (communityCategoryCreateBtn) communityCategoryCreateBtn.addEventListener("click", createCommunityCategory);
  if (communityCategoryManagerOpenBtn) communityCategoryManagerOpenBtn.addEventListener("click", () => toggleCommunityCategoryManager(true));
  if (communityCategoryManagerCloseBtn) communityCategoryManagerCloseBtn.addEventListener("click", () => toggleCommunityCategoryManager(false));
  if (communityBoardRequestOpenBtn) communityBoardRequestOpenBtn.addEventListener("click", () => toggleCommunityBoardRequest(true));
  if (communityBoardRequestCancelBtn) communityBoardRequestCancelBtn.addEventListener("click", () => toggleCommunityBoardRequest(false));
  if (communityBoardRequestBtn) communityBoardRequestBtn.addEventListener("click", requestCommunityBoard);
  if (communityThreadCreateOpenBtn) communityThreadCreateOpenBtn.addEventListener("click", () => toggleCommunityThreadCreator(true));
  if (communityThreadCreateCancelBtn) communityThreadCreateCancelBtn.addEventListener("click", () => toggleCommunityThreadCreator(false));
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
  if (communityToolsToggleBtn) communityToolsToggleBtn.addEventListener("click", () => toggleCommunityTools());
  if (communityReviewTabBtn) communityReviewTabBtn.addEventListener("click", () => switchCommunityMode(communityMode === "review" ? "boards" : "review"));
  if (communityBackBoardsBtn) communityBackBoardsBtn.addEventListener("click", showCommunityBoardStage);
  if (communityBackThreadsBtn) communityBackThreadsBtn.addEventListener("click", showCommunityThreadStage);
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
  if (driveUploadBtn) driveUploadBtn.addEventListener("click", uploadDriveFile);
  if (driveRemoteCapabilityBtn) driveRemoteCapabilityBtn.addEventListener("click", loadRemoteDownloadCapabilities);
  if (driveRemoteDownloadBtn) driveRemoteDownloadBtn.addEventListener("click", startRemoteDriveDownload);
  if (storageUploadBtn) storageUploadBtn.addEventListener("click", openStorageUploadPicker);
  if (storageUploadFile) storageUploadFile.addEventListener("change", uploadStorageFile);
  if (storageRefreshBtn) storageRefreshBtn.addEventListener("click", loadDriveDashboard);
  if (storageFolderCreateBtn) storageFolderCreateBtn.addEventListener("click", createStorageFolder);
  if (storageOrganizeBtn) storageOrganizeBtn.addEventListener("click", organizeSelectedStorageFile);
  if (storageFolderMoveBtn) storageFolderMoveBtn.addEventListener("click", moveStorageFolder);
  if (albumCreateBtn) albumCreateBtn.addEventListener("click", createAlbum);
  if (comfyuiRefreshBtn) comfyuiRefreshBtn.addEventListener("click", loadComfyuiModels);
  if (comfyuiGenerateBtn) comfyuiGenerateBtn.addEventListener("click", generateComfyuiImage);
  if (comfyuiSaveBtn) comfyuiSaveBtn.addEventListener("click", saveComfyuiImageToDrive);
  if (comfyuiDiscardBtn) comfyuiDiscardBtn.addEventListener("click", discardComfyuiImage);
  if (sidebarToggle) sidebarToggle.addEventListener("click", () => {
    setSidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"));
  });
  const sidebarNav = $("module-main-tabs");
  if (sidebarNav) {
    sidebarNav.addEventListener("click", (event) => {
      const sub = event.target?.closest?.("[data-sidebar-action]");
      if (!sub) return;
      event.preventDefault();
      event.stopPropagation();
      runSidebarAction(sub.dataset.sidebarAction || "");
    });
  }
  if (editSaveBtn)   editSaveBtn.addEventListener("click", submitEditUser);
  if (editCancelBtn) editCancelBtn.addEventListener("click", hideUserEditDialog);
  if (avatarUploadBtn) avatarUploadBtn.addEventListener("click", uploadUserAvatar);
  if (userEditOverlay) userEditOverlay.addEventListener("click", (e) => {
    if (e.target === userEditOverlay) hideUserEditDialog();
  });
  if (adminAddOverlay) adminAddOverlay.addEventListener("click", (e) => {
    if (e.target === adminAddOverlay) hideAdminAddDialog();
  });
  if (bugReportOverlay) bugReportOverlay.addEventListener("click", (e) => {
    if (e.target === bugReportOverlay) hideBugReportDialog();
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      hideUserEditDialog();
      hideAdminAddDialog();
      hideBugReportDialog();
      closeNotificationPanel();
    }
  });
  if (chatInput) chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      sendChatMessage();
    }
  });
  if (dmInput) dmInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      sendDmMessage();
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
  if (governanceRefresh) governanceRefresh.addEventListener("click", loadGovernanceDashboard);
  if (governanceCreate) governanceCreate.addEventListener("click", createGovernanceProposal);
  if ($("governance-proposal-status")) $("governance-proposal-status").addEventListener("change", loadGovernanceProposals);

  // Settings
  if (settingsSave) settingsSave.addEventListener("click", saveSettings);
  if (cloudDrivePolicySave) cloudDrivePolicySave.addEventListener("click", saveCloudDriveAdminPolicy);
  if (serverModeApply) serverModeApply.addEventListener("click", applyServerMode);
  if (healthRefresh) healthRefresh.addEventListener("click", loadServerHealth);
  if (integrityRefresh) integrityRefresh.addEventListener("click", loadIntegrityGuard);
  if (integrityRescan) integrityRescan.addEventListener("click", rescanIntegrityGuard);
  if (integrityExport) integrityExport.addEventListener("click", exportIntegrityReport);
  if (integrityBulkApprove) integrityBulkApprove.addEventListener("click", () => reviewSelectedIntegrityFindings("approve"));
  if (integrityBulkReject) integrityBulkReject.addEventListener("click", () => reviewSelectedIntegrityFindings("reject"));
  if (integrityBulkIgnore) integrityBulkIgnore.addEventListener("click", () => reviewSelectedIntegrityFindings("ignore"));
  if (integrityRepair) integrityRepair.addEventListener("click", repairIntegrityChains);
  if (restartBtn)   restartBtn.addEventListener("click",   restartServer);
  if (securityCenterRefresh) securityCenterRefresh.addEventListener("click", loadSecurityCenter);
  if (securityControlsSave) securityControlsSave.addEventListener("click", saveSecurityCenterControls);
  if (securityThresholdsSave) securityThresholdsSave.addEventListener("click", saveSecurityThresholds);
  if (securityModeApply) securityModeApply.addEventListener("click", applySecurityMode);
  if (securityProfileSave) securityProfileSave.addEventListener("click", saveSecurityProfile);
}

$("li-pw").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doLogin();
});
$("reg-pw").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doRegister();
});
setupPwToggle("reset-new-pw", "reset-new-pw-toggle");
setupPwToggle("reset-new-pw-confirm", "reset-new-pw-confirm-toggle");

(async function init() {
  await loadSiteConfig();
  try {
    startClock();
  } catch (err) {
    console.error("clock bootstrap failed", err);
  }
  setupInactivityTracking();
  startServerConnectionMonitor();
  _csrfToken = readCookie("csrf_token");
  bindUiEvents();
  if (typeof loadCaptchaChallenge === "function") loadCaptchaChallenge();
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
