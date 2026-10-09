import { t } from './i18n';
// A distinct green / cyan / blue palette for the 3D pose, targets and camera overlay.
export const skeletonColors = {
  left: '#75df91',
  right: '#609ce8',
  center: '#80e4df',
} as const;

export const faceInk = '#173c49';

export function boneGroup(a: number, b: number): keyof typeof skeletonColors {
  if (a < 11 || b < 11 || a % 2 !== b % 2) return 'center';
  return a % 2 === 1 ? 'left' : 'right';
}

export const skeletonLegend = () => `<span class="skeleton-legend" aria-label="${t('本人の左半身・中央・右半身の色')}">${([
  ['left', '左'], ['center', '中央'], ['right', '右'],
] as const).map(([group, label]) => `<span><i style="background:${skeletonColors[group]}"></i>${t(label)}</span>`).join('')}</span>`;
