import * as THREE from 'three';
import { joints, type Point, type PoseView } from './types';

export function setTargetCamera(camera: THREE.PerspectiveCamera, points: Point[], view: PoseView) {
  const a = THREE.MathUtils.degToRad(view.azimuth), e = THREE.MathUtils.degToRad(view.elevation);
  const target = new THREE.Vector3(0, view.target_height, 0);
  camera.position.copy(target).add(new THREE.Vector3(
    Math.sin(a) * Math.cos(e), Math.sin(e), Math.cos(a) * Math.cos(e),
  ).multiplyScalar(view.distance));
  camera.zoom = 1;
  camera.lookAt(target);
  camera.updateMatrixWorld();
  // Widen the lens on narrow screens without moving the camera: distance
  // determines perspective, while a uniform zoom preserves the target shape.
  let tangent = .5 / view.focal_scale;
  for (const i of [...joints, 0]) {
    const center = new THREE.Vector3(...points[i]).applyMatrix4(camera.matrixWorldInverse);
    const radius = i === 0 ? .145 : .045;
    const depth = -center.z - radius;
    tangent = Math.max(tangent, (Math.abs(center.x) + radius) / (depth * camera.aspect * .8),
      (Math.abs(center.y) + radius) / (depth * .8));
  }
  camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan(tangent));
  camera.updateProjectionMatrix();
}
