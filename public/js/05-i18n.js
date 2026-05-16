'use strict';

(function setupHackmeI18n() {
  const STORAGE_KEY = 'hackme_web.locale';
  const DEFAULT_LOCALE = 'zh-TW';
  const SUPPORTED_LOCALES = Object.freeze({
    'zh-TW': '繁體中文',
    en: 'English',
  });
  const ATTRIBUTE_NAMES = ['placeholder', 'title', 'aria-label', 'alt'];
  const SKIP_SELECTOR = [
    'script',
    'style',
    'template',
    'pre',
    'code',
    '[data-i18n-skip]',
    '[contenteditable="true"]',
    '.markdown-body',
    '.drive-preview-text',
    '.drive-code-preview',
    '.chat-message-body',
    '.chat-message-content',
    '.community-post-content',
    '.community-thread-body',
    '.video-description',
    '.profile-bio',
  ].join(',');

  const KEY_TEXT = Object.freeze({
    'app.title': { 'zh-TW': 'hackme_web — 登入系統', en: 'hackme_web — Login System' },
    'tradingWorkflow.title': { 'zh-TW': '交易 Workflow 編輯器', en: 'Trading Workflow Editor' },
    'comfyuiWorkflow.title': { 'zh-TW': 'ComfyUI Workflow 視覺編輯器', en: 'ComfyUI Workflow Visual Builder' },
    'language.label': { 'zh-TW': '語言', en: 'Language' },
    'language.changed': { 'zh-TW': '語言已切換', en: 'Language changed' },
  });

  const EN_TEXT = Object.freeze({
    '語言': 'Language',
    '繁體中文': 'Traditional Chinese',
    '簡單的帳號註冊與登入系統': 'Simple account registration and login',
    '檢查伺服器狀態中': 'Checking server status',
    '登入': 'Log in',
    '註冊': 'Register',
    '帳號': 'Username',
    '密碼': 'Password',
    '請輸入帳號': 'Enter username',
    '請輸入密碼': 'Enter password',
    '顯示密碼': 'Show password',
    '內測 token（內測模式才需要）': 'Internal test token (required only in internal test mode)',
    'root 提供的內測 token': 'Internal test token from root',
    '忘記密碼 / Email 驗證': 'Forgot password / Email verification',
    '帳號或 Email': 'Username or email',
    '送出重設密碼審核': 'Request password reset review',
    '寄送 Email 驗證碼': 'Send email verification code',
    '重設密碼驗證碼': 'Password reset code',
    '請輸入驗證碼': 'Enter verification code',
    '新密碼': 'New password',
    '請輸入新密碼': 'Enter new password',
    '確認新密碼': 'Confirm new password',
    '請再次輸入新密碼': 'Enter the new password again',
    '重設密碼': 'Reset password',
    'Email 驗證碼': 'Email verification code',
    '完成 Email 驗證': 'Complete email verification',
    '選擇一個帳號（3 字以上）': 'Choose a username (at least 3 characters)',
    '請設定密碼': 'Set a password',
    '確認密碼': 'Confirm password',
    '請再次輸入密碼': 'Enter password again',
    '暱稱': 'Display name',
    'Email（選填，用於重設密碼與驗證）': 'Email (optional, for password reset and verification)',
    '真實姓名（選填）': 'Real name (optional)',
    '可留空': 'Optional',
    '生日（選填）': 'Birthday (optional)',
    '電話（選填）': 'Phone (optional)',
    '09xx-xxx-xxx，可留空': '09xx-xxx-xxx, optional',
    '驗證碼': 'Verification code',
    '請輸入答案': 'Enter answer',
    '重新取得': 'Refresh',
    '發佈號: loading...': 'Release: loading...',
    '密碼強度要求：': 'Password strength requirements:',
    '至少 8 個字元': 'At least 8 characters',
    '包含大寫字母（A–Z）': 'Contains uppercase letters (A-Z)',
    '包含小寫字母（a–z）': 'Contains lowercase letters (a-z)',
    '包含符號（!@#$%…）': 'Contains symbols (!@#$%...)',
    '恭喜登入成功': 'Login successful',
    '歡迎回來！': 'Welcome back!',
    '未登入': 'Not signed in',
    '閒置登出：--:--': 'Idle logout: --:--',
    '快速操作': 'Quick actions',
    '修改資料': 'Edit profile',
    '切換淺色模式': 'Switch to light mode',
    '切換夜色模式': 'Switch to night mode',
    '通知': 'Notifications',
    '通知中心': 'Notification Center',
    '全部已讀': 'Mark all read',
    '尚未載入通知': 'Notifications have not loaded yet',
    '回報 Bug': 'Report bug',
    '登出': 'Log out',
    '主要功能': 'Main features',
    '收合側邊欄': 'Collapse sidebar',
    '開啟個人面板': 'Open profile panel',
    '聊天': 'Chat',
    '個人面板': 'Profile',
    '公告': 'Announcements',
    '討論區': 'Forum',
    '雲端硬碟': 'Cloud Drive',
    '相簿': 'Albums',
    '影音': 'Videos',
    '遊戲區': 'Games',
    'AI 產圖': 'AI Images',
    '積分系統': 'Points',
    '積分交易所': 'Points Exchange',
    '申覆': 'Appeals',
    '任務中心': 'Job Center',
    '分享管理': 'Share Management',
    '帳號管理': 'Account Management',
    '安全中心': 'Security Center',
    '日常': 'Daily',
    '社群': 'Community',
    '工具': 'Tools',
    '管理': 'Management',
    '我的主頁': 'My Profile',
    '編輯資料': 'Edit Profile',
    '好友': 'Friends',
    '重新整理': 'Refresh',
    '重新整理聊天室': 'Refresh rooms',
    '建立聊天室': 'Create room',
    '加入聊天室': 'Join room',
    '快速私聊對象': 'Quick DM target',
    '帳號，可留空': 'Username, optional',
    '聊天室名稱': 'Room name',
    '最多 48 字': 'Up to 48 characters',
    '建立時加入成員': 'Add members on create',
    '帳號，逗號分隔': 'Usernames, comma-separated',
    '加入密碼': 'Join password',
    '允許匿名': 'Allow anonymous',
    '我在此群匿名': 'Join this group anonymously',
    '關閉': 'Close',
    '取消': 'Cancel',
    '聊天室 ID': 'Room ID',
    '例如 12': 'Example: 12',
    '聊天室密碼': 'Room password',
    '若有密碼才需填寫': 'Required only if the room has a password',
    '若允許，以匿名加入': 'Join anonymously if allowed',
    '好友帳號': 'Friend username',
    '加好友': 'Add friend',
    '邀請成員（帳號，逗號分隔）': 'Invite members (usernames, comma-separated)',
    '邀請': 'Invite',
    '備份聊天記錄': 'Export chat history',
    '輸入訊息，最多 500 字': 'Type a message, up to 500 characters',
    '送出': 'Send',
    '上傳附件': 'Upload attachment',
    '微笑': 'Smile',
    '感謝': 'Thanks',
    '了解': 'Got it',
    '驚訝': 'Surprised',
    '加油': 'Cheer',
    '難過': 'Sad',
    '重新整理訊息': 'Refresh messages',
    '好友代碼': 'Friend code',
    '複製好友代碼': 'Copy friend code',
    '重新產生': 'Regenerate',
    '儲存資料': 'Save profile',
    '帳號設定': 'Account settings',
    '個人外觀': 'Personal appearance',
    '外觀模板': 'Appearance template',
    '快速色系': 'Quick color mode',
    '夜色': 'Night',
    '淺色': 'Light',
    '自訂色盤': 'Custom palette',
    '保留自訂色盤': 'Keep custom palette',
    '加入好友': 'Add friend',
    '好友 username 或 user id': 'Friend username or user ID',
    '送出申請': 'Send request',
    '收到的申請': 'Incoming requests',
    '送出的申請': 'Sent requests',
    '分享連結': 'Share links',
    '我的影音': 'My videos',
    '發布公告': 'Publish announcement',
    '公告標題': 'Announcement title',
    '公告內容': 'Announcement content',
    '輸入公告內容': 'Enter announcement content',
    '置頂公告': 'Pin announcement',
    '公告 ID': 'Announcement ID',
    '上傳新附件': 'Upload new attachment',
    '選擇雲端檔案': 'Choose cloud file',
    '請先選擇雲端檔案': 'Select a cloud file first',
    '理由': 'Reason',
    '附件用途': 'Attachment purpose',
    '上傳並送審': 'Upload and submit for review',
    '既有檔送審': 'Submit existing file for review',
    '工具': 'Tools',
    '審核': 'Review',
    '申請建立討論區': 'Request forum board',
    '管理分類': 'Manage categories',
    '收起': 'Collapse',
    '討論分類': 'Forum category',
    '討論區名稱': 'Board name',
    '例如：遊戲交流區': 'Example: Game discussion',
    '討論區說明': 'Board description',
    '說明討論主題、規則與用途': 'Describe topics, rules, and purpose',
    '版規': 'Board rules',
    '例如：禁止人身攻擊、禁止外流個資、禁止洗版': 'Example: No personal attacks, doxxing, or spam',
    '可見性': 'Visibility',
    '排序': 'Sort order',
    '新增分類': 'Add category',
    '分類名稱': 'Category name',
    '例如：公告討論、技術交流': 'Example: Announcements, tech talk',
    '分類說明': 'Category description',
    '分類用途說明': 'Describe this category',
    '搜尋討論區': 'Search boards',
    '搜尋名稱、說明、版主': 'Search name, description, moderators',
    '返回討論區': 'Back to boards',
    '撰寫新主題': 'New thread',
    '版主設定': 'Moderator settings',
    '選擇版主帳號': 'Select moderator account',
    '常用權限組': 'Permission preset',
    '審核主題': 'Review threads',
    '置頂主題': 'Pin thread',
    '置頂留言': 'Pin replies',
    '鎖定主題': 'Lock thread',
    '編輯留言': 'Edit replies',
    '刪除主題或留言': 'Delete threads or replies',
    '獎勵作者': 'Reward authors',
    '懲處違規留言': 'Penalize violating replies',
    '新增 / 更新版主': 'Add / update moderator',
    '新主題標題': 'New thread title',
    '輸入主題標題': 'Enter thread title',
    '內容': 'Content',
    '輸入主題內容': 'Enter thread content',
    '發布主題': 'Publish thread',
    '搜尋主題、內容、作者': 'Search threads, content, authors',
    '上一頁': 'Previous',
    '下一頁': 'Next',
    '返回主題列表': 'Back to thread list',
    '刪除主題': 'Delete thread',
    '留言回覆': 'Reply',
    '輸入回覆內容': 'Enter reply',
    '送出留言': 'Send reply',
    '刷新申覆': 'Refresh appeals',
    '雲端硬碟分頁': 'Cloud Drive tabs',
    '檔案管理': 'Files',
    '容量管理': 'Capacity',
    '雲端硬碟容量使用率': 'Cloud Drive capacity usage',
    '雲端硬碟用量': 'Cloud Drive usage',
    '選購方案': 'Choose plan',
    '重新整理雲端硬碟狀態': 'Refresh Cloud Drive status',
    '選擇 .torrent': 'Choose .torrent',
    '+ 資料夾': '+ Folder',
    '新增文檔': 'New document',
    '上傳檔案': 'Upload file',
    '上傳資料夾': 'Upload folder',
    'BT / .torrent': 'BT / .torrent',
    '移動資料夾': 'Move folder',
    '全部還原': 'Restore all',
    '清空': 'Clear',
    '預覽': 'Preview',
    '刷新': 'Refresh',
    '智慧整理方式': 'Smart organization mode',
    '智慧整理': 'Smart organize',
    '相簿名稱': 'Album name',
    '我的相簿': 'My album',
    '描述': 'Description',
    '旅行、專案、公開素材...': 'Travel, projects, public assets...',
    '分享密碼（選填）': 'Share password (optional)',
    '持連結可看時生效': 'Applies when link access is enabled',
    '建立': 'Create',
    '分享密碼': 'Share password',
    '留空不變，輸入新密碼可更新': 'Leave blank to keep current, enter a new password to update',
    '儲存': 'Save',
    '預覽圖大小': 'Thumbnail size',
    '已完成複製': 'Copied',
    '連結已複製': 'Link copied',
    '請先登入': 'Please log in first',
    '載入中': 'Loading',
    '讀取中': 'Loading',
    '同步中': 'Syncing',
    '處理中': 'Processing',
    '準備中': 'Preparing',
    '完成': 'Done',
    '失敗': 'Failed',
    '成功': 'Success',
    '錯誤': 'Error',
    '警告': 'Warning',
    '正常': 'Normal',
    '啟用': 'Enabled',
    '停用': 'Disabled',
    '開啟': 'Open',
    '編輯': 'Edit',
    '刪除': 'Delete',
    '查看': 'View',
    '複製': 'Copy',
    '更新': 'Update',
    '新增': 'Add',
    '搜尋': 'Search',
    '狀態': 'Status',
    '設定': 'Settings',
    '原因': 'Reason',
    '說明': 'Description',
    '名稱': 'Name',
    '角色': 'Role',
    '等級': 'Level',
    '權限': 'Permissions',
    '建立可回測、可執行的節點式交易策略；儲存後回交易頁載入。': 'Build node-based trading strategies that can be backtested and executed; save them and return to the trading page to load.',
    '用節點與線建立 ComfyUI workflow；從綠色 output 拉到紫色 input，完成後回主頁保存。': 'Build a ComfyUI workflow with nodes and links; connect green outputs to purple inputs, then return to the main page to save.',
    '載入範例': 'Load example',
    '套用 JSON': 'Apply JSON',
    '複製 JSON': 'Copy JSON',
    '節點工具箱': 'Node toolbox',
    'Graph 節點': 'Graph nodes',
    '條件節點': 'Condition nodes',
    '節點屬性': 'Node properties',
    '回測預覽': 'Backtest preview',
    '開始時間': 'Start time',
    '結束時間': 'End time',
    '執行回測預覽': 'Run backtest preview',
    '最近 180 天': 'Last 180 days',
    '最近 365 天': 'Last 365 days',
    '可讀 JSON': 'Readable JSON',
    '重新排列節點': 'Auto layout nodes',
    '匯入 JSON': 'Import JSON',
    '送回主頁': 'Send back to main page',
    '下載 ComfyUI Workflow': 'Download ComfyUI Workflow',
    '下載 API Prompt': 'Download API Prompt',
    '下載本站 Preset': 'Download site preset',
    '複製 ComfyUI Workflow': 'Copy ComfyUI Workflow',
    '搜尋節點': 'Search nodes',
    '目前 ComfyUI 節點': 'Current ComfyUI nodes',
    '依賴 / 驗證': 'Dependencies / validation',
    '連線': 'Connections',
    '未選取': 'None selected',
    '本站 preset/layout JSON': 'Site preset/layout JSON',
    '例如 checkpoint、inpaint、upscale、control': 'Example: checkpoint, inpaint, upscale, control',
  });

  let currentLocale = normalizeLocale(readStoredLocale());
  let observer = null;
  let applying = false;
  let pendingRoots = new Set();
  let pendingFrame = null;

  function readStoredLocale() {
    try {
      return localStorage.getItem(STORAGE_KEY) || DEFAULT_LOCALE;
    } catch (err) {
      return DEFAULT_LOCALE;
    }
  }

  function normalizeLocale(value) {
    const raw = String(value || '').trim();
    const lower = raw.toLowerCase();
    if (lower === 'en' || lower.startsWith('en-')) return 'en';
    if (lower === 'zh' || lower === 'zh-tw' || lower === 'zh-hant' || lower === 'zh-hk') return 'zh-TW';
    return DEFAULT_LOCALE;
  }

  function translateKey(key, vars = null) {
    const entry = KEY_TEXT[String(key || '')];
    const text = entry ? (entry[currentLocale] || entry[DEFAULT_LOCALE] || '') : '';
    return interpolate(text || String(key || ''), vars);
  }

  function translateSourceText(source) {
    return translateSourceTextForLocale(source, currentLocale);
  }

  function translateSourceTextForLocale(source, locale) {
    const value = String(source ?? '');
    if (locale === DEFAULT_LOCALE) return value;
    return EN_TEXT[value] || value;
  }

  function interpolate(text, vars = null) {
    if (!vars || typeof vars !== 'object') return text;
    return String(text || '').replace(/\{([a-zA-Z0-9_]+)\}/g, (_match, key) => (
      Object.prototype.hasOwnProperty.call(vars, key) ? String(vars[key]) : ''
    ));
  }

  function translatedPreservingWhitespace(source) {
    return translatedPreservingWhitespaceForLocale(source, currentLocale);
  }

  function translatedPreservingWhitespaceForLocale(source, locale) {
    const raw = String(source ?? '');
    const match = raw.match(/^(\s*)([\s\S]*?)(\s*)$/);
    if (!match) return translateSourceTextForLocale(raw, locale);
    return `${match[1]}${translateSourceTextForLocale(match[2], locale)}${match[3]}`;
  }

  function isKnownRenderedText(current, source) {
    return Object.keys(SUPPORTED_LOCALES).some((locale) => (
      current === translatedPreservingWhitespaceForLocale(source, locale)
    ));
  }

  function isKnownRenderedAttribute(current, source) {
    return Object.keys(SUPPORTED_LOCALES).some((locale) => (
      current === translateSourceTextForLocale(source, locale)
    ));
  }

  function shouldSkipElement(element) {
    return !element || Boolean(element.closest?.(SKIP_SELECTOR));
  }

  function scopedElementRoot(root) {
    if (!root || root === document || root.nodeType === Node.DOCUMENT_NODE) return document;
    if (root.nodeType === Node.ELEMENT_NODE) return root;
    return null;
  }

  function shouldSkipTextNode(node) {
    const parent = node?.parentElement;
    if (!parent || shouldSkipElement(parent)) return true;
    if (parent.closest?.('textarea,input')) return true;
    if (parent.closest?.('[data-i18n]')) return true;
    const trimmed = String(node.nodeValue || '').trim();
    if (!trimmed) return true;
    return !Object.prototype.hasOwnProperty.call(EN_TEXT, trimmed) && !node.__hackmeI18nSourceText;
  }

  function translateTextNode(node) {
    if (shouldSkipTextNode(node)) return;
    const current = String(node.nodeValue || '');
    const existingSource = node.__hackmeI18nSourceText;
    let source = existingSource;
    if (!source || !isKnownRenderedText(current, source)) {
      source = current;
      node.__hackmeI18nSourceText = source;
    }
    const next = translatedPreservingWhitespace(source);
    if (current !== next) node.nodeValue = next;
  }

  function attrStoreName(attr) {
    return `hackmeI18nSource${attr.replace(/[^a-z0-9]/gi, '_')}`;
  }

  function translateAttribute(element, attr) {
    if (!element || shouldSkipElement(element) || !element.hasAttribute(attr)) return;
    const current = element.getAttribute(attr) || '';
    const trimmed = current.trim();
    const store = attrStoreName(attr);
    const existingSource = element.dataset[store] || '';
    if (!existingSource && !Object.prototype.hasOwnProperty.call(EN_TEXT, trimmed)) return;
    let source = existingSource;
    if (!source || !isKnownRenderedAttribute(current, source)) {
      source = current;
      element.dataset[store] = source;
    }
    const next = translateSourceText(source);
    if (current !== next) element.setAttribute(attr, next);
  }

  function applyExplicitTranslations(root) {
    const scope = scopedElementRoot(root);
    if (!scope) return;
    const elements = [];
    if (root?.nodeType === Node.ELEMENT_NODE && root.matches?.('[data-i18n]')) elements.push(root);
    elements.push(...scope.querySelectorAll('[data-i18n]'));
    elements.forEach((element) => {
      const key = element.getAttribute('data-i18n');
      if (!key) return;
      element.textContent = translateKey(key);
    });
  }

  function translateAttributes(root) {
    const scope = scopedElementRoot(root);
    if (!scope) return;
    const elements = [];
    if (root?.nodeType === Node.ELEMENT_NODE) elements.push(root);
    elements.push(...scope.querySelectorAll(ATTRIBUTE_NAMES.map((attr) => `[${attr}]`).join(',')));
    elements.forEach((element) => {
      ATTRIBUTE_NAMES.forEach((attr) => translateAttribute(element, attr));
    });
  }

  function translateTextNodes(root) {
    const start = root || document.body;
    if (!start) return;
    if (start.nodeType === Node.TEXT_NODE) {
      translateTextNode(start);
      return;
    }
    if (start.nodeType !== Node.ELEMENT_NODE && start.nodeType !== Node.DOCUMENT_NODE) return;
    const walker = document.createTreeWalker(start, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        return shouldSkipTextNode(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      },
    });
    while (walker.nextNode()) translateTextNode(walker.currentNode);
  }

  function syncLanguageControls(root = document) {
    const scope = scopedElementRoot(root);
    if (!scope) return;
    const controls = [];
    if (root?.nodeType === Node.ELEMENT_NODE && root.matches?.('[data-language-select]')) controls.push(root);
    controls.push(...scope.querySelectorAll('[data-language-select]'));
    controls.forEach((select) => {
      if (!select.dataset.i18nBound) {
        select.dataset.i18nBound = '1';
        select.addEventListener('change', () => setLocale(select.value, { announce: true }));
      }
      select.value = currentLocale;
      const zh = select.querySelector('option[value="zh-TW"]');
      const en = select.querySelector('option[value="en"]');
      if (zh) zh.textContent = currentLocale === 'en' ? 'Traditional Chinese' : '繁體中文';
      if (en) en.textContent = 'English';
    });
  }

  function applyI18n(root = document) {
    if (!document.body) return;
    const isWholeDocument = root === document || root?.nodeType === Node.DOCUMENT_NODE;
    applying = true;
    try {
      if (isWholeDocument) {
        document.documentElement.lang = currentLocale;
        const titleKey = document.documentElement.dataset.i18nTitle || document.body?.dataset.i18nTitle || 'app.title';
        document.title = translateKey(titleKey);
      }
      if (root?.nodeType === Node.TEXT_NODE) {
        translateTextNode(root);
        return;
      }
      syncLanguageControls(root);
      applyExplicitTranslations(root);
      translateAttributes(root);
      translateTextNodes(root);
      if (isWholeDocument) document.body.dataset.locale = currentLocale;
    } finally {
      applying = false;
    }
  }

  function queueApply(root) {
    if (applying || !root) return;
    pendingRoots.add(root);
    if (pendingFrame) return;
    pendingFrame = requestAnimationFrame(() => {
      const roots = Array.from(pendingRoots);
      pendingRoots.clear();
      pendingFrame = null;
      roots.forEach((item) => applyI18n(item));
    });
  }

  function startObserver() {
    if (observer || !document.body) return;
    observer = new MutationObserver((mutations) => {
      if (applying) return;
      mutations.forEach((mutation) => {
        if (mutation.type === 'childList') {
          mutation.addedNodes.forEach((node) => queueApply(node));
          return;
        }
        if (mutation.type === 'characterData') {
          queueApply(mutation.target);
          return;
        }
        if (mutation.type === 'attributes') {
          queueApply(mutation.target);
        }
      });
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ATTRIBUTE_NAMES,
    });
  }

  function setLocale(locale, options = {}) {
    const next = normalizeLocale(locale);
    currentLocale = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch (err) {}
    applyI18n(document);
    document.dispatchEvent(new CustomEvent('hackme:locale-changed', { detail: { locale: next } }));
    if (options.announce && typeof window.showAppToast === 'function') {
      window.showAppToast(translateKey('language.changed'), true, { duration: 1200 });
    }
  }

  function init() {
    syncLanguageControls(document);
    applyI18n(document);
    startObserver();
  }

  window.HackmeI18n = {
    supportedLocales: SUPPORTED_LOCALES,
    getLocale: () => currentLocale,
    setLocale,
    t: translateKey,
    text: translateSourceText,
    apply: applyI18n,
  };
  window.t = translateKey;
  window.translateUiText = translateSourceText;
  window.setAppLocale = setLocale;
  window.getAppLocale = () => currentLocale;
  window.applyI18n = applyI18n;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
