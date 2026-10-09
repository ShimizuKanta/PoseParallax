import { drawSkeleton } from './skeleton';
import type { Point } from './types';

interface Landmark { x: number; y: number; visibility: number }

export class Camera {
  private worker: Worker | null = null;
  private stream: MediaStream | null = null;
  private running = false;
  private busy = false;
  private lastFrame = -1;
  private timer = 0;
  private initTimer = 0;
  private generation = 0;
  private resizeTimer = 0;
  private constraints(): MediaTrackConstraints {
    const stage = this.video.parentElement!;
    const aspect = Math.max(.3, Math.min(3, stage.clientWidth / Math.max(1, stage.clientHeight)));
    return {
      facingMode: { ideal: 'environment' },
      width: { ideal: Math.round(aspect < 1 ? 640 * aspect : 640) },
      height: { ideal: Math.round(aspect < 1 ? 640 : 640 / aspect) },
      aspectRatio: { ideal: aspect }, frameRate: { ideal: 15, max: 24 },
    };
  }
  private onResize = () => {
    clearTimeout(this.resizeTimer);
    const generation = this.generation;
    this.resizeTimer = window.setTimeout(() => {
      if (generation === this.generation) void this.stream?.getVideoTracks()[0]?.applyConstraints(this.constraints()).catch(() => {});
    }, 250);
  };
  private onVisibility = () => { if (document.hidden) this.onPoints(Array.from({ length: 33 }, () => [0, 0, 0])); };
  constructor(private video: HTMLVideoElement, private canvas: HTMLCanvasElement,
              private status: (message: string) => void, private onPoints: (points: Point[]) => void,
              private onReady: (ready: boolean) => void) {}

  async start() {
    this.stop();
    const generation = this.generation;
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        throw new Error('カメラにはHTTPSが必要です。管理者の案内したURLで開いてください。');
      }
      this.status('カメラへのアクセスを許可してください');
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false, video: this.constraints(),
      });
      if (generation !== this.generation) { stream.getTracks().forEach(t => t.stop()); return; }
      this.stream = stream; this.video.srcObject = stream;
      await this.video.play();
      if (generation !== this.generation) return;
      this.status('姿勢モデルを読み込んでいます…');
      this.worker = new Worker('/inference-worker.js');
      const initTimeout = this.initTimer = window.setTimeout(() => { this.status('モデルの準備に時間がかかっています。再試行してください。'); this.stop(); }, 60000);
      this.worker.onmessage = (event) => {
        if (generation !== this.generation) return;
        const data = event.data;
        if (data.type === 'ready') {
          clearTimeout(initTimeout);
          this.running = true; this.busy = false;
          this.status('中央にポーズ役の全身を映してください');
          this.onReady(true); this.loop();
        } else if (data.type === 'result') {
          this.busy = false;
          const poses: Landmark[][] = data.poses;
          const aspect = this.video.videoWidth / this.video.videoHeight;
          const centerDistance = (pose: Landmark[]) => {
            const torso = [11, 12, 23, 24].map(i => pose[i]).filter(p => p.visibility >= .3);
            if (torso.length < 2) return Infinity;
            const x = torso.reduce((v, p) => v + p.x, 0) / torso.length;
            const y = torso.reduce((v, p) => v + p.y, 0) / torso.length;
            return Math.hypot((x - .5) * aspect, y - .5);
          };
          const person = poses.filter(p => Number.isFinite(centerDistance(p))).sort((a, b) => centerDistance(a) - centerDistance(b))[0];
          const raw: Point[] = person ? person.map(p => [p.x, p.y, Math.max(0, Math.min(1, p.visibility ?? 0))])
            : Array.from({ length: 33 }, () => [0, 0, 0]);
          this.canvas.width = this.video.videoWidth; this.canvas.height = this.video.videoHeight;
          drawSkeleton(this.canvas, raw, false);
          // Use square-coordinate units for scoring: normalized x/y alone distort non-square videos.
          this.onPoints(raw.map(([x, y, c]) => [x * aspect, y, c]));
        } else if (data.type === 'error') {
          clearTimeout(initTimeout);
          console.error('Pose inference failed:', data.message);
          this.status('姿勢推定を開始できませんでした。再試行するか、別のブラウザをお試しください。');
          this.stop();
        }
      };
      this.worker.onerror = () => {
        clearTimeout(initTimeout); this.status('姿勢モデルを読み込めませんでした。接続を確認して再試行してください。'); this.stop();
      };
      this.worker.postMessage({ type: 'init' });
      document.addEventListener('visibilitychange', this.onVisibility);
      window.addEventListener('resize', this.onResize);
    } catch (error) {
      if (generation !== this.generation) return;
      const name = error instanceof DOMException ? error.name : '';
      this.status(name === 'NotAllowedError' ? 'カメラの許可が必要です。ブラウザの設定で許可し、再試行してください。'
        : name === 'NotFoundError' ? 'カメラが見つかりません。カメラのあるスマートフォンで開いてください。'
        : name === 'NotReadableError' ? 'カメラが使用中です。他のアプリを閉じて再試行してください。' : String(error).replace(/^Error: /, ''));
      this.stop();
    }
  }

  private loop = async () => {
    if (!this.running) return;
    const generation = this.generation;
    if (!this.busy && !document.hidden && this.video.readyState >= 2 && this.lastFrame !== this.video.currentTime) {
      this.busy = true; this.lastFrame = this.video.currentTime;
      try {
        const bitmap = await createImageBitmap(this.video);
        if (!this.running || generation !== this.generation) { bitmap.close(); return; }
        this.worker!.postMessage({ type: 'frame', bitmap, timestamp: performance.now() }, [bitmap]);
      } catch { this.busy = false; }
    }
    if (this.running && generation === this.generation) this.timer = window.setTimeout(this.loop, 125);
  };

  stop() {
    this.generation++; this.running = false; this.busy = false; this.lastFrame = -1;
    clearTimeout(this.timer); clearTimeout(this.initTimer); clearTimeout(this.resizeTimer); this.worker?.terminate(); this.worker = null;
    this.stream?.getTracks().forEach(t => t.stop()); this.stream = null; this.video.srcObject = null;
    document.removeEventListener('visibilitychange', this.onVisibility);
    window.removeEventListener('resize', this.onResize);
    this.onReady(false);
  }
}
