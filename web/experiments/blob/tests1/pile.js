import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import * as CANNON from 'cannon-es';
import GUI from 'lil-gui';

let fadeCenterNodeOut = false;
let fadeCenterNodeIn = false;

let scene, camera, renderer, controls;
let world;
let blobs = [];
let blobMeshes = [];
let fixedBlobs = [];
let dragControls = [];
let raycaster, mouse;
let dragObject = null;
let plane;
let gravityWell;
let dropZone;
let outerZone;
let outerWall;
let gui;
let centerNode;
let params = {
  numBlobs: 6,
  minRadius: 1.5,
  maxRadius: 1.75,
  radiusRandomness: 0.5,
  padding: 0.4,
  gravityStrength: 200, // Reduced for slower movement
  outerRadius: 8,
  dropZoneRadius: 2,
  centerBlobScale: 2.2,
  previewBounds: false,
  dragHoverScale: 1.3,
  centerNodeSize: .4,
  otherBlobsScale: 0.7,
  useCenterBlobScaling: true,
  blobActiveScale: 1.1 // Scale when blob is being actively dragged
};
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
  constructor(radius) {
    this.radius = radius;
    this.targetScale = 1;  // Target scale (1 = normal scale)
    this.currentScale = 1; // Current rendered scale
  }
}

// Helper function to get or create blob visual state
function getBlobVisual(index, radius) {
  if (!blobVisuals[index]) {
    blobVisuals[index] = new BlobVisual(radius);
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

  // Physics world
  world = new CANNON.World();
  world.gravity.set(0, 0, 0); // We'll implement central gravity manually
  world.broadphase = new CANNON.NaiveBroadphase();
  world.solver.iterations = 10;
  // Add more damping for fluid-like movement
  world.defaultContactMaterial.contactEquationStiffness = 1e6;
  world.defaultContactMaterial.contactEquationRelaxation = 4;

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
  gui.add(params, 'outerRadius', 1, 50, 0.1).name('Outer Radius').onChange(updateBounds);
  gui.add(params, 'dropZoneRadius', 0.1, 10, 0.1).name('Drop Zone Radius').onChange(updateBounds);
  gui.add(params, 'centerBlobScale', 0.1, 10, 0.1).name('Center Blob Size');
  gui.add(params, 'previewBounds').name('Preview Bounds').onChange(updateBoundsVisibility);
  gui.add(params, 'dragHoverScale', 1, 2, 0.01).name('Hover Scale');
  gui.add(params, 'centerNodeSize', 0.1, 10, 0.1).name('Center Node Size');
  gui.add(params, 'otherBlobsScale', 0.1, 2, 0.05).name('Other Blobs Scale');
  gui.add(params, 'useCenterBlobScaling').name('Enable Center Blob Scaling');
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

  // Outer zone - wireframe sphere
  const outerZoneGeometry = new THREE.SphereGeometry(params.outerRadius, 32, 32);
  const outerZoneMaterial = new THREE.MeshBasicMaterial({
    color: 0xff0000,
    wireframe: true,
    transparent: true,
    opacity: 0.3,
    visible: true
  });
  outerZone = new THREE.Mesh(outerZoneGeometry, outerZoneMaterial);
  scene.add(outerZone);

  // Create outer wall physics body using Trimesh
  const outerGeometry = new THREE.SphereGeometry(params.outerRadius, 32, 32);
  const outerVertices = outerGeometry.attributes.position.array;
  const outerIndices = Array.from({ length: outerVertices.length / 3 }, (_, i) => i);
  const outerShape = new CANNON.Trimesh(outerVertices, outerIndices);
  outerWall = new CANNON.Body({ mass: 0 });
  outerWall.addShape(outerShape);
  world.addBody(outerWall);

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

function updateBoundsVisibility() {
  dropZone.visible = params.previewBounds;
  outerZone.visible = params.previewBounds;
}

function updateBounds() {
  dropZone.geometry.dispose();
  dropZone.geometry = new THREE.SphereGeometry(params.dropZoneRadius, 32, 32);

  outerZone.geometry.dispose();
  outerZone.geometry = new THREE.SphereGeometry(params.outerRadius, 32, 32);

  // Update outerWall shape to match new outerRadius
  world.removeBody(outerWall);
  const outerGeometry = new THREE.SphereGeometry(params.outerRadius, 32, 32);
  const outerVertices = outerGeometry.attributes.position.array;
  const outerIndices = Array.from({ length: outerVertices.length / 3 }, (_, i) => i);
  const outerShape = new CANNON.Trimesh(outerVertices, outerIndices);
  outerWall = new CANNON.Body({ mass: 0 });
  outerWall.addShape(outerShape);
  world.addBody(outerWall);
}

function updateCenterBlobScale() {
  // Center blob scale is now handled directly in the animate function
  // when a blob is in the center position
}

function createBlobs() {
  clearBlobs();

  for (let i = 0; i < params.numBlobs; i++) {
    let radius = THREE.MathUtils.lerp(params.minRadius, params.maxRadius, Math.random());
    radius += (Math.random() - 0.5) * params.radiusRandomness;
    radius = Math.max(params.minRadius, Math.min(params.maxRadius, radius));
    // Visual state is now managed by blobVisuals array

    // Position blobs at random within outer sphere and outside drop zone
    let x = 0, y = 0, z = 0;
    const dropRadius = params.dropZoneRadius + radius + params.padding;
    const outerRadius = params.outerRadius - radius - params.padding;
    let valid = false;
    while (!valid) {
      x = (Math.random() * 2 - 1) * outerRadius;
      y = (Math.random() * 2 - 1) * outerRadius;
      z = (Math.random() * 2 - 1) * outerRadius;
      const d = Math.sqrt(x * x + y * y + z * z);
      valid = d > dropRadius && d < outerRadius;
    }

    const totalRadius = radius + params.padding;

    // Initialize visual state for this blob
    const blobVisual = new BlobVisual(radius);
    blobVisuals.push(blobVisual);
    
    // Three.js mesh
    const geometry = new THREE.SphereGeometry(radius, 32, 32);
    const material = new THREE.MeshStandardMaterial({ color: new THREE.Color(Math.random(), Math.random(), Math.random()) });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(x, y, z);
    scene.add(mesh);
    blobMeshes.push(mesh);
    
    // Set initial scale
    mesh.scale.setScalar(blobVisual.currentScale);

    // Physics body
    const shape = new CANNON.Sphere(totalRadius);
    const body = new CANNON.Body({ mass: 1, shape: shape, position: new CANNON.Vec3(x, y, z) });
    // Increased damping for more fluid resistance
    body.linearDamping = 0.95;
    body.angularDamping = 0.95;
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
      // Set target scale for active drag
      blobVisuals[index].targetScale = params.blobActiveScale;
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
      // If we've moved away from the center, remove center state
      const distToCenter = blobs[index].position.length();
      if (distToCenter > params.dropZoneRadius * 0.8) { 
        const body = blobs[index];
        body.mass = 1; // Restore mass
        body.updateMassProperties();
        centerBlobIndices.splice(centerIndex, 1); // Remove from center
        blobMeshes[index].visible = true; // Make sure it's visible
        logCenteredBlobs();
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
      if (distToCenter < params.dropZoneRadius) {
        // Add to center if not already centered
        if (!centerBlobIndices.includes(index)) {
          centerBlobIndices.push(index);
          // Defer to animate loop to ease into center
          blobs[index].velocity.set(0, 0, 0);
          blobs[index].angularVelocity.set(0, 0, 0);
          blobs[index].mass = 0;
          blobs[index].updateMassProperties();
          // Only hide the blob if it's not the first one in the center
          if (centerBlobIndices.length > 1) {
            blobMeshes[index].visible = false;
          }
          // animate scale in animate loop
          fadeCenterNodeOut = true;
          fadeCenterNodeIn = false;
          logCenteredBlobs();
        }
      } else {
        // Reset target scale when dropped (actual scale will animate to this)
        blobVisuals[index].targetScale = 1.0;
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

    if (!isDragging || blobMeshes[i] !== dragObject) {
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
    
    if (!isDragging) {
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
    
    // Update target scale based on state
    if (centerBlobIndices.includes(i)) {
      // Center blob gets special scaling
      blobVisual.targetScale = params.centerBlobScale / blobVisual.radius;
    } else if (params.useCenterBlobScaling && centerBlobIndices.length > 0) {
      // Other blobs when there's a center blob
      blobVisual.targetScale = params.otherBlobsScale;
    } else {
      // Normal state
      blobVisual.targetScale = 1.0;
    }
    
    // Smoothly interpolate to target scale
    blobVisual.currentScale = THREE.MathUtils.lerp(
      blobVisual.currentScale,
      blobVisual.targetScale,
      scaleLerpFactor
    );
    
    // Apply the scale to the mesh
    mesh.scale.setScalar(blobVisual.currentScale);
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
      // Calculate target scale for centered blobs
      const targetScale = idx === 0 ? 
        (params.centerBlobScale / visual.radius) : 
        (params.otherBlobsScale / visual.radius);
      
      // Smoothly interpolate position to center
      const center = new CANNON.Vec3(0, 0, 0);
      const toCenter = center.vsub(body.position);
      const distance = toCenter.length();
      
      if (distance > 0.01) { // If not already at center
        // Apply a spring force toward center with damping
        const springForce = 10.0; // Adjust for snappier/slower animation
        const damping = 0.8; // Damping factor (0-1)
        
        toCenter.normalize();
        const targetVelocity = toCenter.scale(Math.min(distance * springForce, 5));
        const velocityDiff = targetVelocity.vsub(body.velocity);
        
        body.velocity.x += velocityDiff.x * (1 - damping) * timeScale;
        body.velocity.y += velocityDiff.y * (1 - damping) * timeScale;
        
        // Update visual scale smoothly
        visual.targetScale = targetScale;
        visual.currentScale += (visual.targetScale - visual.currentScale) * 0.2 * timeScale;
        mesh.scale.setScalar(visual.currentScale);
      } else {
        // Snap to center and stop when close enough
        body.position.set(0, 0, 0);
        body.velocity.set(0, 0, 0);
        body.angularVelocity.set(0, 0, 0);
        body.force.set(0, 0, 0);
        body.torque.set(0, 0, 0);
        
        // Set final scale
        mesh.scale.setScalar(targetScale);
        visual.currentScale = targetScale;
      }
      
      // Only hide the blob if it's not the first one in the center
      if (idx > 0) {
        mesh.visible = false;
      } else {
        mesh.visible = true;
      }
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
