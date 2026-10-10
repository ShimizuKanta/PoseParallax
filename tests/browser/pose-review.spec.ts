import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import * as THREE from 'three';
import { setTargetCamera } from '../../frontend/src/pose-view';
import { joints } from '../../frontend/src/types';

const fixtures = JSON.parse(execFileSync('.venv/bin/python', ['-c', `
import json
from server.poses import POSES, project
print(json.dumps([{'pose':p, 'target':project(p['points'],a,12),
                  'view':{'azimuth':a,'elevation':12,'distance':3,'target_height':.95,'focal_scale':1}}
                 for p in POSES for a in (0,65,145)]))
`], { encoding: 'utf8' }));

// Compare independent Python projection with the actual Three.js camera,
// accounting for the uniform fitting used to display the 2D target.
test('review camera preserves the target shape on portrait and landscape screens', () => {
  const normalized = (points: number[][]) => {
    const center = [0, 1].map(axis => points.reduce((sum, p) => sum + p[axis], 0) / points.length);
    const radius = Math.sqrt(points.reduce((sum, p) => sum + (p[0]-center[0])**2 + (p[1]-center[1])**2, 0) / points.length);
    return points.map(p => [(p[0]-center[0])/radius, (p[1]-center[1])/radius]);
  };
  for (const fixture of fixtures) for (const aspect of [.4, 1, 2]) {
    const camera = new THREE.PerspectiveCamera(40, aspect, .1, 100);
    setTargetCamera(camera, fixture.pose.points, fixture.view);
    expect(camera.position.distanceTo(new THREE.Vector3(0, .95, 0))).toBeCloseTo(3, 10);
    const actual = joints.map(i => {
      const p = new THREE.Vector3(...fixture.pose.points[i]).project(camera);
      expect(Math.abs(p.x)).toBeLessThan(1);
      expect(Math.abs(p.y)).toBeLessThan(1);
      return [p.x * aspect, -p.y];
    });
    const goal = normalized(joints.map(i => fixture.target[i]));
    normalized(actual).forEach((p,i) => p.forEach((value,axis) => expect(value).toBeCloseTo(goal[i][axis], 10)));
  }
});

test('observer can rotate, zoom and reset the result to their target; poser has no reset', async ({ page }, info) => {
  const fixture = fixtures.find((f: any) => f.pose.id === 'marching' && f.view.azimuth === 145);
  const round = { id:'review-round', number:1, poser_id:'b', pose:fixture.pose,
    target:fixture.target, target_view:fixture.view, started_at:100, ended_at:105,
    cleared:{a:105}, outcome:'cleared', settings:{} };
  let state = { type:'state', event_id:'review-event', name:'Pose Parallax', phase:'round_result',
    me:'a', admin:false, players:[{id:'a',name:'Observer'},{id:'b',name:'Poser'}],
    round, history:[{...round,participants:{a:'Observer',b:'Poser'},elapsed:5}], server_time:105 };
  await page.route('**/api/state', route => route.fulfill({json:state}));
  await page.routeWebSocket('**/ws', ws => ws.send(JSON.stringify(state)));
  await page.goto('/');
  const reset = page.getByRole('button', {name:'自分のお手本の視点に戻す', exact:true});
  await expect(reset).toBeEnabled();
  await expect(page.locator('#review-target')).toBeVisible();
  const canvas = page.locator('#result-pose canvas');
  const settle = () => page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await reset.click();
  await settle();
  const original = await canvas.screenshot();
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5);
  await page.mouse.down();
  await page.mouse.move(box.x+box.width*.8,box.y+box.height*.65,{steps:10});
  await page.mouse.up();
  await page.mouse.wheel(0,200);
  await settle();
  expect((await canvas.screenshot()).equals(original)).toBe(false);
  await page.getByLabel('Language / 言語').selectOption('en');
  await page.getByRole('button', {name:'Reset to my target view',exact:true}).click();
  await settle();
  expect((await canvas.screenshot()).equals(original)).toBe(true);
  await page.screenshot({path:info.outputPath('review-target-view.png'),fullPage:true});
  await page.setViewportSize({width:844,height:390});
  await page.getByRole('button',{name:'Reset to my target view',exact:true}).click();
  await expect(canvas).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.reload();
  await expect(page.getByRole('button',{name:'Reset to my target view',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'Reset to my target view',exact:true}).click();
  state = {...state, me:'b', round:{...round,target:undefined,target_view:undefined} as any};
  await page.reload();
  await expect(canvas).toBeVisible();
  await expect(page.locator('#reset-target-view')).toHaveCount(0);
});
