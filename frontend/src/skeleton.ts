import type { Point } from './types';
import { edges, joints } from './types';
import { boneGroup, skeletonColors } from './skeleton-style';

type XY = [number, number];

export function drawSkeleton(canvas: HTMLCanvasElement, points: Point[], fit = true, confidence = 0.3) {
  const ctx = canvas.getContext('2d')!;
  const { width: w, height: h } = canvas;
  ctx.clearRect(0, 0, w, h);
  const visible = (i: number) => points[i]?.[2] >= confidence;
  const valid = joints.filter(visible);
  if (!valid.length) return;
  const hasFace = visible(0) && visible(11) && visible(12);
  const bounds = hasFace ? [...valid, 0] : valid;
  let scaleX = w, scaleY = h, ox = 0, oy = 0;
  if (fit) {
    const minX = Math.min(...bounds.map(i => points[i][0]));
    const maxX = Math.max(...bounds.map(i => points[i][0]));
    const minY = Math.min(...bounds.map(i => points[i][1]));
    const maxY = Math.max(...bounds.map(i => points[i][1]));
    scaleX = scaleY = Math.min(w * .72 / (maxX - minX || 1), h * .74 / (maxY - minY || 1));
    ox = w / 2 - (minX + maxX) / 2 * scaleX;
    oy = h / 2 - (minY + maxY) / 2 * scaleY;
  }
  const xy = (i: number): XY => [points[i][0] * scaleX + ox, points[i][1] * scaleY + oy];
  const line = (a: XY, b: XY) => { ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke(); };
  const bodyWidth = fit ? 6 : Math.max(3, w / 150);
  ctx.lineWidth = bodyWidth;
  ctx.lineCap = 'round';
  for (const [a, b] of edges) {
    if (!visible(a) || !visible(b)) continue;
    ctx.strokeStyle = skeletonColors[boneGroup(a, b)];
    line(xy(a), xy(b));
  }
  if (hasFace) {
    const head = xy(0), left = xy(11), right = xy(12);
    const shoulderMid: XY = [(left[0] + right[0]) / 2, (left[1] + right[1]) / 2];
    const shoulderWidth = Math.hypot(left[0] - right[0], left[1] - right[1]);
    const neck = Math.hypot(shoulderMid[0] - head[0], shoulderMid[1] - head[1]);
    if (shoulderWidth > 1 && neck > 1) {
      const across: XY = [(left[0] - right[0]) / shoulderWidth, (left[1] - right[1]) / shoulderWidth];
      const down: XY = [(shoulderMid[0] - head[0]) / neck, (shoulderMid[1] - head[1]) / neck];
      const offset = (x: number, y: number): XY => [head[0] + across[0] * x + down[0] * y, head[1] + across[1] * x + down[1] * y];
      // Landmarks determine the head size; observer views show a plain sphere.
      const eyeHalf = shoulderWidth * .13;
      const eyes: XY[] = !fit && visible(2) && visible(5) ? [xy(2), xy(5)]
        : [offset(eyeHalf, -neck * .1), offset(-eyeHalf, -neck * .1)];
      const mouth: XY[] = !fit && visible(9) && visible(10) ? [xy(9), xy(10)]
        : [offset(eyeHalf * .9, neck * .2), offset(-eyeHalf * .9, neck * .2)];
      const middle: XY = [(mouth[0][0] + mouth[1][0]) / 2, (mouth[0][1] + mouth[1][1]) / 2];
      const bend = Math.hypot(mouth[0][0] - mouth[1][0], mouth[0][1] - mouth[1][1]) * .45;
      const control: XY = [middle[0] + down[0] * bend, middle[1] + down[1] * bend];
      const chin: XY = [middle[0] + down[0] * (bend * .5 + bodyWidth), middle[1] + down[1] * (bend * .5 + bodyWidth)];
      ctx.strokeStyle = ctx.fillStyle = skeletonColors.center;
      line(chin, left); line(chin, right);
      const headRadius = Math.max(...[...eyes, ...mouth, control].map(p => Math.hypot(p[0] - head[0], p[1] - head[1]))) * 1.35;
      const shade = ctx.createRadialGradient(head[0] - headRadius * .3, head[1] - headRadius * .3, 0, ...head, headRadius);
      shade.addColorStop(0, skeletonColors.center); shade.addColorStop(1, '#419d9b');
      ctx.fillStyle = shade;
      ctx.beginPath(); ctx.arc(...head, headRadius, 0, Math.PI * 2); ctx.fill();
    }
  }
  for (const i of valid) {
    ctx.fillStyle = skeletonColors[i % 2 === 1 ? 'left' : 'right'];
    ctx.beginPath(); ctx.arc(...xy(i), fit ? 5 : Math.max(3, w / 180), 0, Math.PI * 2); ctx.fill();
  }
}
