import { FilesetResolver, PoseLandmarker } from '@mediapipe/tasks-vision';

let model: PoseLandmarker | null = null;
self.onmessage = async (event: MessageEvent) => {
  const data = event.data;
  if (data.type === 'init') {
    try {
      const files = await FilesetResolver.forVisionTasks(`${self.location.origin}/wasm`);
      let delegate: 'GPU' | 'CPU' = 'GPU';
      const create = (delegate: 'GPU' | 'CPU') => PoseLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: `${self.location.origin}/models/pose_landmarker_lite.task`, delegate },
        runningMode: 'VIDEO', numPoses: 4, minPoseDetectionConfidence: .4,
        minPosePresenceConfidence: .4, minTrackingConfidence: .4,
      });
      try { model = await create('GPU'); }
      catch { delegate = 'CPU'; model = await create('CPU'); }
      self.postMessage({ type: 'ready', delegate });
    } catch (error) { self.postMessage({ type: 'error', message: String(error) }); }
  } else if (data.type === 'frame' && model) {
    try {
      const result = model.detectForVideo(data.bitmap, data.timestamp);
      self.postMessage({ type: 'result', poses: result.landmarks, timestamp: data.timestamp });
    } catch (error) { self.postMessage({ type: 'error', message: String(error) }); }
    finally { data.bitmap.close(); }
  }
};
