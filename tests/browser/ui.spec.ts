import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

test('certificate setup preserves the invitation when switching language', async ({ page }) => {
  const pages = JSON.parse(execFileSync('.venv/bin/python', ['-c', `
import json
from server.setup_page import setup_html
print(json.dumps({lang:setup_html('https://game.example/','AB:CD',lang,False).decode() for lang in ('ja','en')}))
`], {encoding:'utf8'}));
  await page.route('**/?lang=*', route => route.fulfill({contentType:'text/html',
    body:pages[new URL(route.request().url()).searchParams.get('lang')!]}));
  await page.goto('/?lang=ja#invite=original-token');
  await expect(page.getByRole('link', {name:'ゲームを開く',exact:true})).toHaveAttribute('href', 'https://game.example/#invite=original-token');
  await page.getByRole('link', {name:'English',exact:true}).click();
  await expect(page.getByRole('link', {name:'Open game',exact:true})).toHaveAttribute('href', 'https://game.example/#invite=original-token');
  await page.getByRole('link', {name:'日本語',exact:true}).click();
  await expect(page.getByRole('link', {name:'ゲームを開く',exact:true})).toHaveAttribute('href', 'https://game.example/#invite=original-token');
});

const settings = { clear_mode: 'latched', rounds: 4, round_seconds: 120, hold_seconds: 1, score_threshold: 70, confidence_threshold: .5, hidden_policy: 'require', min_visible: 8, joints: [11,12,13,14,15,16,23,24,25,26,27,28], azimuth_min: -90, azimuth_max: 90, elevation_min: -15, elevation_max: 15, min_limb_ratio: .08, min_side_separation: .08, min_keypoint_separation: .08 };
const players = [{ id: 'a', name: 'クリア', connected: true, ready: false, cleared: false, matched: false, score: 0 }, { id: 'b', name: 'Welcome', connected: true, ready: false, cleared: false, matched: false, score: 0 }];
const target = Array.from({ length: 33 }, (_, i) => [.2 + (i % 4) * .15, .1 + Math.floor(i / 4) * .09, 1]);
const round = { id: 'round', number: 1, poser_id: 'b', target, started_at: Date.now()/1000 - 2, ended_at: null, outcome: null, cleared: {}, settings };
const snapshot = { type: 'state', join_url: 'https://game.example/', setup_url: null, event_id: 'event', name: 'クリア', phase: 'waiting', registration_open: true, me: null as string | null, admin: false, players, round: null as any, history: [] as any[], server_time: Date.now()/1000, settings };

for (const viewport of [{ width: 320, height: 568 }, { width: 390, height: 844 }, { width: 844, height: 390 }]) {
  test(`compact bilingual observer ${viewport.width}x${viewport.height}`, async ({ page }, info) => {
    await page.setViewportSize(viewport);
    const state = { ...snapshot, me: 'a', phase: 'playing', round };
    await page.route('**/api/state', route => route.fulfill({ json: state }));
    await page.routeWebSocket('**/ws', ws => ws.send(JSON.stringify(state)));
    await page.goto('/');
    await expect(page.locator('#camera-video')).toBeAttached();
    await page.evaluate(() => { (window as any).__camera = document.querySelector('#camera-video'); });
    await page.getByLabel('Language / 言語').selectOption('en');
    await expect(page.locator('.round-top h1')).toHaveText('Find your perspective');
    await expect(page.getByRole('button', { name: 'Start camera / Retry', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Details', exact: true }).click();
    await expect(page.locator('#round-message')).toContainText('Hold 1s · Limit 120s');
    await expect(page.locator('#roster [data-user-content]').filter({ hasText: /^クリア$/ })).toBeVisible();
    await expect(page.locator('#round-details')).toContainText('Left');
    await page.locator('#round-details').getByRole('button', { name: 'Close', exact: true }).click();
    await page.getByRole('button', { name: 'Enlarge target' }).click();
    await expect(page.locator('#large-target')).toBeVisible();
    await page.locator('#target-dialog').getByRole('button', { name: 'Close', exact: true }).click();
    expect(await page.evaluate(() => document.querySelector('#camera-video') === (window as any).__camera)).toBeTruthy();
    const layout = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight, screenWidth: innerWidth, screenHeight: innerHeight }));
    expect(layout.width).toBeLessThanOrEqual(layout.screenWidth);
    expect(layout.height).toBeLessThanOrEqual(layout.screenHeight + 1);
    const cameraBox = (await page.locator('.camera-stage').boundingBox())!;
    expect(cameraBox.width).toBe(viewport.width);
    expect(cameraBox.height).toBeGreaterThan(viewport.height * .84);
    for (const selector of ['#show-details', '#enlarge-target', '.match-strip']) {
      const box = (await page.locator(selector).boundingBox())!;
      expect(box.y).toBeGreaterThanOrEqual(cameraBox.y);
      expect(box.y + box.height).toBeLessThanOrEqual(cameraBox.y + cameraBox.height);
    }
    await page.screenshot({ path: info.outputPath(`observer-en-${viewport.width}.png`) });
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('.round-top h1')).toHaveText('Find your perspective');
    await page.getByLabel('Language / 言語').selectOption('ja');
    await expect(page.locator('.round-top h1')).toHaveText('視点を見つけよう');
  });
}

test('language preserves forms, user content and expanded admin settings; errors are English', async ({ page }) => {
  let state = { ...snapshot };
  await page.route('**/api/**', route => {
    if (route.request().url().endsWith('/api/state')) return route.fulfill({ json: state });
    return route.fulfill({ status: 401, json: { detail: 'パスワードが違います。' } });
  });
  await page.routeWebSocket('**/ws', ws => ws.send(JSON.stringify(state)));
  await page.goto('/');
  await page.getByLabel('表示名', { exact: true }).fill('ひこうき');
  await page.getByLabel('Language / 言語').selectOption('en');
  await expect(page.getByLabel('Display name', { exact: true })).toHaveValue('ひこうき');
  await expect(page.locator('.join-card h2')).toHaveText('クリア');
  await expect(page.locator('.join-grid h1')).toContainText('Same pose.');
  await page.goto('/admin');
  await page.getByLabel('Admin password', { exact: true }).fill('wrong-password');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Incorrect password.');
  state = { ...state, admin: true };
  await page.reload();
  await page.locator('.settings-panel > summary').click();
  await page.getByLabel('Hold duration (seconds)', { exact: true }).fill('2.5');
  await page.getByLabel('Language / 言語').selectOption('ja');
  await expect(page.getByLabel('一致を保つ時間（秒）', { exact: true })).toBeVisible();
  await expect(page.getByLabel('一致を保つ時間（秒）', { exact: true })).toHaveValue('2.5');
  await page.getByLabel('Language / 言語').selectOption('en');
  await expect(page.getByLabel('Hold duration (seconds)', { exact: true })).toHaveValue('2.5');
  await expect(page.locator('#phase-label')).toHaveText('Registration');
});

test('English results retain access to all previous rounds and individual records', async ({ page }) => {
  const record = { ...round, outcome: 'cleared', participants: { a: 'クリア', b: 'Welcome' }, cleared: { a: round.started_at + 2 }, elapsed: 2 };
  const state = { ...snapshot, me: 'a', phase: 'final_result', history: [record] };
  await page.route('**/api/state', route => route.fulfill({ json: state }));
  await page.routeWebSocket('**/ws', ws => ws.send(JSON.stringify(state)));
  await page.goto('/');
  await page.getByLabel('Language / 言語').selectOption('en');
  await expect(page.getByRole('heading', { name: 'Cleared', exact: true })).toBeVisible();
  await page.getByText('Round history & individual results', { exact: true }).click();
  await page.getByText('Individual results', { exact: true }).click();
  await expect(page.locator('.result-item p [data-user-content]')).toHaveText('クリア');
  await expect(page.locator('.result-item p strong')).toHaveText('00:02.0');
});
