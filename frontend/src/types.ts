export type Point = [number, number, number];
export interface Settings {
  clear_mode: 'latched' | 'simultaneous'; score_threshold: number; confidence_threshold: number;
  hold_seconds: number; hidden_policy: 'require' | 'ignore'; min_visible: number; joints: number[];
  azimuth_min: number; azimuth_max: number; elevation_min: number; elevation_max: number;
  min_limb_ratio: number; min_side_separation: number; min_keypoint_separation: number; round_seconds: number; rounds: number;
}
export interface Player { id: string; name: string; connected: boolean; ready: boolean; cleared: boolean; matched: boolean; score: number }
export interface PoseView {
  azimuth: number; elevation: number; distance: number; target_height: number; focal_scale: number;
}
export interface Round {
  id: string; number: number; poser_id: string; started_at: number | null; ended_at: number | null;
  outcome: string | null; cleared: Record<string, number>; settings: Settings;
  target?: Point[]; pose?: { id: string; name: string; points: Point[] };
  target_view?: PoseView;
}
export interface Result {
  id: string; number: number; poser_id: string; participants: Record<string, string>;
  elapsed: number | null; outcome: string; cleared: Record<string, number>; started_at: number | null;
}
export interface State {
  type: 'state'; join_url: string | null; setup_url?: string | null; event_id: string; name: string; phase: 'waiting' | 'round_setup' | 'playing' | 'round_result' | 'final_result';
  registration_open: boolean; me: string | null; admin: boolean; players: Player[];
  round: Round | null; history: Result[]; server_time: number; settings: Settings | null;
}
export interface Feedback { type: 'feedback'; score: number; matched: boolean; visible: number; reason: string; hold: number; cleared: boolean }
export const joints = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];
export const jointNames = ['左肩', '右肩', '左肘', '右肘', '左手首', '右手首', '左腰', '右腰', '左膝', '右膝', '左足首', '右足首'];
export const edges = [[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24], [23, 25], [25, 27], [24, 26], [26, 28]];
