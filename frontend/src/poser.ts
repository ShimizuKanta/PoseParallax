import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { edges, joints, type Point, type PoseView } from './types';
import { boneGroup, skeletonColors, faceInk } from './skeleton-style';
import { setTargetCamera } from './pose-view';

export function showPoser(container: HTMLElement, points: Point[], showFace = true,
  options: { targetView?: PoseView; resetButton?: HTMLButtonElement } = {}): () => void {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  container.append(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, .1, 100);
  camera.position.set(.4, 1.4, 3.8);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, .95, 0); controls.enablePan = false; controls.minDistance = 2; controls.maxDistance = 7;
  controls.update();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x526273, 3));
  const materials = {
    left: new THREE.MeshStandardMaterial({ color: skeletonColors.left, roughness: .45 }),
    right: new THREE.MeshStandardMaterial({ color: skeletonColors.right, roughness: .45 }),
    center: new THREE.MeshStandardMaterial({ color: skeletonColors.center, roughness: .45 }),
  };
  const ball = new THREE.SphereGeometry(.043, 16, 12);
  for (const i of joints) {
    const mesh = new THREE.Mesh(ball, materials[i % 2 === 1 ? 'left' : 'right']);
    mesh.position.set(...points[i]); scene.add(mesh);
  }
  const head = new THREE.Vector3(...points[0]);
  const headRadius = .145;
  const headMesh = new THREE.Mesh(new THREE.SphereGeometry(headRadius, 32, 24), materials.center);
  headMesh.position.copy(head); scene.add(headMesh);
  const ink = new THREE.MeshBasicMaterial({ color: faceInk });
  if (showFace) {
    // Project each facial feature onto the front surface of the sphere.
    const surface = (x: number, y: number) => head.clone().add(new THREE.Vector3(
      x, y, Math.sqrt(headRadius ** 2 - x ** 2 - y ** 2) + .003,
    ));
    const eyeGeometry = new THREE.SphereGeometry(.015, 16, 12);
    for (const side of [-1, 1]) {
      const eye = new THREE.Mesh(eyeGeometry, ink);
      eye.position.copy(surface(side * .052, .035)); scene.add(eye);
    }
    const mouthPoints = Array.from({ length: 33 }, (_, i) => {
      const t = i / 32;
      return surface(-.062 + .124 * t, -.028 - .12 * t * (1 - t));
    });
    const mouthCurve = new THREE.CatmullRomCurve3(mouthPoints);
    scene.add(new THREE.Mesh(new THREE.TubeGeometry(mouthCurve, 48, .007, 8, false), ink));
  }
  const chin = head.clone().add(new THREE.Vector3(0, -headRadius, 0));
  for (const [a, b] of [...edges, [0, 11], [0, 12]]) {
    const from = a === 0 ? chin.clone() : new THREE.Vector3(...points[a]), to = new THREE.Vector3(...points[b]);
    const direction = to.clone().sub(from);
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(.023, .023, direction.length(), 12), materials[boneGroup(a, b)]);
    mesh.position.copy(from).add(to).multiplyScalar(.5);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize()); scene.add(mesh);
  }
  const grid = new THREE.GridHelper(3, 12, 0x465366, 0x273547); scene.add(grid);
  let targetViewActive = false;
  const resetView = () => {
    if (!options.targetView) return;
    controls.target.set(0, options.targetView.target_height, 0);
    setTargetCamera(camera, points, options.targetView);
    controls.update();
    targetViewActive = true;
  };
  const leaveTargetView = () => { targetViewActive = false; };
  controls.addEventListener('start', leaveTargetView);
  if (options.targetView && options.resetButton) {
    options.resetButton.disabled = false;
    options.resetButton.addEventListener('click', resetView);
  }
  let frame = 0;
  const resize = new ResizeObserver(() => {
    const w = container.clientWidth, h = container.clientHeight;
    renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
    if (targetViewActive) resetView();
  });
  resize.observe(container);
  function render() { renderer.render(scene, camera); frame = requestAnimationFrame(render); }
  render();
  return () => {
    cancelAnimationFrame(frame); resize.disconnect(); controls.dispose();
    options.resetButton?.removeEventListener('click', resetView);
    controls.removeEventListener('start', leaveTargetView);
    scene.traverse(object => { if (object instanceof THREE.Mesh) object.geometry.dispose(); });
    grid.geometry.dispose(); (grid.material as THREE.Material).dispose();
    ink.dispose(); Object.values(materials).forEach(m => m.dispose()); renderer.dispose(); renderer.domElement.remove();
  };
}
