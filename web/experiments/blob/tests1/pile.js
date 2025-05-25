import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import * as CANNON from 'cannon-es';
import GUI from 'lil-gui';

// Define params first to ensure it's available for BlobVisual instances
const params = {
  numBlobs: 6,
  minRadius: 1.5,
  maxRadius: 1.75,
  radiusRandomness: 0.5,
  padding: 0.4,
  gravityStrength: 200, // Reduced for slower movement
  dropZoneRadius: 2,
  centerBlobScale: 2.2,
  previewBounds: false,
  dragHoverScale: 1.3,
  centerNodeSize: .4,
  otherBlobsScale: 0.7,
  useCenterBlobScaling: true,
  blobActiveScale: 1.2, // Scale when blob is being actively dragged
  transitionSpeed: 1, // Controls how quickly blobs animate between states
  planeLRspacing: 6, // Left/right plane spacing
  planeTBspacing: 10  // Top/bottom plane spacing
};

// Export params for debugging
window.params = params;

// Collision groups (must be powers of 2)
const COLLISION_GROUPS = {
  BLOBS: 1,     // 0001 - Regular blobs
  CENTER: 2,    // 0010 - Center blob
  DRAGGED: 4,   // 0100 - Currently dragged blob
  BOUNDARY: 8   // 1000 - Boundary planes
};

// Boundary plane bodies
let boundaryBodies = [];

let fadeCenterNodeOut = false;
let fadeCenterNodeIn = false;

let scene, camera, renderer, controls;
let world;
let blobs = [];
let blobMeshes = [];
let plane1, plane2, plane3, plane4; // Plane meshes for boundary visualization
let fixedBlobs = [];
let dragControls = [];
let raycaster, mouse;
let dragObject = null;
let plane;
let gravityWell;
let dropZone;
// Drop zone visualization only
// Boundary planes handle all containment now
let gui;
let centerNode;
let dropZoneScale = params.centerBlobScale;
// Store visual properties for each blob
const blobVisuals = [];
let isDragging = false;
let centerBlobIndices = []; // Array to store indices of centered blobs

// Helper function to log centered blobs
function logCenteredBlobs() {
  if (centerBlobIndices.length > 0) {
    console.log(`Blobs in center: ${centerBlobIndices.join(', ')}`);
  } else {
    console.log('No blobs in center');
  }
}

// Blob visual state class
class BlobVisual {
  constructor(radius, params) {
    this.radius = radius;
    this.targetScale = 1;  // Target scale (1 = normal scale)
    this.currentScale = 1; // Current rendered scale
    this.params = params;  // Reference to params for dynamic values
    this.animationSpeed = 4.0; // Base animation speed (multiplied by transitionSpeed)
  }
  
  // Update the current scale based on target scale and time
  update(deltaTime = 1) {
    // Skip if we're already at the target
    if (Math.abs(this.currentScale - this.targetScale) < 0.001) {
      this.currentScale = this.targetScale;
      return this.currentScale;
    }
    
    // Calculate the animation step based on time and speed
    const delta = this.targetScale - this.currentScale;
    const step = delta * this.params.transitionSpeed * this.animationSpeed * deltaTime;
    
    // Apply the step with a minimum step size to ensure completion
    if (Math.abs(step) < 0.001) {
      this.currentScale = this.targetScale;
    } else {
      this.currentScale += step;
    }
    
    return this.currentScale;
  }
  
  // Set a new target scale
  setTargetScale(scale, caller = '') {
    if (this.targetScale !== scale) {
      // Scale target changed
      this.targetScale = scale;
    }
    return this;
  }
  
  // Get the current visual scale
  getVisualScale() {
    return this.currentScale * this.radius;
  }
}

// Helper function to get or create blob visual state
function getBlobVisual(index, radius) {
  if (!blobVisuals[index]) {
    blobVisuals[index] = new BlobVisual(radius, params);
  }
  return blobVisuals[index];
}

init();
animate();

function resetCamera() {
  camera.position.set(0, 0, 20);
  camera.up.set(0, 1, 0);
  camera.lookAt(0, 0, 0);
  if (controls) {
    controls.target.set(0, 0, 0);
    controls.update();
  }
}

function init() {
  // Scene setup
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x202020);

  camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
  resetCamera();

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  document.body.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  // Physics world with optimized performance settings
  world = new CANNON.World();
  world.gravity.set(0, 0, 0); // We'll implement central gravity manually
  world.broadphase = new CANNON.SAPBroadphase(world); // More efficient broadphase
  world.solver.iterations = 15; // Balanced between accuracy and performance
  
  // Create and configure the blob material with springy properties
  const blobMaterial = new CANNON.Material('blobMaterial');
  world.addContactMaterial(
    new CANNON.ContactMaterial(
      blobMaterial,
      blobMaterial,
      {
        restitution: 0.6,          // Bouncy but not too much
        friction: 0.1,             // Low friction for smooth movement
        contactEquationStiffness: 1e5,  // Softer contacts between blobs
        contactEquationRelaxation: 8,   // Slightly reduced for performance
        frictionEquationStiffness: 1e5  // Softer friction response
      }
    )
  );
  world.defaultMaterial = blobMaterial;  // Set as default material for all bodies
  
  // Add some damping to the world to prevent excessive bouncing
  world.quatNormalizeSkip = 0;
  world.quatNormalizeFast = false;
  world.solver.tolerance = 0.001; // More precise solving

  // Plane for dragging calculations
  plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);

  // Raycaster and mouse for interaction
  raycaster = new THREE.Raycaster();
  mouse = new THREE.Vector2();

  // GUI
  gui = new GUI();
  gui.add(params, 'numBlobs', 1, 10, 1).name('Number of Blobs').onChange(resetBlobs);
  gui.add(params, 'minRadius', 0.1, 3, 0.1).name('Min Radius').onChange(resetBlobs);
  gui.add(params, 'maxRadius', 0.1, 3, 0.1).name('Max Radius').onChange(resetBlobs);
  gui.add(params, 'radiusRandomness', 0, 1, 0.01).name('Radius Randomness').onChange(resetBlobs);
  gui.add(params, 'padding', 0, 1, 0.01).name('Padding').onChange(updateBlobPadding);
  gui.add(params, 'gravityStrength', 0, 1000, 1).name('Gravity Strength');
  gui.add(params, 'dropZoneRadius', 0.1, 10, 0.1).name('Drop Zone Radius').onChange(updateBounds);
  gui.add(params, 'centerBlobScale', 0.1, 10, 0.1).name('Center Blob Size');
  // Add boundary controls
  const boundaryFolder = gui.addFolder('Boundary Planes');
  boundaryFolder.add(params, 'planeLRspacing', 5, 50, 0.5).name('Left/Right Spacing').onChange(updatePlanePositions);
  boundaryFolder.add(params, 'planeTBspacing', 5, 50, 0.5).name('Top/Bottom Spacing').onChange(updatePlanePositions);
  boundaryFolder.add(params, 'previewBounds').name('Preview Bounds').onChange(updateBoundsVisibility);
  gui.add(params, 'dragHoverScale', 1, 2, 0.01).name('Hover Scale');
  gui.add(params, 'centerNodeSize', 0.1, 10, 0.1).name('Center Node Size');
  gui.add(params, 'otherBlobsScale', 0.1, 2, 0.05).name('Other Blobs Scale');
  gui.add(params, 'useCenterBlobScaling').name('Enable Center Blob Scaling');
  gui.add(params, 'transitionSpeed', 0.01, 1, 0.01).name('Transition Speed');
  gui.add({ resetCamera }, 'resetCamera').name('Reset Camera');

  // Gravity well center (0,0,0)
  gravityWell = new CANNON.Vec3(0, 0, 0);

  // Drop zone - invisible transparent sphere with fixed radius
  const dropZoneGeometry = new THREE.SphereGeometry(params.dropZoneRadius, 32, 32);
  const dropZoneMaterial = new THREE.MeshBasicMaterial({
    color: 0x00ff00,
    transparent: true,
    opacity: 0.1,
    visible: true,
    wireframe: true
  });
  dropZone = new THREE.Mesh(dropZoneGeometry, dropZoneMaterial);
  scene.add(dropZone);

  // 2 planes in the YZ direction spaced by a parameter
  const planeLRspacing = params.planeLRspacing;
  const planeTBspacing = params.planeTBspacing;
  const planeSize = 20;
  const planeThickness = 0.1; // Thickness for collision
  const planeGeometry = new THREE.PlaneGeometry(planeSize, planeSize);
  const planeMaterial = new THREE.MeshBasicMaterial({
    color: 0xffffff,
    transparent: true,
    opacity: 0.3,
    visible: true,
    wireframe: true
  });
  // Left plane
  plane1 = new THREE.Mesh(planeGeometry, planeMaterial);
  plane1.rotation.y = Math.PI / 2;
  plane1.position.set(-planeLRspacing, 0, 0);
  scene.add(plane1);
  
  // Right plane
  plane2 = new THREE.Mesh(planeGeometry, planeMaterial);
  plane2.rotation.y = Math.PI / 2;
  plane2.position.set(planeLRspacing, 0, 0);
  scene.add(plane2);

  // Bottom plane
  plane3 = new THREE.Mesh(planeGeometry, planeMaterial);
  plane3.rotation.x = Math.PI / 2;
  plane3.position.set(0, -planeTBspacing, 0);
  scene.add(plane3);
  
  // Top plane
  plane4 = new THREE.Mesh(planeGeometry, planeMaterial);
  plane4.rotation.x = Math.PI / 2;
  plane4.position.set(0, planeTBspacing, 0);
  scene.add(plane4);

  // Create physics bodies for boundaries
  createBoundaryBodies();
  
  // Configure physics world for better collision detection
  world.defaultContactMaterial.friction = 0.0;
  world.defaultContactMaterial.restitution = 0.6; // Add some bounciness
  
  // Set up collision detection between blobs and boundaries
  const blobBoundaryMaterial = new CANNON.ContactMaterial(
    world.defaultMaterial, // Blob material
    world.defaultMaterial, // Boundary material
    {
      friction: 0.0,
      restitution: 0.6
    }
  );
  world.addContactMaterial(blobBoundaryMaterial);

  // Boundary planes handle all containment now

  // Create blobs
  createBlobs();

  // Add centerNode sprite at the center
  const centerTexture = new THREE.TextureLoader().load('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="30" fill="white" /></svg>');
  const centerMaterial = new THREE.SpriteMaterial({ map: centerTexture, transparent: true, opacity: 0.5 });
  centerNode = new THREE.Sprite(centerMaterial);
  centerNode.scale.set(params.centerNodeSize, params.centerNodeSize, 1);
  // Set renderOrder and disable depthTest for centerNode
  centerNode.renderOrder = 999;
  centerNode.material.depthTest = false;
  scene.add(centerNode);

  // Event listeners
  window.addEventListener('resize', onWindowResize);
  renderer.domElement.addEventListener('pointerdown', onPointerDown);
  renderer.domElement.addEventListener('pointermove', onPointerMove);
  renderer.domElement.addEventListener('pointerup', onPointerUp);

  updateBoundsVisibility();
}

function createBoundaryBodies() {
  // Remove any existing boundary bodies
  if (boundaryBodies && boundaryBodies.length > 0) {
    boundaryBodies.forEach(body => world.removeBody(body));
    boundaryBodies = [];
  }
  
  const planeSize = 100;
  const planeThickness = 0.1;
  
  // Left and right walls (thicker for better collision detection)
  const wallThickness = 0.5; // Increased thickness for better collision detection
  const wallSize = planeSize * 2; // Make walls larger than visual
  
  const leftWall = new CANNON.Body({
    mass: 0, // Static body
    shape: new CANNON.Box(new CANNON.Vec3(wallThickness, wallSize, wallSize)),
    position: new CANNON.Vec3(-params.planeLRspacing, 0, 0),
    collisionFilterGroup: COLLISION_GROUPS.BOUNDARY,
    collisionFilterMask: COLLISION_GROUPS.BLOBS | COLLISION_GROUPS.DRAGGED | COLLISION_GROUPS.CENTER,
    collisionResponse: true
  });
  
  const rightWall = new CANNON.Body({
    mass: 0, // Static body
    shape: new CANNON.Box(new CANNON.Vec3(wallThickness, wallSize, wallSize)),
    position: new CANNON.Vec3(params.planeLRspacing, 0, 0),
    collisionFilterGroup: COLLISION_GROUPS.BOUNDARY,
    collisionFilterMask: COLLISION_GROUPS.BLOBS | COLLISION_GROUPS.DRAGGED | COLLISION_GROUPS.CENTER,
    collisionResponse: true
  });
  
  // Top and bottom walls
  const bottomWall = new CANNON.Body({
    mass: 0, // Static body
    shape: new CANNON.Box(new CANNON.Vec3(wallSize, wallThickness, wallSize)),
    position: new CANNON.Vec3(0, -params.planeTBspacing, 0),
    collisionFilterGroup: COLLISION_GROUPS.BOUNDARY,
    collisionFilterMask: COLLISION_GROUPS.BLOBS | COLLISION_GROUPS.DRAGGED | COLLISION_GROUPS.CENTER,
    collisionResponse: true
  });
  
  const topWall = new CANNON.Body({
    mass: 0, // Static body
    shape: new CANNON.Box(new CANNON.Vec3(wallSize, wallThickness, wallSize)),
    position: new CANNON.Vec3(0, params.planeTBspacing, 0),
    collisionFilterGroup: COLLISION_GROUPS.BOUNDARY,
    collisionFilterMask: COLLISION_GROUPS.BLOBS | COLLISION_GROUPS.DRAGGED | COLLISION_GROUPS.CENTER,
    collisionResponse: true
  });
  
  // Add all walls to the world and our array
  world.addBody(leftWall);
  world.addBody(rightWall);
  world.addBody(bottomWall);
  world.addBody(topWall);
  
  boundaryBodies.push(leftWall, rightWall, bottomWall, topWall);
}

function updatePlanePositions() {
  // Update visual positions
  plane1.position.x = -params.planeLRspacing;
  plane2.position.x = params.planeLRspacing;
  plane3.position.y = -params.planeTBspacing;
  plane4.position.y = params.planeTBspacing;
  
  // Update physics bodies
  createBoundaryBodies();
}

function updateBoundsVisibility() {
  dropZone.visible = params.previewBounds;
  plane1.visible = params.previewBounds;
  plane2.visible = params.previewBounds;
  plane3.visible = params.previewBounds;
  plane4.visible = params.previewBounds;
}

function updateBounds() {
  dropZone.geometry.dispose();
  dropZone.geometry = new THREE.SphereGeometry(params.dropZoneRadius, 32, 32);
  
  // Update boundary planes when spacing changes
  createBoundaryBodies();
}

function updateCenterBlobScale() {
  // Center blob scale is now handled directly in the animate function
  // when a blob is in the center position
}

function createBlobs() {
  clearBlobs();

  // Calculate angle step between blobs
  const angleStep = (Math.PI * 2) / params.numBlobs;
  const radiusFromCenter = params.dropZoneRadius * 2.5; // 2.5x drop zone radius
  
  for (let i = 0; i < params.numBlobs; i++) {
    // Randomize blob size within limits
    let radius = THREE.MathUtils.lerp(params.minRadius, params.maxRadius, Math.random());
    radius += (Math.random() - 0.5) * params.radiusRandomness;
    radius = Math.max(params.minRadius, Math.min(params.maxRadius, radius));
    
    // Calculate position in a circle
    const angle = i * angleStep;
    let x = Math.cos(angle) * radiusFromCenter;
    let y = Math.sin(angle) * radiusFromCenter;
    const z = 0; // Keep blobs in the same Z plane for 2D-like behavior
    
    // Ensure position is within boundaries with padding
    const buffer = radius + params.padding;
    x = THREE.MathUtils.clamp(x, -params.planeLRspacing + buffer, params.planeLRspacing - buffer);
    y = THREE.MathUtils.clamp(y, -params.planeTBspacing + buffer, params.planeTBspacing - buffer);

    const totalRadius = radius + params.padding;

    // Initialize visual state for this blob
    const blobVisual = new BlobVisual(radius, params);
    blobVisuals.push(blobVisual);
    
    // Three.js mesh
    const geometry = new THREE.SphereGeometry(radius, 32, 32);
    const material = new THREE.MeshStandardMaterial({ 
      color: new THREE.Color(Math.random(), Math.random(), Math.random()) 
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(x, y, z);
    scene.add(mesh);
    blobMeshes.push(mesh);
    
    // Set initial scale
    mesh.scale.setScalar(blobVisual.currentScale);

    // Physics body
    const shape = new CANNON.Sphere(totalRadius);
    const body = new CANNON.Body({ 
      mass: 1, 
      shape: shape, 
      position: new CANNON.Vec3(x, y, z),
      collisionFilterGroup: COLLISION_GROUPS.BLOBS,
      collisionFilterMask: COLLISION_GROUPS.BLOBS | COLLISION_GROUPS.CENTER | COLLISION_GROUPS.BOUNDARY | COLLISION_GROUPS.DRAGGED,
      collisionResponse: true,
      material: world.defaultMaterial
    });
    
    // Physics properties
    body.linearDamping = 0.3; // Reduced damping for more responsive movement
    body.angularDamping = 0.3;
    body.linearSleepingThreshold = 0.5;
    body.angularSleepingThreshold = 0.5;
    world.addBody(body);
    blobs.push(body);
  }

  // Add light
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
  scene.add(ambientLight);
  const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
  directionalLight.position.set(10, 20, 10);
  scene.add(directionalLight);
}

function updateBlobPadding() {
  for (let i = 0; i < blobs.length; i++) {
    const newRadius = blobVisuals[i].radius + params.padding;
    blobs[i].shapes[0].radius = newRadius;
    blobs[i].updateBoundingRadius();
    blobs[i].updateMassProperties();
  }
}

function clearBlobs() {
  // Remove meshes
  for (let mesh of blobMeshes) {
    scene.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
  }
  blobMeshes = [];

  // Remove physics bodies
  for (let body of blobs) {
    world.removeBody(body);
  }
  blobs = [];

  // Clear fixed blobs
  for (let body of fixedBlobs) {
    world.removeBody(body);
  }
  fixedBlobs = [];
}

function resetBlobs() {
  clearBlobs();
  createBlobs();
}

// Dragging helpers

function getIntersects(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  return raycaster.intersectObjects(blobMeshes);
}

function onPointerDown(event) {
  const intersects = getIntersects(event);
  if (intersects.length > 0) {
    dragObject = intersects[0].object;
    controls.enabled = false;
    isDragging = true;
    const index = blobMeshes.indexOf(dragObject);
    if (index !== -1) {
      console.log(`Started dragging blob`);
      
      // Set target scale for active drag
      blobVisuals[index].setTargetScale(params.blobActiveScale);
      
      // Set collision group to DRAGGED for the dragged blob
      blobs[index].collisionFilterGroup = COLLISION_GROUPS.DRAGGED;
      // Collide with BLOBS, BOUNDARY, and other DRAGGED blobs
      blobs[index].collisionFilterMask = COLLISION_GROUPS.BLOBS | COLLISION_GROUPS.BOUNDARY;
    }
  }
}

function onPointerMove(event) {
  if (!dragObject) return;

  const rect = renderer.domElement.getBoundingClientRect();
  mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  
  // Check if we're dragging a blob that was in the center
  const index = blobMeshes.indexOf(dragObject);
  if (index !== -1) {
    const centerIndex = centerBlobIndices.indexOf(index);
    if (centerIndex !== -1) {
      // Get the position difference from the last frame
      const currentPos = new THREE.Vector3().copy(blobs[index].position);
      const delta = new THREE.Vector3().subVectors(currentPos, blobs[index].previousPosition || currentPos);
      
      // Update all centered blobs' positions
      centerBlobIndices.forEach(blobIndex => {
        if (blobIndex !== index) { // Skip the blob we're directly controlling
          const body = blobs[blobIndex];
          const newPos = new CANNON.Vec3(
            body.position.x + delta.x,
            body.position.y + delta.y,
            body.position.z + delta.z
          );
          body.position.copy(newPos);
          body.velocity.set(0, 0, 0);
          body.angularVelocity.set(0, 0, 0);
          
          // Update the corresponding mesh position
          if (blobMeshes[blobIndex]) {
            blobMeshes[blobIndex].position.copy(new THREE.Vector3(newPos.x, newPos.y, newPos.z));
          }
        }
      });
      
      // Store current position for next frame
      blobs[index].previousPosition = currentPos.clone();
      
      // If we've moved away from the center, update physics for all centered blobs
      const distToCenter = blobs[index].position.length();
      if (distToCenter > params.dropZoneRadius * 0.8) { 
        centerBlobIndices.forEach(blobIndex => {
          const body = blobs[blobIndex];
          body.mass = 1; // Restore mass
          body.updateMassProperties();
          
          // Update collision group and mask back to BLOBS
          body.collisionFilterGroup = COLLISION_GROUPS.BLOBS;
          body.collisionFilterMask = COLLISION_GROUPS.BLOBS | COLLISION_GROUPS.CENTER | COLLISION_GROUPS.BOUNDARY | COLLISION_GROUPS.DRAGGED;
          
          // Make sure the mesh is visible
          if (blobMeshes[blobIndex]) {
            blobMeshes[blobIndex].visible = true;
          }
        });
        
        // Clear all centered blobs
        centerBlobIndices = [];
      }
    }
  }
  const intersects = raycaster.ray.intersectPlane(plane, new THREE.Vector3());

  if (intersects) {
    const index = blobMeshes.indexOf(dragObject);
    if (index !== -1) {
      blobs[index].position.set(intersects.x, intersects.y, intersects.z);
      blobs[index].velocity.set(0, 0, 0);
      blobs[index].angularVelocity.set(0, 0, 0);
      blobs[index].force.set(0, 0, 0);
      blobs[index].torque.set(0, 0, 0);
    }
  }
}

function onPointerUp(event) {
  controls.enabled = true;
  isDragging = false;

  if (dragObject) {
    const index = blobMeshes.indexOf(dragObject);
    if (index !== -1) {
      const distToCenter = blobs[index].position.length();
      if (distToCenter < params.dropZoneRadius) { // if we're in the drop zone
        // Add to center if not already centered
        if (!centerBlobIndices.includes(index)) {
          centerBlobIndices.push(index);
          // Defer to animate loop to ease into center
          blobs[index].velocity.set(0, 0, 0);
          blobs[index].angularVelocity.set(0, 0, 0);
          blobs[index].mass = 0;
          blobs[index].updateMassProperties();
          
          // Update collision group to CENTER
          blobs[index].collisionFilterGroup = COLLISION_GROUPS.CENTER;
          blobs[index].collisionFilterMask = COLLISION_GROUPS.BLOBS | COLLISION_GROUPS.BOUNDARY;
          
          // Only hide the blob if it's not the first one in the center
          if (centerBlobIndices.length > 1) {
            blobMeshes[index].visible = false;
          }
          // animate scale in animate loop
          fadeCenterNodeOut = true;
          fadeCenterNodeIn = false;
          logCenteredBlobs();
        }
      } else { // if we're not in the drop zone
        // Reset target scale when dropped (actual scale will animate to this)
        blobVisuals[index].setTargetScale(1.0);
        
        // Reset collision group to BLOBS when dropped outside center
        blobs[index].collisionFilterGroup = COLLISION_GROUPS.BLOBS;
        blobs[index].collisionFilterMask = COLLISION_GROUPS.BLOBS | COLLISION_GROUPS.CENTER | COLLISION_GROUPS.BOUNDARY | COLLISION_GROUPS.DRAGGED;
        
        // Log the updated center state
        logCenteredBlobs();
      }
    }
  }
  dragObject = null;
}

// Central gravity well force application
function applyGravityWell() {
  for (let i = 0; i < blobs.length; i++) {
    const body = blobs[i];
    const dir = gravityWell.vsub(body.position);
    const distance = dir.length();

    if (!isDragging && blobMeshes[i] !== dragObject) {
      body.position.z = 0;
      body.velocity.z = 0;
      body.angularVelocity.z = 0;
      body.force.z = 0;
      body.torque.z = 0;
    }

    if (fixedBlobs.includes(body)) continue; // Skip fixed blobs
    
    // Skip collision check if this is a centered blob and we're dragging
    if (centerBlobIndices.includes(i) && dragObject) continue;
    
    // Skip repulsion for the blob being dragged if there's already a centered blob
    const isDraggingThisBlob = dragObject === blobMeshes[i];
    if (isDraggingThisBlob && centerBlobIndices.length > 0) continue;
    
    // Always apply gravity to non-dragged blobs, regardless of drag state
    if (!isDraggingThisBlob) {
      dir.normalize();
      const strength = params.gravityStrength / (distance * distance); // inverse square law
      const force = dir.scale(strength);

      const radius = blobVisuals[i].radius; // visual radius

      // Repulsion logic: always use params.dropZoneRadius and (0,0,0) if no blobs are centered
      let repelPos = gravityWell;
      let repelRadius = params.dropZoneRadius;
      if (centerBlobIndices.length > 0) {
        repelPos = blobs[centerBlobIndices[0]].position;
        repelRadius = blobVisuals[centerBlobIndices[0]].radius * blobMeshes[centerBlobIndices[0]].scale.x;
      }

      const toRepel = repelPos.vsub(body.position);
      const repelDistance = toRepel.length();

      // Compute penetration so that repulsion starts when the blob's visible edge meets the drop zone surface
      const penetration = repelRadius - (repelDistance - radius - params.padding);
      if (penetration <= 0) {
        // Only apply gravity if not dragging this blob
        if (!isDraggingThisBlob) {
          body.applyForce(force, new CANNON.Vec3(0, 0, 0));
        }
      } else {
        // Reduce repulsion force when dragging a blob
        const repulsionStrength = isDraggingThisBlob ? 0.1 : 0.5;
        toRepel.normalize();
        const repelForce = toRepel.scale(-params.gravityStrength * repulsionStrength * penetration);
        body.applyForce(repelForce, new CANNON.Vec3(0, 0, 0));
      }
    }

    // Removed inwardForce and reentryForce logic blocks for outer wall containment
    // since the physics engine now enforces containment via the collision mesh.

    if (distance > params.outerRadius * 2) {
      const radius = body.shapes[0].radius;
      const dropRadius = params.dropZoneRadius + radius;
      const outerRadius = params.outerRadius - radius;
      let x = 0, y = 0, z = 0;
      let valid = false;
      while (!valid) {
        x = (Math.random() * 2 - 1) * outerRadius;
        y = (Math.random() * 2 - 1) * outerRadius;
        z = (Math.random() * 2 - 1) * outerRadius;
        const d = Math.sqrt(x * x + y * y + z * z);
        valid = d > dropRadius && d < outerRadius;
      }
      body.position.set(x, y, z);
      body.velocity.set(0, 0, 0);
      body.angularVelocity.set(0, 0, 0);
      body.force.set(0, 0, 0);
      body.torque.set(0, 0, 0);
    }
    if (!isDragging || blobMeshes[i] !== dragObject) {
      body.position.z = 0;
      body.velocity.z = 0;
      body.force.z = 0;
      body.angularVelocity.z = 0;
    }
  }
}

// Inter-blob collision and repulsion handled by physics engine with spheres

// Prevent blobs from entering drop zone unless dragged handled by drag logic

function animate() {
  requestAnimationFrame(animate);

  applyGravityWell();

  // Time scaling for fluid motion
  const deltaTime = 1/60; // Fixed timestep for consistent animation
  const timeScale = 0.5; // Slow down all animations
  
  // Apply gravity and step physics with time scaling
  applyGravityWell();
  world.step(deltaTime * timeScale, deltaTime, 3); // Slower physics steps

  // Update mesh positions from physics bodies and apply scaling
  const scaleLerpFactor = 0.2 * timeScale; // Smoothing factor for scale transitions
  
  for (let i = 0; i < blobs.length; i++) {
    const blobVisual = blobVisuals[i];
    const mesh = blobMeshes[i];
    
    if (!isDragging || mesh !== dragObject) {
      blobs[i].position.z = 0;
      blobs[i].velocity.z = 0;
      blobs[i].angularVelocity.z = 0;
      blobs[i].force.z = 0;
      blobs[i].torque.z = 0;
    }

    // Update position and rotation
    mesh.position.copy(blobs[i].position);
    mesh.quaternion.copy(blobs[i].quaternion);
    
    // Only update target scale if not currently dragging this blob
    if (mesh !== dragObject) {
      if (centerBlobIndices.includes(i)) {
        // Center blob gets special scaling
        blobVisual.setTargetScale(params.centerBlobScale / blobVisual.radius, 'center blob');
      } else if (params.useCenterBlobScaling && centerBlobIndices.length > 0) {
        // Other blobs when there's a center blob
        blobVisual.setTargetScale(params.otherBlobsScale, 'other blob with center');
      } else {
        // Normal state - only set target if not currently being animated to a different scale
        if (blobVisual.targetScale !== 1.0 && 
            Math.abs(blobVisual.currentScale - 1.0) > 0.01) {
          blobVisual.setTargetScale(1.0, 'normal state');
        }
      }
    }
    
    // Update the blob's animation and apply scale
    blobVisual.update(deltaTime); // Use actual deltaTime for smooth animation
    mesh.scale.setScalar(blobVisual.getVisualScale() / blobVisual.radius);
    if (mesh === dragObject) {
      // Updating blob scale
    }
  }

  // Handle center dot hover scaling and visibility
  let isHovering = false;
  let shouldShowCenterNode = true;
  
  if (centerBlobIndices.length === 0) {
    // Only check for hover when there's no center blob
    if (dragObject) {
      const index = blobMeshes.indexOf(dragObject);
      if (index !== -1) {
        const distanceToCenter = blobs[index].position.length();
        isHovering = distanceToCenter < 2.5;
      }
    }
    
    // Apply hover scale or return to normal
    const targetScale = isHovering ? 
      params.centerNodeSize * params.dragHoverScale : 
      params.centerNodeSize;
    const targetOpacity = isHovering ? 0.8 : 0.5;
    
    // Smoothly interpolate to target scale and opacity
    centerNode.scale.lerp(
      new THREE.Vector3(targetScale, targetScale, 1), 
      0.2 * timeScale
    );
    centerNode.material.opacity = THREE.MathUtils.lerp(
      centerNode.material.opacity,
      targetOpacity,
      0.2 * timeScale
    );
  } else {
    // When there's a center blob, fade out the center node
    shouldShowCenterNode = false;
  }
  
  // Update center node visibility based on the current state
  if (shouldShowCenterNode && !centerNode.visible) {
    centerNode.visible = true;
  } else if (!shouldShowCenterNode && centerNode.visible) {
    centerNode.visible = false;
  }

  // Handle all centered blobs
  centerBlobIndices.forEach((centerIndex, idx) => {
    const body = blobs[centerIndex];
    const mesh = blobMeshes[centerIndex];
    const visual = blobVisuals[centerIndex];
    
    // Smoothly animate to center
    if (!isDragging || mesh !== dragObject) {
      // Scale is handled by BlobVisual's targetScale in the main loop
      // Just handle position animation here
      
      // Smoothly interpolate position to center
      const center = new CANNON.Vec3(0, 0, 0);
      const toCenter = center.vsub(body.position);
      const distance = toCenter.length();
      
      if (distance > 0.01) { // If not already at center
        // Apply a spring force toward center with damping
        const springForce = 10.0; // Adjust for snappier/slower animation
        const damping = 0.8; // Damping factor (0-1)
        
        // Update position with spring physics
        toCenter.normalize();
        const targetVelocity = toCenter.scale(Math.min(distance * springForce, 5));
        const velocityDiff = targetVelocity.vsub(body.velocity);
        
        body.velocity.x += velocityDiff.x * (1 - damping) * timeScale;
        body.velocity.y += velocityDiff.y * (1 - damping) * timeScale;
      } else {
        // Snap to center and stop when close enough
        body.position.set(0, 0, 0);
        body.velocity.set(0, 0, 0);
        body.angularVelocity.set(0, 0, 0);
        body.force.set(0, 0, 0);
        body.torque.set(0, 0, 0);
      }
      
      // Only hide the blob if it's not the first one in the center
      mesh.visible = idx === 0;
    }
  });

  // Fade logic for centerNode
  if (fadeCenterNodeOut) {
    if (centerNode.material.opacity > 0) {
      centerNode.material.opacity = Math.max(0, centerNode.material.opacity - 0.05 * timeScale);
      if (centerNode.material.opacity <= 0) {
        centerNode.visible = false;
        fadeCenterNodeOut = false;
      }
    }
  } else if (fadeCenterNodeIn) {
    if (!centerNode.visible) centerNode.visible = true;
    if (centerNode.material.opacity < 0.5) {
      centerNode.material.opacity = Math.min(0.5, centerNode.material.opacity + 0.05 * timeScale);
      if (centerNode.material.opacity >= 0.5) {
        centerNode.material.opacity = 0.5;
        fadeCenterNodeIn = false;
      }
    }
  } else if (centerBlobIndices.length === 0) {
    // Ensure center node is visible when there's no center blob
    if (!centerNode.visible) {
      centerNode.visible = true;
      centerNode.material.opacity = 0.5;
    }
  }

  controls.update();
  renderer.render(scene, camera);
}

function onWindowResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();

  renderer.setSize(window.innerWidth, window.innerHeight);
}
