'use strict';

let gameSelectedMatchId = null;
let gameSelectedSquare = null;
let gameState = { matches: [], invites: [], leaderboard: [] };
const CHESS_PIECES = {
  K: "♔", Q: "♕", R: "♖", B: "♗", N: "♘", P: "♙",
  k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟",
};

function setGameMsg(text, ok) {
  const el = $("game-msg");
  if (!el) return;
  el.textContent = text || "";
  el.className = text ? "msg show " + (ok ? "ok" : "err") : "msg";
}

function gameRequestNeedsFreshCsrf(json, res) {
  return res.status === 403 && String(json?.msg || "").toUpperCase().includes("CSRF");
}

async function gameRequest(path, { method = "GET", body = null } = {}) {
  const upperMethod = String(method || "GET").toUpperCase();
  const mutates = upperMethod !== "GET";
  const buildOptions = async () => {
    const csrf = await fetchCsrfToken({ force: mutates });
    const headers = { "X-CSRF-Token": csrf || "" };
    if (mutates) headers["Content-Type"] = "application/json";
    return {
      method: upperMethod,
      credentials: "same-origin",
      cache: "no-store",
      headers,
      body: body ? JSON.stringify(body) : undefined,
    };
  };

  let res = await fetch(API + path, await buildOptions());
  let json = await res.json().catch(() => ({}));
  if (gameRequestNeedsFreshCsrf(json, res)) {
    await fetchCsrfToken({ force: true });
    res = await fetch(API + path, await buildOptions());
    json = await res.json().catch(() => ({}));
  }
  if (!res.ok || !json.ok) {
    throw new Error(json.msg || `HTTP ${res.status}`);
  }
  if (mutates && typeof _csrfToken !== "undefined") {
    _csrfToken = null;
  }
  return json;
}

function renderGameCatalog(games) {
  const wrap = $("game-catalog-list");
  if (!wrap) return;
  const rows = Array.isArray(games) ? games : [];
  wrap.innerHTML = rows.map((game) => `
    <button class="game-catalog-item active" type="button" disabled>
      <span class="game-catalog-icon">♟</span>
      <span><strong>${sanitize(game.title || "西洋棋")}</strong><small>${game.supports_computer ? "玩家對戰 / 電腦練習" : "玩家對戰"}</small></span>
    </button>
  `).join("") || "<p style=\"color:var(--muted);\">尚未開放遊戲</p>";
}

function renderGameUsers(users) {
  const select = $("game-invite-user");
  if (!select) return;
  const rows = Array.isArray(users) ? users : [];
  if (!rows.length) {
    select.innerHTML = '<option value="">目前沒有可邀請玩家</option>';
    return;
  }
  select.innerHTML = '<option value="">選擇玩家</option>' + rows.map((user) => (
    `<option value="${sanitize(user.username || "")}">${sanitize(user.username || "")} · ${sanitize(user.role || "user")}</option>`
  )).join("");
}

function renderGameInvites(invites) {
  const wrap = $("game-invite-list");
  if (!wrap) return;
  const rows = Array.isArray(invites) ? invites : [];
  if (!rows.length) {
    wrap.innerHTML = "<p style=\"color:var(--muted);\">目前沒有邀請</p>";
    return;
  }
  wrap.innerHTML = rows.map((invite) => {
    const incoming = invite.opponent_username === currentUser;
    const title = incoming ? `${invite.inviter_username} 邀請你對戰` : `邀請 ${invite.opponent_username}`;
    const actions = invite.status === "pending" && incoming
      ? `<button class="btn game-mini-btn btn-primary" type="button" data-game-invite="${invite.id}" data-game-invite-action="accept">接受</button>
         <button class="btn game-mini-btn" type="button" data-game-invite="${invite.id}" data-game-invite-action="reject">拒絕</button>`
      : invite.status === "pending"
        ? `<button class="btn game-mini-btn" type="button" data-game-invite="${invite.id}" data-game-invite-action="cancel">取消</button>`
        : "";
    return `
      <div class="drive-file-row game-list-row">
        <div><strong>${sanitize(title)}</strong><small>${sanitize(invite.status)} · ${sanitize(formatChatTime(invite.created_at))}</small></div>
        <div class="drive-file-actions">${actions}</div>
      </div>
    `;
  }).join("");
}

function gameMatchLabel(match) {
  const side = match.my_side === "black" ? "黑方" : "白方";
  const opponentName = match.my_side === "black" ? match.white_username : match.black_username;
  return `${side} vs ${opponentName || "電腦"}`;
}

function renderGameMatches(matches) {
  const wrap = $("game-match-list");
  if (!wrap) return;
  const rows = Array.isArray(matches) ? matches : [];
  if (!gameSelectedMatchId && rows.length) {
    gameSelectedMatchId = rows[0].id;
  }
  if (!rows.length) {
    wrap.innerHTML = "<p style=\"color:var(--muted);\">還沒有棋局</p>";
    renderChessBoard(null);
    return;
  }
  wrap.innerHTML = rows.map((match) => `
    <button class="game-match-row ${match.id === gameSelectedMatchId ? "active" : ""}" type="button" data-game-match-id="${match.id}">
      <span><strong>${sanitize(gameMatchLabel(match))}</strong><small>${sanitize(match.status)} · ${sanitize(match.current_turn === "white" ? "白方走" : "黑方走")}</small></span>
      <span>${match.mode === "computer" ? "練習" : "對戰"}</span>
    </button>
  `).join("");
  const selected = rows.find((match) => match.id === gameSelectedMatchId) || rows[0];
  if (selected) {
    gameSelectedMatchId = selected.id;
    renderChessBoard(selected);
  }
}

function renderChessBoard(match) {
  const board = $("chess-board");
  const title = $("game-current-title");
  const status = $("game-current-status");
  const history = $("game-move-history");
  const resign = $("game-resign-btn");
  if (!board) return;
  if (!match) {
    board.innerHTML = "<div class=\"chess-empty\">尚未選擇棋局</div>";
    if (title) title.textContent = "尚未選擇棋局";
    if (status) status.textContent = "選擇棋局後即可走棋";
    if (history) history.innerHTML = "";
    if (resign) resign.style.display = "none";
    return;
  }
  const boardMap = match.board || {};
  if (title) title.textContent = gameMatchLabel(match);
  const myTurn = match.status === "active" && match.my_side === match.current_turn;
  if (status) {
    if (match.status !== "active") {
      status.textContent = match.winner_username ? `已結束，勝者：${match.winner_username}` : `已結束：${match.result_reason || "平手"}`;
    } else {
      status.textContent = myTurn ? "輪到你走棋" : `等待${match.current_turn === "white" ? "白方" : "黑方"}走棋`;
    }
  }
  if (resign) resign.style.display = match.status === "active" ? "" : "none";
  const legalTargets = new Set((match.legal_moves || [])
    .filter((move) => move.from === gameSelectedSquare)
    .map((move) => move.to));
  const squares = [];
  for (let rank = 8; rank >= 1; rank -= 1) {
    for (const file of "abcdefgh") {
      const square = file + rank;
      const piece = boardMap[square] || "";
      const isDark = (file.charCodeAt(0) + rank) % 2 === 0;
      const selectable = match.status === "active" && piece && ((match.my_side === "white" && piece === piece.toUpperCase()) || (match.my_side === "black" && piece === piece.toLowerCase()));
      squares.push(`
        <button class="chess-square ${isDark ? "dark" : "light"} ${square === gameSelectedSquare ? "selected" : ""} ${legalTargets.has(square) ? "target" : ""}"
                type="button" data-chess-square="${square}" ${match.status !== "active" ? "disabled" : ""}>
          <span>${sanitize(CHESS_PIECES[piece] || "")}</span>
          <small>${selectable || legalTargets.has(square) ? sanitize(square) : ""}</small>
        </button>
      `);
    }
  }
  board.innerHTML = squares.join("");
  if (history) {
    const moves = Array.isArray(match.move_history) ? match.move_history : [];
    history.innerHTML = moves.length
      ? moves.slice(-16).map((move, index) => `<span>${moves.length - 16 + index + 1 > 0 ? moves.length - 16 + index + 1 : index + 1}. ${sanitize(move.from)}→${sanitize(move.to)}${move.computer ? " · CPU" : ""}</span>`).join("")
      : "<span style=\"color:var(--muted);\">尚未走棋</span>";
  }
}

function renderGameLeaderboard(data) {
  const wrap = $("game-leaderboard-list");
  if (!wrap) return;
  const rows = Array.isArray(data?.leaderboard) ? data.leaderboard : [];
  if (!rows.length) {
    wrap.innerHTML = "<p style=\"color:var(--muted);\">本週尚無玩家對戰成績</p>";
    return;
  }
  wrap.innerHTML = rows.map((row) => `
    <div class="drive-file-row game-list-row">
      <div><strong>#${row.rank} ${sanitize(row.username || "-")}</strong><small>${row.wins || 0} 勝 · ${row.draws || 0} 和 · ${row.losses || 0} 敗</small></div>
      <strong>${row.score || 0}</strong>
    </div>
  `).join("");
}

async function loadGameZone() {
  try {
    await fetchCsrfToken({ force: true });
    const [catalog, usersJson, invitesJson, matchesJson, leaderboardJson] = await Promise.all([
      gameRequest("/games/catalog"),
      gameRequest("/games/users"),
      gameRequest("/games/chess/invites"),
      gameRequest("/games/chess/matches"),
      gameRequest("/games/chess/leaderboard"),
    ]);
    gameState = {
      matches: matchesJson.matches || [],
      invites: invitesJson.invites || [],
      leaderboard: leaderboardJson.leaderboard || [],
    };
    renderGameCatalog(catalog.games || []);
    renderGameUsers(usersJson.users || []);
    renderGameInvites(invitesJson.invites || []);
    renderGameMatches(matchesJson.matches || []);
    renderGameLeaderboard(leaderboardJson);
    const awardBtn = $("game-award-btn");
    if (awardBtn) awardBtn.style.display = currentUser === "root" ? "" : "none";
    setGameMsg("", true);
  } catch (err) {
    setGameMsg(err.message || "遊戲區讀取失敗", false);
  }
}

async function refreshGameZoneAfterMutation(successMessage) {
  try {
    await loadGameZone();
    if (successMessage) setGameMsg(successMessage, true);
  } catch (err) {
    if (successMessage) setGameMsg(successMessage, true);
  }
}

async function createGameInvite() {
  const select = $("game-invite-user");
  const username = select ? select.value : "";
  if (!username) {
    setGameMsg("請先選擇要邀請的玩家；沒有其他玩家時可使用電腦練習。", false);
    return;
  }
  try {
    await gameRequest("/games/chess/invites", { method: "POST", body: { opponent_username: username } });
    setGameMsg("已送出對戰邀請", true);
    await refreshGameZoneAfterMutation("已送出對戰邀請");
  } catch (err) {
    setGameMsg(err.message || "送出邀請失敗", false);
  }
}

async function reviewGameInvite(inviteId, action) {
  try {
    const json = await gameRequest(`/games/chess/invites/${encodeURIComponent(inviteId)}/${encodeURIComponent(action)}`, { method: "POST", body: {} });
    if (json.match_id) gameSelectedMatchId = json.match_id;
    setGameMsg("邀請已更新", true);
    await refreshGameZoneAfterMutation("邀請已更新");
  } catch (err) {
    setGameMsg(err.message || "邀請處理失敗", false);
  }
}

async function createPracticeGame() {
  try {
    const json = await gameRequest("/games/chess/practice", { method: "POST", body: {} });
    gameSelectedMatchId = json.match_id;
    gameSelectedSquare = null;
    setGameMsg("已建立電腦練習局", true);
    await refreshGameZoneAfterMutation("已建立電腦練習局");
  } catch (err) {
    setGameMsg(err.message || "建立練習局失敗", false);
  }
}

async function selectChessSquare(square) {
  const match = (gameState.matches || []).find((item) => item.id === gameSelectedMatchId);
  if (!match || match.status !== "active") return;
  const piece = match.board?.[square] || "";
  const legal = (match.legal_moves || []).some((move) => move.from === gameSelectedSquare && move.to === square);
  if (gameSelectedSquare && legal) {
    try {
      const json = await gameRequest(`/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/move`, {
        method: "POST",
        body: { from: gameSelectedSquare, to: square },
      });
      gameSelectedSquare = null;
      const updated = json.match;
      gameState.matches = gameState.matches.map((item) => item.id === updated.id ? updated : item);
      renderGameMatches(gameState.matches);
      await loadGameZone();
    } catch (err) {
      setGameMsg(err.message || "走棋失敗", false);
    }
    return;
  }
  if (piece) {
    gameSelectedSquare = square;
    renderChessBoard(match);
  }
}

async function resignGame() {
  if (!gameSelectedMatchId) return;
  if (!confirm("確認認輸並結束這局？")) return;
  try {
    await gameRequest(`/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/resign`, { method: "POST", body: {} });
    gameSelectedSquare = null;
    await loadGameZone();
  } catch (err) {
    setGameMsg(err.message || "認輸失敗", false);
  }
}

async function awardGameRewards() {
  try {
    const json = await gameRequest("/root/games/chess/weekly-rewards/award", { method: "POST", body: {} });
    setGameMsg(`已發放 ${json.awarded?.length || 0} 筆週獎勵`, true);
    await loadGameZone();
  } catch (err) {
    setGameMsg(err.message || "週獎勵發放失敗", false);
  }
}

document.addEventListener("click", (event) => {
  const inviteBtn = event.target?.closest?.("[data-game-invite]");
  if (inviteBtn) {
    reviewGameInvite(inviteBtn.dataset.gameInvite, inviteBtn.dataset.gameInviteAction || "accept");
    return;
  }
  const matchBtn = event.target?.closest?.("[data-game-match-id]");
  if (matchBtn) {
    gameSelectedMatchId = Number(matchBtn.dataset.gameMatchId || 0);
    gameSelectedSquare = null;
    renderGameMatches(gameState.matches || []);
    return;
  }
  const squareBtn = event.target?.closest?.("[data-chess-square]");
  if (squareBtn) {
    selectChessSquare(squareBtn.dataset.chessSquare || "");
  }
});
