import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';

const directory = await mkdtemp(join(tmpdir(), 'pose-parallax-test-'));
const child = spawn('.venv/bin/uvicorn', ['server.app:app', '--host', '127.0.0.1', '--port', '8011'], {
  stdio: 'inherit', env: { ...process.env, POSE_DATA_DIR: directory, POSE_ADMIN_PASSWORD: 'browser-test-password', POSE_LAN_IP: '192.0.2.40', POSE_PUBLIC_URL: '' },
});
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('exit', async code => { await rm(directory, { recursive: true, force: true }); process.exit(code ?? 0); });
