import { build } from 'esbuild';

// MediaPipe's WASM loader uses importScripts. A classic IIFE worker is required;
// module workers fail even when GPU is disabled. Serve this same bundle in dev and production.
await build({
  entryPoints: ['frontend/src/inference.worker.ts'],
  outfile: 'frontend/public/inference-worker.js',
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: 'es2022',
  minify: true,
});
