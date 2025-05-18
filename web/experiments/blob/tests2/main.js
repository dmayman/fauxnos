import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GUI } from 'dat.gui';
import { BlobGenerator } from './blob.js';

// Scene setup
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x111122);

// Camera setup
const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
camera.position.z = 20;

// Renderer setup
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
document.getElementById('app').appendChild(renderer.domElement);

// Controls
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;

// Lights
const ambientLight = new THREE.AmbientLight(0x404040);
scene.add(ambientLight);

const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
directionalLight.position.set(1, 1, 1);
directionalLight.castShadow = true;
scene.add(directionalLight);

// GUI
const gui = new GUI();
const params = {
  numBlobs: 8,
  minSize: 1.3,
  maxSize: 1.5,
  damping: 0.5,
  hitAreaScale: 1.0,
  regenerate: () => blobGenerator.generateBlobs(),
  attractorX: 0,
  attractorY: 0
};

const blobFolder = gui.addFolder('Blob Settings');
blobFolder.add(params, 'numBlobs', 1, 100, 1).name('Count').onChange(updateBlobParams);
blobFolder.add(params, 'minSize', 0.1, 5.0, 0.1).name('Min Size').onChange(updateBlobParams);
blobFolder.add(params, 'maxSize', 0.1, 5.0, 0.1).name('Max Size').onChange(updateBlobParams);
blobFolder.add(params, 'damping', 0, 0.5, 0.01).name('Damping').onChange(updateBlobParams);
blobFolder.add(params, 'hitAreaScale', 0.5, 2.0, 0.1).name('Hit Area Scale').onChange(updateBlobParams);
blobFolder.add(params, 'regenerate').name('Regenerate Blobs');


// Create the dropzone sphere
const dropzone = {
  position: new THREE.Vector3(0, 0, 0),
  size: 5.0,  // Fixed size for the dropzone
  mesh: new THREE.Mesh(
    new THREE.SphereGeometry(5, 32, 32),
    new THREE.MeshStandardMaterial({
      color: 0x666666,
      transparent: true,
      opacity: 0.5,
      wireframe: true
    })
  )
};
scene.add(dropzone.mesh);

// Create blob generator
const blobGenerator = new BlobGenerator(scene, {
  numBlobs: params.numBlobs,
  minSize: params.minSize,
  maxSize: params.maxSize,
  dropzone: dropzone  // Pass dropzone to generator
});

// Generate initial blobs
blobGenerator.generateBlobs();

// Update blob parameters
function updateBlobParams() {
  // Only regenerate blobs if the count has changed
  const countChanged = blobGenerator.params.numBlobs !== params.numBlobs;
  
  // Update the parameters
  blobGenerator.params.numBlobs = params.numBlobs;
  blobGenerator.params.minSize = params.minSize;
  blobGenerator.params.maxSize = params.maxSize;
  blobGenerator.params.damping = params.damping;
  blobGenerator.params.hitAreaScale = params.hitAreaScale;
  
  // Only regenerate if necessary (count changed or explicitly requested)
  if (countChanged) {
    blobGenerator.generateBlobs();
  }
}

// Update attractor position
function updateAttractor() {
  blobGenerator.attractor.set(params.attractorX, params.attractorY, 0);
}

// Animation loop
let lastTime = 0;
function animate(currentTime = 0) {
  requestAnimationFrame(animate);
  
  // Update blob physics with current time
  blobGenerator.update(currentTime);
  
  // Update controls
  controls.update();
  
  // Render scene
  renderer.render(scene, camera);
  
  lastTime = currentTime;
}

// Handle window resize
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// Start animation
updateBlobParams();
requestAnimationFrame(animate);