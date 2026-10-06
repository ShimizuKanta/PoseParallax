import './style.css';
import QRCode from 'qrcode';
import { Camera } from './camera';
import { drawSkeleton } from './skeleton';
import { faceInk, skeletonColors, skeletonLegend } from './skeleton-style';
import { jointNames, joints, type Feedback, type Settings, type State } from './types';

const app = document.querySelector<HTMLDivElement>('#app')!;
const adminPage = location.pathname === '/admin';
const escape = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, s => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[s]!));
const time = (seconds: number | null) => seconds === null ? '—' : `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toFixed(1).padStart(4, '0')}`;
const phaseNames = { waiting: '参加受付', round_setup: 'ラウンド準備', playing: 'プレイ中', round_result: 'ラウンド結果', final_result: '最終結果' };
const outcomeNames: Record<string, string> = { cleared: 'クリア', timeout: '時間切れ', skipped: 'スキップ', cancelled: '中止', poser_left: 'ポーズ役が退出', server_restart: 'サーバー再起動で中止' };
let state: State | null = null, socket: WebSocket | null = null, camera: Camera | null = null;
let viewKey = '', disposePoser: (() => void) | null = null, serverOffset = 0, retry = 0;
let reconnectTimer = 0, pollingTimer = 0, cameraReady = false;

app.innerHTML = `<header><a class="brand" href="${adminPage ? '/admin' : '/'}"><span class="brand-icon">P<span>↗</span></span><span>POSE<span class="brand-light"> PARALLAX</span></span></a><span class="connection" id="connection">接続中</span></header>
  <main id="main"><section class="card"><p>会場に接続しています…</p></section></main>
  <footer><span>視点が変わる。チームがつながる。</span><a href="${adminPage ? '/' : '/admin'}">${adminPage ? '参加者ページ' : '管理者'}</a></footer>
  <div id="toast" role="status" aria-live="polite"></div>`;
const main = document.querySelector<HTMLElement>('#main')!;
let toastTimer = 0;
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
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d: { msg: string }) => d.msg).join(' / ') : '通信に失敗しました。');
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
  socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`);
  socket.onopen = () => { retry = 0; connection('接続済み', true); };
  socket.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.type === 'state') update(data);
    else if (data.type === 'feedback') feedback(data);
  };
  socket.onclose = event => {
    socket = null;
    if (event.code === 4409) { connection('別のタブで接続中'); camera?.stop(); toast('別のタブで接続しました。この画面を使う場合は再読み込みしてください。'); return; }
    if (event.code === 4401 || event.code === 4403) { connection('接続終了'); void refresh().then(poll); return; }
    connection('再接続中…');
    reconnectTimer = window.setTimeout(connect, Math.min(1000 * 2 ** retry++, 10000));
  };
  socket.onerror = () => connection('接続を確認中…');
}
async function refresh() {
  try { update(await api('state', undefined, 'GET')); }
  catch (error) { connection('サーバーに接続できません'); toast(String(error).replace(/^Error: /, '')); }
}
function poll() {
  clearTimeout(pollingTimer);
  if (!socket) pollingTimer = window.setTimeout(async () => { await refresh(); poll(); }, 3000);
}
function update(next: State) {
  state = next; serverOffset = next.server_time * 1000 - Date.now();
  const member = next.players.some(p => p.id === next.me);
  if (!member && !next.admin) connection(next.registration_open ? '参加受付中' : '会場に接続済み', true);
  const active = next.phase === 'round_setup' || next.phase === 'playing';
  const key = adminPage ? (next.admin ? `admin:${next.event_id}` : 'login')
    : !member ? `join:${next.event_id}:${next.admin}` : `${next.event_id}:${next.me}:${active ? `active:${next.round!.id}` : next.phase}`;
  if (viewKey !== key) {
    viewKey = key; camera?.stop(); camera = null; cameraReady = false; disposePoser?.(); disposePoser = null;
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
  main.innerHTML = `<div class="join-grid"><section>${hero('A COOPERATIVE PERSPECTIVE GAME', '同じポーズ。<br><span class="accent">ちがう視点。</span>', '仲間と声をかけ合い、ぴったり重なる視点を見つけよう。')}
    <div class="hero-art" aria-hidden="true"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><svg viewBox="0 0 360 220"><g fill="none" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"><path stroke="${skeletonColors.right}" d="M158 85L135 101L118 73M158 85L164 135L151 174L140 202"/><path stroke="${skeletonColors.left}" d="M204 85L226 99L246 89M204 85L198 135L211 174L221 202"/><path stroke="${skeletonColors.center}" d="M181 72L158 85L204 85L181 72M164 135L198 135"/><circle cx="181" cy="48" r="23" fill="${skeletonColors.center}" stroke="none"/><path stroke="${faceInk}" stroke-width="4" d="M171 54Q181 66 191 54"/></g><g fill="${faceInk}"><circle cx="174" cy="41" r="3.5"/><circle cx="188" cy="41" r="3.5"/></g><g fill="#83c8ff"><circle cx="57" cy="143" r="8"/><circle cx="293" cy="142" r="8"/></g><g stroke="#83c8ff" stroke-dasharray="4 6" opacity=".5"><path d="M65 140L156 115M285 140L209 114"/></g></svg><span class="art-tag tag-left">YOUR VIEW</span><span class="art-tag tag-right">THEIR VIEW</span></div></section>
    <section class="card join-card"><span class="eyebrow">JOIN THE GAME</span><h2>${escape(state!.name)}</h2><p>表示名を入れて、チームに参加。</p>
    ${state!.admin ? '<p class="notice">管理者としてログイン中です。参加には別のブラウザをご利用ください。</p><a class="button" href="/admin">管理画面へ</a>' : `<form id="join-form"><label>表示名<input name="name" placeholder="例：かんた" maxlength="30" autocomplete="nickname" required /></label><button id="join-button" type="submit">参加する <span>↗</span></button></form>`}
    <p id="join-status" class="small"></p><div class="privacy-note"><span>◎</span><p>カメラ映像はスマートフォン内で処理します。<br>画像の送信・保存は行いません。</p></div></section></div>
    <div class="steps"><div><b>01</b><span>ひとりがポーズ役に</span></div><div><b>02</b><span>みんなで視点を探す</span></div><div><b>03</b><span>ポーズを合わせてクリア</span></div>`;
  document.querySelector('#join-form')?.addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    const button = form.querySelector('button')!; button.disabled = true;
    try { await api('join', { name: new FormData(form).get('name') }); await refresh(); connect(); }
    catch (error) { toast((error as Error).message); button.disabled = false; }
  });
}
function renderLogin() {
  main.innerHTML = `<section class="card login-card">${hero('HOST CONSOLE', '管理者ログイン', '会場のゲーム進行と判定設定を管理します。')}
    <form id="login-form"><label>管理者パスワード<input name="password" type="password" autocomplete="current-password" required /></label><button>ログイン</button></form></section>`;
  document.querySelector('#login-form')!.addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    try { await api('admin/login', { password: new FormData(form).get('password') }); await refresh(); connect(); }
    catch (error) { toast((error as Error).message); }
  });
}
function renderWaiting() {
  const me = state!.players.find(p => p.id === state!.me)!;
  main.innerHTML = `${hero('READY TO PLAY', `ようこそ、${escape(me.name)}さん`, '全員が集まったら、管理者がゲームを始めます。')}
    <div class="waiting-grid"><section class="card"><div class="section-head"><h2>チームメンバー</h2><span class="pill" id="member-count"></span></div><div id="roster"></div></section>
    <section class="card instructions"><span class="waiting-dot"></span><h2>仲間を待っています</h2><p>観察者は背面カメラを使います。ポーズ役の全身が映る距離をとり、中央に映してください。</p><p class="small">移動するときは画面から目を離し、周囲を確認しましょう。</p></section></div>`;
}
function renderRound() {
  const r = state!.round!, poser = state!.me === r.poser_id;
  main.innerHTML = `<div class="round-top"><div><span class="eyebrow">ROUND ${r.number.toString().padStart(2, '0')}</span><h1>${poser ? 'あなたがポーズ役' : '視点を見つけよう'}</h1></div><div class="timer" data-timer>00:00.0</div></div>
    <div class="round-message" id="round-message"></div>
    ${poser ? `<section class="card poser-card"><div id="poser-view"></div><div class="pose-caption"><strong>${escape(r.pose!.name)}</strong><span>指でドラッグして回転 · 左右は本人基準</span>${skeletonLegend}</div></section><button id="ready-button">ポーズの準備完了</button>`
      : `<div class="observer-grid"><section class="camera-card"><div class="camera-stage"><video id="camera-video" autoplay muted playsinline></video><canvas id="camera-overlay"></canvas><div class="view-cross" aria-hidden="true"></div><span class="camera-label">YOUR CAMERA</span></div><div class="camera-controls"><p id="camera-status" role="status">カメラを起動して、全身を中央に映してください</p><button id="camera-start" class="secondary">カメラを起動 / 再試行</button></div></section>
      <section class="card target-card"><div class="section-head"><span class="eyebrow">YOUR TARGET</span>${skeletonLegend}</div><canvas id="target" width="360" height="300"></canvas><p class="small">この見え方になる場所を探そう</p><div class="score-row"><span>MATCH</span><strong id="score">0<span>%</span></strong></div><div class="meter"><div id="score-bar"></div></div><p id="match-reason" aria-live="polite">判定はゲーム開始後に行います</p><button id="ready-button" disabled>カメラの準備完了</button></section></div>`}
    <section class="card progress-card"><div class="section-head"><h2>チームの状況</h2><span id="clear-count" class="pill"></span></div><div id="roster"></div></section>`;
  document.querySelector('#ready-button')!.addEventListener('click', () => send({ type: 'ready', round_id: r.id }));
  if (poser) {
    const key = viewKey;
    void import('./poser').then(({ showPoser }) => {
      if (viewKey === key) disposePoser = showPoser(document.querySelector('#poser-view')!, r.pose!.points);
    }).catch(() => toast('3D表示を開始できませんでした。ブラウザを更新してください。'));
  } else {
    drawSkeleton(document.querySelector('#target')!, r.target!);
    camera = new Camera(document.querySelector('#camera-video')!, document.querySelector('#camera-overlay')!,
      message => { const el = document.querySelector('#camera-status'); if (el) el.textContent = message; },
      points => { if (state?.phase === 'playing') send({ type: 'pose', round_id: r.id, keypoints: points }); },
      ready => { cameraReady = ready; if (!ready) send({ type: 'unready', round_id: r.id }); updateLive(); });
    document.querySelector('#camera-start')!.addEventListener('click', () => { cameraReady = false; updateLive(); void camera?.start(); });
  }
}
function resultMarkup() {
  const history = state!.history, last = history.at(-1);
  const best = history.filter(r => r.outcome === 'cleared').sort((a, b) => a.elapsed! - b.elapsed!)[0];
  return `<div class="result-feature"><span class="eyebrow">${last?.outcome === 'cleared' ? 'NICE TEAMWORK' : 'ROUND COMPLETE'}</span><h2>${last ? outcomeNames[last.outcome] : 'ゲーム終了'}</h2><div class="result-time">${time(last?.elapsed ?? null)}</div><p>チームベスト <strong>${time(best?.elapsed ?? null)}</strong>${best ? ` · ROUND ${best.number}` : ''}</p></div>
    <div class="result-list">${history.map(r => `<article class="result-item"><div><span class="eyebrow">ROUND ${r.number}</span><h3>${escape(r.participants[r.poser_id])}<span class="small"> · ポーズ役</span></h3><span class="${r.outcome === 'cleared' ? 'accent' : 'muted'}">${outcomeNames[r.outcome]}</span><details><summary>参加者ごとの結果</summary>${Object.entries(r.participants).filter(([pid]) => pid !== r.poser_id).map(([pid, name]) => `<p>${escape(name)} <strong>${r.cleared[pid] && r.started_at !== null ? time(r.cleared[pid] - r.started_at) : '未クリア'}</strong></p>`).join('')}</details></div><strong class="history-time">${time(r.elapsed)}</strong></article>`).join('')}</div>`;
}
function renderResults() {
  main.innerHTML = `${hero(state!.phase === 'final_result' ? 'THANK YOU FOR PLAYING' : 'ROUND RESULT', state!.phase === 'final_result' ? 'みんなでつくった記録。' : 'ひとつのポーズ、みんなの視点。', state!.phase === 'final_result' ? 'おつかれさまでした！' : '管理者が次のラウンドを準備しています。')}
    <section class="card">${resultMarkup()}</section><div id="result-pose" class="result-pose"></div>`;
  const pose = state!.round?.pose;
  if (pose) {
    const key = viewKey;
    void import('./poser').then(({ showPoser }) => { if (viewKey === key) disposePoser = showPoser(document.querySelector('#result-pose')!, pose.points, state!.me === state!.round!.poser_id); });
  }
}
function field(name: keyof Settings, label: string, min: number, max: number, step = 1) {
  return `<label>${label}<input name="${name}" type="number" min="${min}" max="${max}" step="${step}" value="${state!.settings![name]}" required /></label>`;
}
function renderAdmin() {
  const s = state!.settings!;
  main.innerHTML = `<div class="section-head">${hero('HOST CONSOLE', 'みんなの視点を、ひとつに。', '参加者を確認して、ラウンドを進めましょう。')}<button class="quiet" id="logout">ログアウト</button></div>
    <div class="admin-grid"><section class="card"><div class="section-head"><h2>ゲーム進行</h2><span class="pill" id="phase-label"></span></div><div id="admin-summary"><div class="admin-stats"><div><strong id="admin-player-count">0</strong><span>参加者</span></div><div><strong id="admin-round-number">—</strong><span>ラウンド</span></div><div><strong data-timer>00:00.0</strong><span>経過時間</span></div></div><p id="admin-round-status" class="small"></p></div><div id="admin-actions" class="actions"></div></section>
    <section class="card qr-card"><canvas id="qr"></canvas><div><span class="eyebrow">SCAN TO JOIN</span><h2>このQRから参加</h2><p class="small">会場Wi-Fiに接続して開いてください</p><input id="join-url" aria-label="参加URL" type="url" value="${escape(state!.join_url ?? '')}"/><button id="update-qr" class="quiet">QRを更新</button>${state!.setup_url ? `<button id="setup-qr" class="quiet">初期設定QRを表示</button><a class="small" href="${escape(state!.setup_url)}" target="_blank" rel="noreferrer">証明書の設定手順 ↗</a>` : ''}</div></section></div>
    <section class="card"><div class="section-head"><h2>チームメンバー</h2><span id="member-count" class="pill"></span></div><div id="roster"></div></section>
    <details class="card settings-panel"><summary>判定・ゲーム設定 <span class="small">デフォルトとして保存</span></summary><p class="small">変更は次に準備するラウンドから適用します。現在のラウンドの条件は変わりません。</p>
    <form id="settings-form"><div class="form-grid"><label>クリア方式<select name="clear_mode"><option value="latched" ${s.clear_mode === 'latched' ? 'selected' : ''}>一度達成すれば確定</option><option value="simultaneous" ${s.clear_mode === 'simultaneous' ? 'selected' : ''}>全員が同時に一致</option></select></label>
    ${field('rounds', 'ラウンド数', 1, 100)}${field('round_seconds', '制限時間（秒）', 15, 1800)}${field('hold_seconds', '一致を保つ時間（秒）', 0, 10, .1)}
    ${field('score_threshold', '合格スコア（%）', 20, 100)}${field('confidence_threshold', '関節の信頼度', .1, .95, .05)}
    <label>隠れた関節<select name="hidden_policy"><option value="require" ${s.hidden_policy === 'require' ? 'selected' : ''}>全対象関節が見えることを要求</option><option value="ignore" ${s.hidden_policy === 'ignore' ? 'selected' : ''}>見えない関節を除外</option></select></label>${field('min_visible', '最低限必要な関節数', 4, 12)}
    ${field('azimuth_min', '方位角：最小（°）', -180, 180)}${field('azimuth_max', '方位角：最大（°）', -180, 180)}${field('elevation_min', '仰角：最小（°）', -30, 30)}${field('elevation_max', '仰角：最大（°）', -30, 30)}
    ${field('min_limb_ratio', '手足の最小投影長 / 全高', 0, .3, .01)}${field('min_side_separation', '左右関節の最小間隔 / 全高', 0, .3, .01)}${field('min_keypoint_separation', '全関節点の最小間隔 / 全高', 0, .3, .01)}</div>
    <p class="small">全関節点の最小間隔は、お手本の肩・肘・手首・腰・膝・足首の12点すべてに適用します。0.08は全高の8%、0はこの条件を無効にします。間隔が足りない視点は再生成します。</p>
    <fieldset><legend>判定する関節</legend><div class="joint-grid">${joints.map((j, i) => `<label><input type="checkbox" name="joints" value="${j}" ${s.joints.includes(j) ? 'checked' : ''}/>${jointNames[i]}</label>`).join('')}</div></fieldset><button>デフォルトとして保存</button></form></details>
    <details class="card"><summary>ラウンド履歴</summary><div id="admin-results"></div></details>`;
  const makeQR = () => {
    const value = (document.querySelector('#join-url') as HTMLInputElement).value;
    if (!value) { toast('LAN IPを検出できませんでした。参加URLを入力してください。'); return; }
    try { const url = new URL(value); if (!['http:', 'https:'].includes(url.protocol)) throw new Error(); }
    catch { toast('正しい参加URLを入力してください。'); return; }
    void QRCode.toCanvas(document.querySelector('#qr'), value, { width: 160, margin: 2, color: { dark: '#101827', light: '#ffffff' } }).catch(() => toast('QRコードを作成できませんでした。'));
  };
  makeQR(); document.querySelector('#update-qr')!.addEventListener('click', makeQR);
  document.querySelector('#setup-qr')?.addEventListener('click', () => {
    const input = document.querySelector<HTMLInputElement>('#join-url')!;
    const setup = input.value !== state!.setup_url;
    input.value = setup ? state!.setup_url! : state!.join_url!;
    document.querySelector('#setup-qr')!.textContent = setup ? 'ゲーム参加QRに戻す' : '初期設定QRを表示';
    makeQR();
  });
  document.querySelector('#logout')!.addEventListener('click', async () => {
    await api('logout'); socket?.close(); await refresh();
  });
  document.querySelector('#settings-form')!.addEventListener('submit', async event => {
    event.preventDefault(); const data = new FormData(event.currentTarget as HTMLFormElement);
    const settings: Record<string, unknown> = {};
    for (const [key, value] of data.entries()) {
      if (key === 'joints') continue;
      settings[key] = ['clear_mode', 'hidden_policy'].includes(key) ? value : Number(value);
    }
    settings.joints = data.getAll('joints').map(Number);
    try { await api('admin/settings', settings, 'PUT'); toast('デフォルト設定を保存しました。次のラウンドから適用します。'); await refresh(); }
    catch (error) { toast((error as Error).message); }
  });
}
function updateLive() {
  if (!state) return;
  const s = state, r = s.round;
  const set = (id: string, text: string) => { const el = document.getElementById(id); if (el) el.textContent = text; };
  set('member-count', `${s.players.length} / 50人`);
  set('phase-label', phaseNames[s.phase]);
  const joinButton = document.querySelector<HTMLButtonElement>('#join-button');
  if (joinButton) joinButton.disabled = !s.registration_open || s.phase !== 'waiting' || s.players.length >= 50;
  set('join-status', `${s.players.length}人が参加中 · ${s.registration_open ? '参加受付中' : '受付は終了しました'}`);
  const roster = document.querySelector('#roster');
  if (roster) roster.innerHTML = s.players.map(p => `<div class="player"><div class="avatar">${escape(p.name.slice(0, 1))}</div><div class="player-name"><strong>${escape(p.name)}${p.id === s.me ? ' <span class="small">あなた</span>' : ''}</strong><span class="small">${r?.poser_id === p.id && s.phase !== 'waiting' ? 'ポーズ役' : p.connected ? '接続済み' : '再接続待ち'}</span></div><span class="player-status ${p.cleared || p.matched ? 'accent' : ''}">${s.phase === 'round_setup' ? p.ready ? '準備OK' : '準備中' : s.phase === 'playing' ? p.cleared ? '✓ CLEAR' : p.matched ? '一致中' : r?.poser_id === p.id ? 'POSE' : `${Math.round(p.score)}%` : p.connected ? '●' : '○'}</span>${s.admin ? `<button class="quiet remove" data-player="${p.id}" aria-label="${escape(p.name)}を除外">除外</button>` : ''}</div>`).join('') || '<p class="empty">参加者を待っています</p>';
  document.querySelectorAll<HTMLButtonElement>('.remove').forEach(button => button.addEventListener('click', () => {
    const name = s.players.find(p => p.id === button.dataset.player)?.name;
    if (confirm(`${name}さんをこのゲームから除外しますか？`)) void action('remove', { player_id: button.dataset.player });
  }));
  if (r) {
    const observers = s.players.filter(p => p.id !== r.poser_id);
    set('clear-count', `${observers.filter(p => p.cleared).length} / ${observers.length} CLEAR`);
    set('round-message', s.phase === 'round_setup' ? '準備ができたらボタンを押してください。全員そろったら管理者が開始します。'
      : `${r.settings.clear_mode === 'latched' ? '一度クリアすれば確定' : '全員が同時に一致'} · ${r.settings.hold_seconds}秒キープ · 制限 ${r.settings.round_seconds}秒`);
    const ready = document.querySelector<HTMLButtonElement>('#ready-button');
    if (ready) {
      ready.hidden = s.phase !== 'round_setup';
      const me = s.players.find(p => p.id === s.me);
      ready.disabled = !!me?.ready || (s.me !== r.poser_id && !cameraReady);
      ready.textContent = me?.ready ? '✓ 準備完了 · 開始を待っています' : s.me === r.poser_id ? 'ポーズの準備完了' : 'カメラの準備完了';
    }
  }
  if (s.admin && adminPage) {
    const readyCount = s.players.filter(p => p.ready && p.connected).length;
    set('admin-player-count', String(s.players.length));
    set('admin-round-number', String(r?.number ?? '—'));
    set('admin-round-status', s.phase === 'round_setup' ? `${readyCount} / ${s.players.length}人が準備完了`
      : r && s.phase === 'playing' ? `ポーズ役：${s.players.find(p => p.id === r.poser_id)?.name ?? ''}` : '参加者と準備状況を確認して進めてください。');
    const buttons: [string, string, string?][] = s.phase === 'waiting' ? [['setup', 'ゲームを準備'], ['registration', s.registration_open ? '受付を閉じる' : '受付を開く', 'secondary'], ['end', 'ゲーム終了', 'quiet']]
      : s.phase === 'round_setup' ? [['start', 'ラウンド開始'], ['skip', 'スキップ', 'secondary'], ['end', 'ゲーム終了', 'quiet']]
      : s.phase === 'playing' ? [['cancel', 'ラウンド中止', 'secondary'], ['skip', 'スキップ', 'secondary'], ['end', 'ゲーム終了', 'quiet']]
      : s.phase === 'round_result' ? [['setup', s.history.length >= s.settings!.rounds ? '最終結果へ' : '次のラウンドを準備'], ['end', 'ゲーム終了', 'secondary']]
      : [['new_event', '次のグループを受付']];
    document.querySelector('#admin-actions')!.innerHTML = buttons.map(([a, label, cls]) => `<button data-action="${a}" class="${cls ?? ''}" ${a === 'start' && readyCount < s.players.length ? 'disabled' : ''}>${label}</button>`).join('');
    document.querySelectorAll<HTMLButtonElement>('[data-action]').forEach(button => button.addEventListener('click', () => {
      const a = button.dataset.action!;
      if (['end', 'cancel', 'skip'].includes(a) && !confirm(`${button.textContent}しますか？`)) return;
      if (a === 'new_event') {
        const name = prompt('次のグループのイベント名', 'Pose Parallax');
        if (name === null) return;
        void action(a, { name: name.trim() || 'Pose Parallax' });
      } else void action(a);
    }));
    const results = document.querySelector('#admin-results')!;
    // Avoid replacing expanded details unless the results changed.
    const key = JSON.stringify(s.history);
    if (results.getAttribute('data-key') !== key) { results.innerHTML = s.history.length ? resultMarkup() : '<p class="empty">まだラウンドの記録がありません。</p>'; results.setAttribute('data-key', key); }
  }
}
async function action(action: string, extras = {}) {
  try { await api('admin/action', { action, ...extras }); await refresh(); }
  catch (error) { toast((error as Error).message); }
}
function feedback(data: Feedback) {
  const score = document.querySelector('#score'); if (!score) return;
  score.innerHTML = `${Math.round(data.score)}<span>%</span>`;
  const bar = document.querySelector<HTMLElement>('#score-bar')!;
  bar.style.width = `${data.score}%`; bar.classList.toggle('matched', data.matched);
  document.querySelector('#match-reason')!.textContent = data.cleared ? '✓ クリア！仲間に声をかけよう' : `${data.reason}${data.matched ? ` (${data.hold.toFixed(1)}秒)` : ''}`;
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
