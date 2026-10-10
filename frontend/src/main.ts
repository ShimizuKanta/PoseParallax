import { t, language, setLanguage } from './i18n';
import './style.css';
import QRCode from 'qrcode';
import { Camera } from './camera';
import { drawSkeleton } from './skeleton';
import { faceInk, skeletonColors, skeletonLegend } from './skeleton-style';
import { jointNames, joints, type Feedback, type Settings, type State } from './types';

const app = document.querySelector<HTMLDivElement>('#app')!;
const adminPage = location.pathname === '/admin';
const inviteToken = new URLSearchParams(location.hash.slice(1)).get('invite');
const participantPage = !adminPage && new URLSearchParams(location.search).get('participant') === '1';
const escape = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, s => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[s]!));
const time = (seconds: number | null) => seconds === null ? '—' : `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toFixed(1).padStart(4, '0')}`;
const phaseNames = { waiting: "参加受付", round_setup: "ラウンド準備", playing: "プレイ中", round_result: "ラウンド結果", final_result: "最終結果" };
const outcomeNames: Record<string, string> = { cleared: "クリア", timeout: "時間切れ", skipped: "スキップ", cancelled: "中止", poser_left: "ポーズ役が退出", server_restart: "サーバー再起動で中止" };
let state: State | null = null, socket: WebSocket | null = null, camera: Camera | null = null;
let viewKey = '', disposePoser: (() => void) | null = null, serverOffset = 0, retry = 0;
let reconnectTimer = 0, pollingTimer = 0, cameraReady = false;
let lastFeedback: Feedback | null = null;

app.innerHTML = `<header><a class="brand" href="${adminPage ? '/admin' : participantPage ? '/?participant=1' : '/' + location.hash}"><span class="brand-icon">P<span>↗</span></span><span>POSE<span class="brand-light"> PARALLAX</span></span></a><div class="header-tools"><label class="language-label"><span class="sr-only">Language / 言語</span><select id="language" aria-label="Language / 言語"><option data-language value="ja">日本語</option><option data-language value="en">English</option></select></label><span class="connection" id="connection">${t("接続中")}</span></div></header>
  <main id="main"><section class="card"><p>${t("会場に接続しています…")}</p></section></main>
  <footer><span>${t("視点が変わる。チームがつながる。")}</span><a href="${adminPage ? '/' : '/admin'}">${adminPage ? t("参加者ページ") : t("管理者")}</a></footer>
  <div id="toast" role="status" aria-live="polite"></div>`;
const main = document.querySelector<HTMLElement>('#main')!;
let toastTimer = 0, lastCameraStatus = 'カメラを起動して、全身を中央に映してください';
const languageSelect = document.querySelector<HTMLSelectElement>('#language')!;
languageSelect.value = language;
languageSelect.addEventListener('change', () => {
  setLanguage(languageSelect.value === 'en' ? 'en' : 'ja');
  if (document.querySelector('#camera-status')) document.querySelector('#camera-status')!.textContent = t(lastCameraStatus);
  updateLive();
  if (lastFeedback) feedback(lastFeedback);
});
function toast(message: string) {
  const el = document.querySelector<HTMLElement>('#toast')!;
  el.textContent = message; el.classList.add('visible'); clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => el.classList.remove('visible'), 6000);
}
async function api(path: string, body?: unknown, method = 'POST') {
  const response = await fetch(`/api/${path}`, { method, headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === 'string' ? t(detail) : Array.isArray(detail) ? detail.map((d: { msg: string }) => d.msg).join(' / ') : t("通信に失敗しました。"));
  }
  return data;
}
function connection(text: string, online = false) {
  const el = document.querySelector('#connection')!; el.textContent = text; el.classList.toggle('online', online);
}
function send(data: object) { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(data)); }
function connect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = 0;
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws${participantPage ? '?participant=1' : ''}`);
  socket.onopen = () => { retry = 0; connection(t("接続済み"), true); };
  socket.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.type === 'state') update(data);
    else if (data.type === 'feedback') feedback(data);
  };
  socket.onclose = event => {
    socket = null;
    if (event.code === 4409) { connection(t("別のタブで接続中")); camera?.stop(); toast(t("別のタブで接続しました。この画面を使う場合は再読み込みしてください。")); return; }
    if (event.code === 4401 || event.code === 4403) { connection(t("接続終了")); void refresh().then(poll); return; }
    connection(t("再接続中…"));
    reconnectTimer = window.setTimeout(connect, Math.min(1000 * 2 ** retry++, 10000));
  };
  socket.onerror = () => connection(t("接続を確認中…"));
}
async function refresh() {
  try { update(await api(participantPage ? 'state?participant=1' : 'state', undefined, 'GET')); }
  catch (error) { connection(t("サーバーに接続できません")); toast(String(error).replace(/^Error: /, '')); }
}
function poll() {
  clearTimeout(pollingTimer);
  if (!socket) pollingTimer = window.setTimeout(async () => { await refresh(); poll(); }, 3000);
}
function update(next: State) {
  state = next; serverOffset = next.server_time * 1000 - Date.now();
  const member = next.players.some(p => p.id === next.me);
  if (!member && !next.admin) connection(next.registration_open ? t("参加受付中") : t("会場に接続済み"), true);
  const active = next.phase === 'round_setup' || next.phase === 'playing';
  const key = adminPage ? (next.admin ? `admin:${next.event_id}` : 'login')
    : !member ? `join:${next.event_id}:${next.admin}` : `${next.event_id}:${next.me}:${active ? `active:${next.round!.id}` : next.phase}`;
  if (viewKey !== key) {
    document.querySelectorAll('dialog[open]').forEach(el => (el as HTMLDialogElement).close());
    document.body.classList.remove('round-screen', 'observer-screen', 'playing-screen', 'camera-ready');
    viewKey = key; lastFeedback = null; lastCameraStatus = 'カメラを起動して、全身を中央に映してください'; camera?.stop(); camera = null; cameraReady = false; disposePoser?.(); disposePoser = null;
    if (adminPage) next.admin ? renderAdmin() : renderLogin();
    else if (!member) renderJoin();
    else if (active) renderRound();
    else if (next.phase === 'waiting') renderWaiting();
    else renderResults();
  }
  updateLive();
  renderTimers();
  if ((next.admin || member) && !socket && !reconnectTimer) connect();
}
function hero(kicker: string, title: string, sub: string) {
  return `<div class="heading"><span class="eyebrow">${kicker}</span><h1>${title}</h1><p>${sub}</p></div>`;
}
function renderJoin() {
  main.innerHTML = `<div class="join-grid"><section>${hero('A COOPERATIVE PERSPECTIVE GAME', `${t("同じポーズ。")}<br><span class="accent">${t("ちがう視点。")}</span>`, t("仲間と声をかけ合い、ぴったり重なる視点を見つけよう。"))}
    <div class="hero-art" aria-hidden="true"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><svg viewBox="0 0 360 220"><g fill="none" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"><path stroke="${skeletonColors.right}" d="M158 85L135 101L118 73M158 85L164 135L151 174L140 202"/><path stroke="${skeletonColors.left}" d="M204 85L226 99L246 89M204 85L198 135L211 174L221 202"/><path stroke="${skeletonColors.center}" d="M181 72L158 85L204 85L181 72M164 135L198 135"/><circle cx="181" cy="48" r="23" fill="${skeletonColors.center}" stroke="none"/><path stroke="${faceInk}" stroke-width="4" d="M171 54Q181 66 191 54"/></g><g fill="${faceInk}"><circle cx="174" cy="41" r="3.5"/><circle cx="188" cy="41" r="3.5"/></g><g fill="#83c8ff"><circle cx="57" cy="143" r="8"/><circle cx="293" cy="142" r="8"/></g><g stroke="#83c8ff" stroke-dasharray="4 6" opacity=".5"><path d="M65 140L156 115M285 140L209 114"/></g></svg><span class="art-tag tag-left">YOUR VIEW</span><span class="art-tag tag-right">THEIR VIEW</span></div></section>
    <section class="card join-card"><span class="eyebrow">JOIN THE GAME</span><h2 data-user-content>${escape(state!.name)}</h2><p>${t("表示名を入れて、チームに参加。")}</p>
    ${state!.admin ? `<p class="notice">${t("管理者としてログイン中です。参加には別のブラウザをご利用ください。")}</p><a class="button" href="/admin">${t("管理画面へ")}</a>` : `<form id="join-form"><label>${t("表示名")}<input name="name" placeholder="${t('例：かんた')}" maxlength="30" autocomplete="nickname" required /></label><button id="join-button" type="submit">${t("参加する")}<span>↗</span></button></form>`}
    <p id="join-status" class="small"></p><div class="privacy-note"><span>◎</span><p>${t("カメラ映像はスマートフォン内で処理します。")}<br>${t("画像の送信・保存は行いません。")}</p></div></section></div>
    <div class="steps"><div><b>01</b><span>${t("ひとりがポーズ役に")}</span></div><div><b>02</b><span>${t("みんなで視点を探す")}</span></div><div><b>03</b><span>${t("ポーズを合わせてクリア")}</span></div>`;
  document.querySelector('#join-form')?.addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    const button = form.querySelector('button')!; button.disabled = true;
    try { await api('join', { name: new FormData(form).get('name'), invite_token: inviteToken }); await refresh(); connect(); }
    catch (error) { toast(t((error as Error).message)); button.disabled = false; }
  });
}
function renderLogin() {
  main.innerHTML = `<section class="card login-card">${hero('HOST CONSOLE', t("管理者ログイン"), t("会場のゲーム進行と判定設定を管理します。"))}
    <form id="login-form"><label>${t("管理者パスワード")}<input name="password" type="password" autocomplete="current-password" required /></label><button>${t("ログイン")}</button></form></section>`;
  document.querySelector('#login-form')!.addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    try { await api('admin/login', { password: new FormData(form).get('password') }); await refresh(); connect(); }
    catch (error) { toast(t((error as Error).message)); }
  });
}
function renderWaiting() {
  const me = state!.players.find(p => p.id === state!.me)!;
  main.innerHTML = `${hero('READY TO PLAY', t('ようこそ、{name}さん', { name: escape(me.name) }), t("全員が集まったら、管理者がゲームを始めます。"))}
    <div class="waiting-grid"><details class="card"><summary>${t("チームメンバー")} <span class="pill" id="member-count"></span></summary><div id="roster"></div></details>
    <section class="card instructions"><span class="waiting-dot"></span><h2>${t("仲間を待っています")}</h2><p>${t("観察者は背面カメラを使います。ポーズ役の全身が映る距離をとり、中央に映してください。")}</p><p class="small">${t("移動するときは画面から目を離し、周囲を確認しましょう。")}</p></section></div>`;
}
function renderRound() {
  const r = state!.round!, poser = state!.me === r.poser_id;
  document.body.classList.add('round-screen');
  document.body.classList.toggle('observer-screen', !poser);
  main.innerHTML = `<div class="round-top"><div><span class="eyebrow">ROUND ${r.number.toString().padStart(2, '0')}</span><h1>${poser ? t('あなたがポーズ役') : t('視点を見つけよう')}</h1></div><div class="round-tools"><div class="timer" data-timer>00:00.0</div><button id="show-details" class="secondary">${t('詳細')}</button></div></div>
    ${poser ? `<section class="card poser-card"><div id="poser-view"></div><div class="pose-caption"><strong>${escape(t(r.pose!.name))}</strong><span>${t('指でドラッグして回転 · 左右は本人基準')}</span></div></section>`
      : `<section class="camera-card"><div class="camera-stage"><video id="camera-video" autoplay muted playsinline></video><canvas id="camera-overlay"></canvas><div class="view-cross" aria-hidden="true"></div><button id="enlarge-target" class="target-preview" aria-label="${t('お手本を拡大')}"><span>${t('お手本')}</span><canvas id="target" width="360" height="300"></canvas><span aria-hidden="true">↗</span></button><div class="camera-notice"><p id="camera-status" role="status">${t(lastCameraStatus)}</p><button id="camera-start" class="secondary">${t('カメラを起動 / 再試行')}</button></div></div><div class="match-strip"><div class="score-row"><span>MATCH</span><strong id="score">0<span>%</span></strong></div><div class="match-feedback"><div class="meter"><div id="score-bar"></div></div><p id="match-reason" aria-live="polite">${t('判定はゲーム開始後に行います')}</p></div></div></section>`}
    <button id="ready-button" ${poser ? '' : 'disabled'}>${poser ? t('ポーズの準備完了') : t('カメラの準備完了')}</button>
    <dialog id="round-details" class="detail-dialog"><div class="section-head"><h2>${t('詳細')}</h2><button class="quiet" data-close-dialog>${t('閉じる')}</button></div>${poser ? '' : `<button id="camera-retry" class="secondary">${t('カメラを起動 / 再試行')}</button>`}<h3>${t('遊び方・判定条件')}</h3><div class="round-message" id="round-message"></div><p>${t('観察者は背面カメラを使います。ポーズ役の全身が映る距離をとり、中央に映してください。')}</p><p class="small">${t('移動するときは画面から目を離し、周囲を確認しましょう。')}</p>${skeletonLegend()}<p class="small">${t('指でドラッグして回転 · 左右は本人基準')}</p><div class="section-head"><h2>${t('チームの状況')}</h2><span id="clear-count" class="pill"></span></div><div id="roster"></div></dialog>
    ${poser ? '' : `<dialog id="target-dialog" class="detail-dialog target-dialog"><div class="section-head"><h2>${t('お手本')}</h2><button class="quiet" data-close-dialog>${t('閉じる')}</button></div><canvas id="large-target" width="720" height="600"></canvas><p>${t('この見え方になる場所を探そう')}</p>${skeletonLegend()}</dialog>`}`;
  document.querySelector('#show-details')!.addEventListener('click', () => (document.querySelector('#round-details') as HTMLDialogElement).showModal());
  document.querySelector('#enlarge-target')?.addEventListener('click', () => (document.querySelector('#target-dialog') as HTMLDialogElement).showModal());
  document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog')!.close()));
  document.querySelector('#ready-button')!.addEventListener('click', () => send({ type: 'ready', round_id: r.id }));
  if (poser) {
    const key = viewKey;
    void import('./poser').then(({ showPoser }) => {
      if (viewKey === key) disposePoser = showPoser(document.querySelector('#poser-view')!, r.pose!.points);
    }).catch(() => toast(t("3D表示を開始できませんでした。ブラウザを更新してください。")));
  } else {
    drawSkeleton(document.querySelector('#target')!, r.target!);
    drawSkeleton(document.querySelector('#large-target')!, r.target!);
    camera = new Camera(document.querySelector('#camera-video')!, document.querySelector('#camera-overlay')!,
      message => { lastCameraStatus = message; const el = document.querySelector('#camera-status'); if (el) el.textContent = t(message); },
      points => { if (state?.phase === 'playing') send({ type: 'pose', round_id: r.id, keypoints: points }); },
      ready => { cameraReady = ready; if (!ready) send({ type: 'unready', round_id: r.id }); updateLive(); });
    document.querySelector('#camera-retry')!.addEventListener('click', () => { cameraReady = false; updateLive(); void camera?.start(); (document.querySelector('#round-details') as HTMLDialogElement).close(); });
    document.querySelector('#camera-start')!.addEventListener('click', () => { cameraReady = false; updateLive(); void camera?.start(); });
  }
}
function resultMarkup() {
  const history = state!.history, last = history.at(-1);
  const best = history.filter(r => r.outcome === 'cleared').sort((a, b) => a.elapsed! - b.elapsed!)[0];
  return `<div class="result-feature"><span class="eyebrow">${last?.outcome === 'cleared' ? 'NICE TEAMWORK' : 'ROUND COMPLETE'}</span><h2>${last ? t(outcomeNames[last.outcome]) : t("ゲーム終了")}</h2><div class="result-time">${time(last?.elapsed ?? null)}</div><p>${t("チームベスト")}<strong>${time(best?.elapsed ?? null)}</strong>${best ? ` · ROUND ${best.number}` : ''}</p></div>
    <details class="result-history"><summary>${t('過去のラウンド・参加者別結果')}</summary><div class="result-list">${history.map(r => `<article class="result-item"><div><span class="eyebrow">ROUND ${r.number}</span><h3><span data-user-content>${escape(r.participants[r.poser_id])}</span><span class="small"> · ${t('ポーズ役')}</span></h3><span class="${r.outcome === 'cleared' ? 'accent' : 'muted'}">${t(outcomeNames[r.outcome])}</span><details><summary>${t("参加者ごとの結果")}</summary>${Object.entries(r.participants).filter(([pid]) => pid !== r.poser_id).map(([pid, name]) => `<p><span data-user-content>${escape(name)}</span> <strong>${r.cleared[pid] && r.started_at !== null ? time(r.cleared[pid] - r.started_at) : t("未クリア")}</strong></p>`).join('')}</details></div><strong class="history-time">${time(r.elapsed)}</strong></article>`).join('')}</div></details>`;
}
function renderResults() {
  const r = state!.round;
  const review = r?.target_view && r.target;
  main.innerHTML = `${hero(state!.phase === 'final_result' ? 'THANK YOU FOR PLAYING' : 'ROUND RESULT', state!.phase === 'final_result' ? t("みんなでつくった記録。") : t("ひとつのポーズ、みんなの視点。"), state!.phase === 'final_result' ? t("おつかれさまでした！") : t("管理者が次のラウンドを準備しています。"))}
    <section class="card">${resultMarkup()}</section>${r?.pose ? `<section class="card pose-review">${review ? `<button id="reset-target-view" class="secondary" disabled>${t('自分のお手本の視点に戻す')}</button>` : ''}<div class="pose-review-grid"><div id="result-pose" class="result-pose"></div>${review ? `<div class="review-target"><h3>${t('自分の2Dお手本')}</h3><canvas id="review-target" width="720" height="600"></canvas></div>` : ''}</div>${skeletonLegend()}</section>` : ''}`;
  if (review) drawSkeleton(document.querySelector('#review-target')!, r!.target!);
  const pose = state!.round?.pose;
  if (pose) {
    const key = viewKey;
    void import('./poser').then(({ showPoser }) => {
      if (viewKey === key) disposePoser = showPoser(document.querySelector('#result-pose')!, pose.points,
        true, { targetView: r?.target_view,
          resetButton: document.querySelector<HTMLButtonElement>('#reset-target-view') ?? undefined });
    });
  }
}
function field(name: keyof Settings, label: string, min: number, max: number, step = 1) {
  return `<label>${label}<input name="${name}" type="number" min="${min}" max="${max}" step="${step}" value="${state!.settings![name]}" required /></label>`;
}
function renderAdmin() {
  const s = state!.settings!;
  main.innerHTML = `<div class="section-head">${hero('HOST CONSOLE', t("みんなの視点を、ひとつに。"), t("参加者を確認して、ラウンドを進めましょう。"))}<button class="quiet" id="logout">${t("ログアウト")}</button></div>
    <div class="admin-grid"><section class="card"><div class="section-head"><h2>${t("ゲーム進行")}</h2><span class="pill" id="phase-label"></span></div><div id="admin-summary"><div class="admin-stats"><div><strong id="admin-player-count">0</strong><span>${t("参加者")}</span></div><div><strong id="admin-round-number">—</strong><span>${t("ラウンド")}</span></div><div><strong data-timer>00:00.0</strong><span>${t("経過時間")}</span></div></div><p id="admin-round-status" class="small"></p></div><div id="admin-actions" class="actions"></div></section>
    <section class="card qr-card"><canvas id="qr"></canvas><div><span class="eyebrow">SCAN TO JOIN</span><h2>${t("このQRから参加")}</h2><p class="small">${t(state!.setup_url ? '会場Wi-Fiに接続して開いてください' : 'QRを読み取って参加してください')}</p><input id="join-url" aria-label="${t('参加URL')}" type="url" value="${escape(state!.join_url ?? '')}"/><button id="update-qr" class="quiet">${t("QRを更新")}</button>${state!.setup_url ? `<button id="setup-qr" class="quiet">${t("初期設定QRを表示")}</button><a class="small" href="${escape(state!.setup_url)}" target="_blank" rel="noreferrer">${t("証明書の設定手順 ↗")}</a>` : ''}</div></section></div>
    <section class="card"><div class="section-head"><h2>${t("チームメンバー")}</h2><span id="member-count" class="pill"></span></div><div id="roster"></div></section>
    <section class="card"><label>${t('ポーズ役の選び方')}<select id="fixed-poser"></select></label><p class="small">${t('固定の変更は次に準備するラウンドから適用します。')}</p>
    <details><summary>${t('このPCでポーズ役として参加')}</summary><form id="admin-join-form"><label>${t('このPCの表示名')}<input name="name" value="${escape(t('管理者PC'))}" maxlength="30" required /></label><button>${t('このPCを参加させてポーズ役に固定')}</button></form>
    <a id="admin-participant-link" class="participant-link" href="/?participant=1" target="_blank" rel="noopener" hidden>${t('このPCの参加画面を開く')}</a><p class="small">${t('参加画面は別タブで開きます。管理画面もそのまま操作できます。')}</p></details></section>
    <details class="card settings-panel"><summary>${t("判定・ゲーム設定")}<span class="small">${t("デフォルトとして保存")}</span></summary><p class="small">${t("変更は次に準備するラウンドから適用します。現在のラウンドの条件は変わりません。")}</p>
    <form id="settings-form"><div class="form-grid"><label>${t("クリア方式")}<select name="clear_mode"><option value="latched" ${s.clear_mode === 'latched' ? 'selected' : ''}>${t("一度達成すれば確定")}</option><option value="simultaneous" ${s.clear_mode === 'simultaneous' ? 'selected' : ''}>${t("全員が同時に一致")}</option></select></label>
    ${field('rounds', t("ラウンド数"), 1, 100)}${field('round_seconds', t("制限時間（秒）"), 15, 1800)}${field('hold_seconds', t("一致を保つ時間（秒）"), 0, 10, .1)}
    ${field('score_threshold', t("合格スコア（%）"), 20, 100)}${field('confidence_threshold', t("関節の信頼度"), .1, .95, .05)}
    <label>${t("隠れた関節")}<select name="hidden_policy"><option value="require" ${s.hidden_policy === 'require' ? 'selected' : ''}>${t("全対象関節が見えることを要求")}</option><option value="ignore" ${s.hidden_policy === 'ignore' ? 'selected' : ''}>${t("見えない関節を除外")}</option></select></label>${field('min_visible', t("最低限必要な関節数"), 4, 12)}
    ${field('azimuth_min', t("方位角：最小（°）"), -180, 180)}${field('azimuth_max', t("方位角：最大（°）"), -180, 180)}${field('elevation_min', t("仰角：最小（°）"), -30, 30)}${field('elevation_max', t("仰角：最大（°）"), -30, 30)}
    ${field('min_limb_ratio', t("手足の最小投影長 / 全高"), 0, .3, .01)}${field('min_side_separation', t("左右関節の最小間隔 / 全高"), 0, .3, .01)}${field('min_keypoint_separation', t("全関節点の最小間隔 / 全高"), 0, .3, .01)}</div>
    <p class="small">${t("全関節点の最小間隔は、お手本の肩・肘・手首・腰・膝・足首の12点すべてに適用します。0.08は全高の8%、0はこの条件を無効にします。間隔が足りない視点は再生成します。")}</p>
    <fieldset><legend>${t("判定する関節")}</legend><div class="joint-grid">${joints.map((j, i) => `<label><input type="checkbox" name="joints" value="${j}" ${s.joints.includes(j) ? 'checked' : ''}/>${t(jointNames[i])}</label>`).join('')}</div></fieldset><button>${t("デフォルトとして保存")}</button></form></details>
    <details class="card"><summary>${t("ラウンド履歴")}</summary><div id="admin-results"></div></details>`;
  const makeQR = () => {
    const value = (document.querySelector('#join-url') as HTMLInputElement).value;
    if (!value) { toast(t("LAN IPを検出できませんでした。参加URLを入力してください。")); return; }
    try {
      const url = new URL(value); if (!['http:', 'https:'].includes(url.protocol)) throw new Error();
      if (value !== state!.setup_url && state!.join_url) {
        url.hash = new URL(state!.join_url).hash;
        (document.querySelector('#join-url') as HTMLInputElement).value = url.href;
      }
    }
    catch { toast(t("正しい参加URLを入力してください。")); return; }
    void QRCode.toCanvas(document.querySelector('#qr'), (document.querySelector('#join-url') as HTMLInputElement).value, { width: 160, margin: 2, color: { dark: '#101827', light: '#ffffff' } }).catch(() => toast(t("QRコードを作成できませんでした。")));
  };
  makeQR(); document.querySelector('#update-qr')!.addEventListener('click', makeQR);
  document.querySelector('#setup-qr')?.addEventListener('click', () => {
    const input = document.querySelector<HTMLInputElement>('#join-url')!;
    const setup = input.value !== state!.setup_url;
    input.value = setup ? state!.setup_url! : state!.join_url!;
    document.querySelector('#setup-qr')!.textContent = setup ? t("ゲーム参加QRに戻す") : t("初期設定QRを表示");
    makeQR();
  });
  document.querySelector('#logout')!.addEventListener('click', async () => {
    await api('logout'); socket?.close(); await refresh();
  });
  document.querySelector('#fixed-poser')!.addEventListener('change', async event => {
    const select = event.currentTarget as HTMLSelectElement;
    select.disabled = true;
    await action('set_poser', { player_id: select.value || null });
    select.disabled = false;
  });
  document.querySelector('#admin-join-form')!.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const button = form.querySelector('button')!;
    button.disabled = true;
    try {
      await api('admin/join', { name: new FormData(form).get('name') });
      // A fresh admin socket receives the newly created participant cookie.
      if (socket) { socket.onclose = null; socket.close(); socket = null; }
      await refresh(); connect();
    } catch (error) { toast(t((error as Error).message)); }
    finally { button.disabled = false; }
  });
  document.querySelector('#settings-form')!.addEventListener('submit', async event => {
    event.preventDefault(); const data = new FormData(event.currentTarget as HTMLFormElement);
    const settings: Record<string, unknown> = {};
    for (const [key, value] of data.entries()) {
      if (key === 'joints') continue;
      settings[key] = ['clear_mode', 'hidden_policy'].includes(key) ? value : Number(value);
    }
    settings.joints = data.getAll('joints').map(Number);
    try { await api('admin/settings', settings, 'PUT'); toast(t("デフォルト設定を保存しました。次のラウンドから適用します。")); await refresh(); }
    catch (error) { toast(t((error as Error).message)); }
  });
}
function updateLive() {
  if (!state) return;
  const s = state, r = s.round;
  const set = (id: string, text: string) => { const el = document.getElementById(id); if (el && el.textContent !== text) el.textContent = text; };
  set('member-count', t('{count} / 50人', { count: s.players.length }));
  set('phase-label', t(phaseNames[s.phase]));
  const joinButton = document.querySelector<HTMLButtonElement>('#join-button');
  if (joinButton) joinButton.disabled = !inviteToken || !s.registration_open || s.phase !== 'waiting' || s.players.length >= 50;
  set('join-status', !inviteToken ? t('主催者の最新のQRコードから参加してください。') : s.registration_open ? t('参加受付中') : t('受付は終了しました'));
  const roster = document.querySelector('#roster');
  if (roster) roster.innerHTML = s.players.map(p => `<div class="player"><div class="avatar" data-user-content>${escape(p.name.slice(0, 1))}</div><div class="player-name"><strong><span data-user-content>${escape(p.name)}</span>${p.id === s.me ? ` <span class="small">${t("あなた")}</span>` : ''}</strong><span class="small">${r?.poser_id === p.id && s.phase !== 'waiting' ? t("ポーズ役") : p.connected ? t("接続済み") : t("再接続待ち")}</span></div><span class="player-status ${p.cleared || p.matched ? 'accent' : ''}">${s.phase === 'round_setup' ? p.ready ? t("準備OK") : t("準備中") : s.phase === 'playing' ? p.cleared ? '✓ CLEAR' : p.matched ? t("一致中") : r?.poser_id === p.id ? 'POSE' : `${Math.round(p.score)}%` : p.connected ? '●' : '○'}</span>${s.admin ? `<button class="quiet remove" data-player="${p.id}" aria-label="${escape(t('{name}を除外', { name: p.name }))}">${t("除外")}</button>` : ''}</div>`).join('') || `<p class="empty">${t("参加者を待っています")}</p>`;
  document.querySelectorAll<HTMLButtonElement>('.remove').forEach(button => button.addEventListener('click', () => {
    const name = s.players.find(p => p.id === button.dataset.player)?.name;
    if (confirm(t('{name}さんをこのゲームから除外しますか？', { name: name ?? '' }))) void action('remove', { player_id: button.dataset.player });
  }));
  if (r) {
    const observers = s.players.filter(p => p.id !== r.poser_id);
    set('clear-count', `${observers.filter(p => p.cleared).length} / ${observers.length} CLEAR`);
    set('round-message', s.phase === 'round_setup' ? t("準備ができたらボタンを押してください。全員そろったら管理者が開始します。")
      : t('{mode} · {hold}秒キープ · 制限 {limit}秒', { mode: r.settings.clear_mode === 'latched' ? t('一度クリアすれば確定') : t('全員が同時に一致'), hold: r.settings.hold_seconds, limit: r.settings.round_seconds }));
    const ready = document.querySelector<HTMLButtonElement>('#ready-button');
    if (ready) {
      document.body.classList.toggle('playing-screen', !adminPage && s.phase === 'playing');
      document.body.classList.toggle('camera-ready', cameraReady);
      ready.hidden = s.phase !== 'round_setup';
      const me = s.players.find(p => p.id === s.me);
      ready.disabled = !!me?.ready || (s.me !== r.poser_id && !cameraReady);
      ready.textContent = me?.ready ? t("✓ 準備完了 · 開始を待っています") : s.me === r.poser_id ? t("ポーズの準備完了") : t("カメラの準備完了");
    }
  }
  if (s.admin && adminPage) {
    const select = document.querySelector<HTMLSelectElement>('#fixed-poser')!;
    const optionsKey = JSON.stringify([s.players.map(p => [p.id, p.name]), language]);
    if (select.dataset.key !== optionsKey) {
      select.innerHTML = `<option value="">${t('自動（順番を均等に）')}</option>` + s.players.map(p => `<option value="${p.id}" data-user-content>${escape(p.name)}</option>`).join('');
      select.dataset.key = optionsKey;
    }
    select.value = s.fixed_poser_id ?? '';
    const pcJoined = !!s.admin_player_id;
    document.querySelector<HTMLFormElement>('#admin-join-form')!.hidden = pcJoined;
    document.querySelector<HTMLAnchorElement>('#admin-participant-link')!.hidden = !pcJoined;
    document.querySelector<HTMLButtonElement>('#admin-join-form button')!.disabled = !s.registration_open || s.phase !== 'waiting' || s.players.length >= 50;
    const readyCount = s.players.filter(p => p.ready && p.connected).length;
    set('admin-player-count', String(s.players.length));
    set('admin-round-number', String(r?.number ?? '—'));
    set('admin-round-status', s.phase === 'round_setup' ? t('{count} / {total}人が準備完了', { count: readyCount, total: s.players.length })
      : r && s.phase === 'playing' ? t('ポーズ役：{name}', { name: s.players.find(p => p.id === r.poser_id)?.name ?? '' }) : t("参加者と準備状況を確認して進めてください。"));
    const buttons: [string, string, string?][] = s.phase === 'waiting' ? [['setup', t("ゲームを準備")], ['registration', s.registration_open ? t("受付を閉じる") : t("受付を開く"), 'secondary'], ['end', t("ゲーム終了"), 'quiet']]
      : s.phase === 'round_setup' ? [['start', t("ラウンド開始")], ['skip', t("スキップ"), 'secondary'], ['end', t("ゲーム終了"), 'quiet']]
      : s.phase === 'playing' ? [['cancel', t("ラウンド中止"), 'secondary'], ['skip', t("スキップ"), 'secondary'], ['end', t("ゲーム終了"), 'quiet']]
      : s.phase === 'round_result' ? [['setup', s.history.length >= s.settings!.rounds ? t("最終結果へ") : t("次のラウンドを準備")], ['end', t("ゲーム終了"), 'secondary']]
      : [['new_event', t("次のグループを受付")]];
    document.querySelector('#admin-actions')!.innerHTML = buttons.map(([a, label, cls]) => `<button data-action="${a}" class="${cls ?? ''}" ${a === 'start' && readyCount < s.players.length ? 'disabled' : ''}>${label}</button>`).join('');
    document.querySelectorAll<HTMLButtonElement>('[data-action]').forEach(button => button.addEventListener('click', () => {
      const a = button.dataset.action!;
      if (['end', 'cancel', 'skip'].includes(a) && !confirm(t('{action}しますか？', { action: button.textContent ?? '' }))) return;
      if (a === 'new_event') {
        const name = prompt(t("次のグループのイベント名"), 'Pose Parallax');
        if (name === null) return;
        void action(a, { name: name.trim() || 'Pose Parallax' });
      } else void action(a);
    }));
    const results = document.querySelector('#admin-results')!;
    // Avoid replacing expanded details unless the results changed.
    const key = JSON.stringify(s.history);
    if (results.getAttribute('data-key') !== key) { results.innerHTML = s.history.length ? resultMarkup() : `<p class="empty">${t("まだラウンドの記録がありません。")}</p>`; results.setAttribute('data-key', key); }
  }
}
async function action(action: string, extras = {}) {
  try { await api('admin/action', { action, ...extras }); await refresh(); }
  catch (error) { toast(t((error as Error).message)); }
}
function feedback(data: Feedback) {
  lastFeedback = data;
  const score = document.querySelector('#score'); if (!score) return;
  score.innerHTML = `${Math.round(data.score)}<span>%</span>`;
  const bar = document.querySelector<HTMLElement>('#score-bar')!;
  bar.style.width = `${data.score}%`; bar.classList.toggle('matched', data.matched);
  document.querySelector('#match-reason')!.textContent = data.cleared ? t("✓ クリア！仲間に声をかけよう") : `${t(data.reason)}${data.matched ? t(' ({hold}秒)', { hold: data.hold.toFixed(1) }) : ''}`;
}
function renderTimers() {
  const r = state?.round;
  const elapsed = r?.started_at != null ? Math.max(0, (r.ended_at ?? (Date.now() + serverOffset) / 1000) - r.started_at) : 0;
  const value = time(elapsed);
  document.querySelectorAll('[data-timer]').forEach(el => { if (el.textContent !== value) el.textContent = value; });
}
window.setInterval(renderTimers, 100);
window.addEventListener('pagehide', () => { camera?.stop(); socket?.close(); });
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
void refresh().then(poll);
