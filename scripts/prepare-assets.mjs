import { createHash } from 'node:crypto';
import { mkdir, cp, readFile, writeFile, rename, readdir, rm } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const publicDir = path.join(root, 'frontend/public');
// Preserve notices for production dependencies even after JS minification.
const licenses = path.join(publicDir, 'licenses/npm');
await rm(licenses, { recursive: true, force: true });
const lock = JSON.parse(await readFile(path.join(root, 'package-lock.json'), 'utf8'));
for (const [folder, metadata] of Object.entries(lock.packages)) {
  if (!folder || metadata.dev || folder === 'node_modules/@mediapipe/tasks-vision') continue;
  const source = path.join(root, folder);
  const notices = (await readdir(source)).filter(name => /^(licen[sc]e|copying|notice)([.-]|$)/i.test(name));
  if (!notices.length) throw new Error(`Missing license: ${folder}`);
  const destination = path.join(licenses, folder.replace(/^node_modules\//, ''));
  await mkdir(destination, { recursive: true });
  for (const name of notices) await cp(path.join(source, name), path.join(destination, name));
}
await cp(path.join(root, 'LICENSE'), path.join(publicDir, 'licenses/PoseParallax-LICENSE'));
await mkdir(path.join(publicDir, 'models'), { recursive: true });
await cp(path.join(root, 'node_modules/@mediapipe/tasks-vision/wasm'), path.join(publicDir, 'wasm'), { recursive: true });
const model = path.join(publicDir, 'models/pose_landmarker_lite.task');
const expectedHash = '59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a';
const valid = data => createHash('sha256').update(data).digest('hex') === expectedHash;
try {
  if (!valid(await readFile(model))) throw new Error('Model checksum mismatch');
  console.log('Pose model is already available.');
} catch {
  const url = 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task';
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Model download failed: ${response.status}`);
  const data = new Uint8Array(await response.arrayBuffer());
  if (!valid(data)) throw new Error('Downloaded model checksum mismatch');
  await writeFile(model + '.tmp', data);
  await rename(model + '.tmp', model);
  console.log(`Downloaded pose model (${(data.byteLength / 1e6).toFixed(1)} MB).`);
}
console.log('Inference assets are served locally; no runtime CDN is required.');
