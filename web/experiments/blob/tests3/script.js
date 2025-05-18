import * as THREE from 'three';

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.1, 1000);
camera.position.z = 100;

const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById('bg'), antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// Circle packing logic
const circles = [];
const maxTries = 5000;
const planeSize = 80;
const minRadius = 1;
const maxRadius = 5;

function doesOverlap(x, y, r) {
  for (let c of circles) {
    const dx = x - c.x;
    const dy = y - c.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < r + c.r + 0.2) return true;
  }
  return false;
}

for (let i = 0; i < maxTries; i++) {
  const r = Math.random() * (maxRadius - minRadius) + minRadius;
  const x = Math.random() * planeSize - planeSize / 2;
  const y = Math.random() * planeSize - planeSize / 2;

  if (!doesOverlap(x, y, r)) {
    circles.push({ x, y, r });

    const geometry = new THREE.SphereGeometry(r, 32, 32);
    const material = new THREE.MeshStandardMaterial({ color: 0xffffff });
    const sphere = new THREE.Mesh(geometry, material);
    sphere.position.set(x, y, 0); // lock to z=0
    scene.add(sphere);
  }
}

// Lighting
const light = new THREE.PointLight(0xffffff, 1);
light.position.set(50, 50, 100);
scene.add(light);
scene.add(new THREE.AmbientLight(0x404040));

// Animation loop
function animate() {
  requestAnimationFrame(animate);
  renderer.render(scene, camera);
}
animate();