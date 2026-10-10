import { test, expect } from '@playwright/test';

test('mobile join, real model initialization, admin setup, clear and next group', async ({ browser }, testInfo) => {
  const options = { viewport: { width: 390, height: 844 }, baseURL: 'http://127.0.0.1:8011' };
  const host = await browser.newContext({ ...options, viewport: { width: 1280, height: 900 } });
  const hostPage = await host.newPage();
  const a = await browser.newContext(options), b = await browser.newContext(options);
  // Capture the actual application socket so deterministic landmarks can test the full scoring path.
  // Real inference is separately exercised with Chromium's synthetic camera below.
  for (const context of [a, b]) await context.addInitScript(() => {
    (window as any).__sockets = [];
    window.WebSocket = new Proxy(window.WebSocket, {
      construct(Target, args) {
        const ws = new Target(...args as [string]);
        (window as any).__sockets.push(ws);
        return ws;
      },
    });
  });
  const pages = [await a.newPage(), await b.newPage()];
  const errors: string[] = [];
  for (const page of [hostPage, ...pages]) page.on('pageerror', error => errors.push(error.message));
  try {
    await hostPage.goto('/admin');
    await hostPage.getByLabel('管理者パスワード').fill('browser-test-password');
    await hostPage.getByRole('button', { name: 'ログイン', exact: true }).click();
    await expect(hostPage.getByRole('heading', { name: 'ゲーム進行' })).toBeVisible();
    await expect(hostPage.getByLabel('参加URL')).toHaveValue(/^http:\/\/192\.0\.2\.40:8011\/#invite=/);
    await hostPage.getByText('判定・ゲーム設定', { exact: false }).click();
    await hostPage.getByLabel('一致を保つ時間（秒）').fill('0');
    await hostPage.getByLabel('全関節点の最小間隔 / 全高', { exact: true }).fill('0.10');
    await hostPage.getByRole('button', { name: 'デフォルトとして保存', exact: true }).click();
    await expect(hostPage.getByRole('status')).toContainText('保存しました');
    expect((await (await host.request.get('/api/state')).json()).settings.min_keypoint_separation).toBe(.1);

    for (const [i, page] of pages.entries()) {
      const inviteUrl = new URL(await hostPage.getByLabel('参加URL').inputValue());
      await page.goto('/' + inviteUrl.hash);
      if (i === 0) await page.screenshot({ path: testInfo.outputPath('mobile-join.png'), fullPage: true });
      await page.getByLabel('表示名').fill(i === 0 ? 'あおい' : 'かんた');
      await page.getByRole('button', { name: '参加する' }).click();
      await expect(page.getByRole('heading', { name: '仲間を待っています' })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    }
    await expect(hostPage.locator('#member-count')).toHaveText('2 / 50人');
    await hostPage.getByRole('button', { name: 'ゲームを準備' }).click();
    const current = await (await host.request.get('/api/state')).json();
    const identities = await Promise.all([a, b].map(async context => (await (await context.request.get('/api/state')).json()).me));
    const poserIndex = identities.indexOf(current.round.poser_id);
    const poser = pages[poserIndex], observer = pages[1 - poserIndex];
    await expect(poser.getByRole('heading', { name: 'あなたがポーズ役' })).toBeVisible();
    await expect(poser.locator('#poser-view canvas')).toBeVisible();
    await poser.screenshot({ path: testInfo.outputPath('poser-ready.png'), fullPage: true });
    await poser.getByRole('button', { name: 'ポーズの準備完了' }).click();
    await observer.getByRole('button', { name: 'カメラを起動 / 再試行' }).click();
    await expect(observer.getByRole('button', { name: 'カメラの準備完了' })).toBeEnabled({ timeout: 60000 });
    await expect.poll(async () => observer.locator('#camera-overlay').evaluate((canvas: HTMLCanvasElement) => canvas.width > 0 && canvas.width === (document.querySelector('#camera-video') as HTMLVideoElement).videoWidth), { timeout: 15000 }).toBeTruthy();
    const cameraBefore = await observer.evaluate(() => {
      const video = document.querySelector('#camera-video') as HTMLVideoElement;
      (window as any).__originalVideo = video;
      return (video.srcObject as MediaStream).getVideoTracks()[0].id;
    });
    await observer.getByLabel('Language / 言語').selectOption('en');
    await expect(observer.getByRole('heading', { name: 'Find your perspective' })).toBeVisible();
    await expect(observer.getByRole('button', { name: 'Camera ready', exact: true })).toBeEnabled();
    expect(await observer.evaluate(() => {
      const video = document.querySelector('#camera-video') as HTMLVideoElement;
      return video === (window as any).__originalVideo && (video.srcObject as MediaStream).getVideoTracks()[0].readyState === 'live';
    })).toBeTruthy();
    expect(await observer.evaluate(() => ((document.querySelector('#camera-video') as HTMLVideoElement).srcObject as MediaStream).getVideoTracks()[0].id)).toBe(cameraBefore);
    await observer.getByLabel('Language / 言語').selectOption('ja');
    await observer.getByRole('button', { name: 'カメラの準備完了' }).click();
    await expect(hostPage.getByRole('button', { name: 'ラウンド開始', exact: true })).toBeEnabled();
    await hostPage.screenshot({ path: testInfo.outputPath('admin-ready.png'), fullPage: true });
    await hostPage.getByRole('button', { name: 'ラウンド開始', exact: true }).click();
    // Observe what the user sees across several server snapshots, not just one timer tick.
    await expect.poll(async () => hostPage.locator('[data-timer]').textContent()).not.toBe('00:00.0');
    await hostPage.evaluate(() => {
      const summary = document.querySelector('#admin-summary')!;
      (window as any).__timerReadings = [];
      (window as any).__timerObserver = new MutationObserver(() => {
        (window as any).__timerReadings.push(summary.querySelector('[data-timer]')?.textContent ?? '');
      });
      (window as any).__timerObserver.observe(summary, { childList: true, subtree: true, characterData: true });
    });
    await expect.poll(async () => {
      const text = await hostPage.locator('[data-timer]').textContent();
      const [minutes, seconds] = text!.split(':').map(Number);
      return minutes * 60 + seconds;
    }).toBeGreaterThanOrEqual(1.6);
    const timerReadings = await hostPage.evaluate(() => {
      (window as any).__timerObserver.disconnect();
      return (window as any).__timerReadings as string[];
    });
    expect(timerReadings.length).toBeGreaterThan(5);
    expect(timerReadings.every(text => text !== '' && text !== '00:00.0')).toBeTruthy();

    const cameraBox = await observer.locator('.camera-stage').boundingBox();
    expect(cameraBox!.height).toBeGreaterThan(844 * .65);
    await observer.getByRole('button', { name: '詳細', exact: true }).click();
    await expect(observer.locator('#round-message')).toContainText('一度クリアすれば確定');
    await observer.getByLabel('Language / 言語').selectOption('en');
    await expect(observer.locator('#round-message')).toContainText('Hold 0s');
    await observer.locator('#round-details').getByRole('button', { name: 'Close', exact: true }).click();
    await observer.getByRole('button', { name: 'Enlarge target' }).click();
    await expect(observer.locator('#large-target')).toBeVisible();
    await observer.locator('#target-dialog').getByRole('button', { name: 'Close', exact: true }).click();
    await observer.setViewportSize({ width: 844, height: 390 });
    expect(await observer.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await observer.setViewportSize({ width: 390, height: 844 });
    await observer.getByLabel('Language / 言語').selectOption('ja');
    await observer.screenshot({ path: testInfo.outputPath('observer-playing.png'), fullPage: true });
    expect(await observer.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();

    const observerState = await (await [a, b][1 - poserIndex].request.get('/api/state')).json();
    // Replace subsequent inference payloads on the real socket with exact target coordinates.
    // Keeping the stream alive avoids racing the server's per-player rate limit.
    await observer.evaluate(payload => {
      const ws = (window as any).__sockets.findLast((ws: WebSocket) => ws.readyState === WebSocket.OPEN);
      const originalSend = ws.send.bind(ws);
      ws.send = (data: string) => {
        const frame = JSON.parse(data);
        if (frame.type === 'pose') frame.keypoints = payload.target;
        originalSend(JSON.stringify(frame));
      };
      ws.send(JSON.stringify({ type: 'pose', round_id: payload.id, keypoints: payload.target }));
    }, observerState.round);
    await expect(observer.getByRole('heading', { name: 'クリア', exact: true })).toBeVisible();
    await expect(poser.getByRole('heading', { name: 'クリア', exact: true })).toBeVisible();
    await observer.screenshot({ path: testInfo.outputPath('round-result.png'), fullPage: true });
    await observer.reload();
    await expect(observer.getByRole('heading', { name: 'クリア', exact: true })).toBeVisible();
    hostPage.once('dialog', dialog => dialog.accept());
    await hostPage.getByRole('button', { name: 'ゲーム終了', exact: true }).click();
    await expect(observer.getByRole('heading', { name: 'みんなでつくった記録。' })).toBeVisible();
    hostPage.once('dialog', dialog => dialog.accept('次のグループ'));
    await hostPage.getByRole('button', { name: '次のグループを受付' }).click();
    await expect(hostPage.locator('#member-count')).toHaveText('0 / 50人');
    await expect(observer.getByRole('button', { name: '参加する' })).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    await a.close(); await b.close(); await host.close();
  }
});
