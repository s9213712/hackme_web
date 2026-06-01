/*
 * Compatibility shell.
 * The canonical server-mode and launch-check implementation lives in 50-admin.js.
 * Keeping duplicated global function declarations here caused 51-admin-server-mode-launch-check.js
 * to override newer 50-admin.js behavior because index.html loads this file later.
 */
window.HACKME_SERVER_MODE_LAUNCH_CHECK_MODULE = "50-admin.js";
