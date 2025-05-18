import * as THREE from 'three';
import GUI from 'lil-gui';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { DragControls } from 'three/examples/jsm/controls/DragControls.js';

let scene, camera, renderer, orbitControls, dragControls, clock;
let centerNode, blobs = [];
let raycaster, mouse;
let draggedBlob = null;
let isDragging = false;
let mergeCandidate = null;
let mergeIndicator = null;

const params = {
    blobSize: 0.5,
    sizeRandomizer: 0.2,
    clusterRadius: 3.0,
    blobPadding: 0.2,
    centerVoidRadius: 0.8,
    nodeSize: 0.15,
    nodeColor: '#ffffff',
    backgroundColor: '#000000',
    totalBlobs: 10,
    springStrength: 0.1,
    damping: 0.9,
    mergeDistance: 1.0,
    attractionStrength: 0.2,
    mergeThreshold: 0.4,
    mergedBlobSizeFactor: 1.0
};

// Material properties from main.js
const materialParams = {
    color1: '#be62df',
    color2: '#628fea',
    color3: '#000000',
    roughness: 0.3,
    metalness: 0.0,
    clearcoat: 0.1,
    clearcoatRoughness: 0,
    transmission: 0.34,
    reflectivity: 1,
    ior: 1.93,
    distortAmount: 0.43,
    stop1: 0.0,
    stop2: 0.35,
    stop3: 0.62,
    fresnelStrength: 1,
    envMapIntensity: 1.25,
    iridescence: 0.75,
    iridescenceIOR: 1.3,
};

init();
animate();

function init() {
    // Scene setup
    scene = new THREE.Scene();
    scene.background = new THREE.Color(params.backgroundColor);
    
    // Camera setup - moved farther back to view the grid
    camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 100);
    camera.position.z = 8;
    
    // Renderer setup
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    document.getElementById('app').appendChild(renderer.domElement);
    
    // Controls setup for mouse drag rotation
    orbitControls = new OrbitControls(camera, renderer.domElement);
    orbitControls.enableDamping = true;
    orbitControls.dampingFactor = 0.05;
    orbitControls.enablePan = false;
    orbitControls.minDistance = 2;
    orbitControls.maxDistance = 20; // Allow zooming out further
    
    // Setup raycaster and mouse
    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();
    
    // Clock for animation
    clock = new THREE.Clock();
    
    // Create merge indicator (invisible initially)
    createMergeIndicator();
    
    // Create center node - position at center of grid
    createCenterNode();
    centerNode.position.set(0, 0, -0.5); // Slightly behind the grid
    
    // Create grid of blobs
    createBlobs();
    
    // Setup drag controls
    setupDragControls();
    
    // Add lights
    addLights();
    
    // GUI Controls
    setupGUI();
    
    // Handle window resize
    window.addEventListener('resize', onWindowResize);
}

function createMergeIndicator() {
    // Create a visual indicator for potential merges
    const geometry = new THREE.SphereGeometry(1, 32, 32);
    const material = new THREE.MeshBasicMaterial({
        color: 0xffffff,
        transparent: true,
        opacity: 0.3,
        wireframe: true
    });
    
    mergeIndicator = new THREE.Mesh(geometry, material);
    mergeIndicator.visible = false;
    scene.add(mergeIndicator);
}

function setupDragControls() {
    // Create drag controls for blobs
    dragControls = new DragControls(blobs, camera, renderer.domElement);
    
    // Add listeners for drag events
    dragControls.addEventListener('dragstart', function(event) {
        // Disable orbit controls while dragging
        orbitControls.enabled = false;
        
        // Mark the blob as being dragged
        draggedBlob = event.object;
        isDragging = true;
        
        // Reset velocity when starting drag
        draggedBlob.userData.velocity = new THREE.Vector3(0, 0, 0);
        
        // Change the blob's material to indicate it's being dragged
        draggedBlob.userData.originalEmissive = draggedBlob.material.emissive.clone();
        draggedBlob.material.emissive.set('#333333');
    });
    
    dragControls.addEventListener('drag', function(event) {
        // Calculate delta position for physics
        if (draggedBlob) {
            const newPos = event.object.position.clone();
            if (draggedBlob.userData.lastPosition) {
                const delta = newPos.clone().sub(draggedBlob.userData.lastPosition);
                draggedBlob.userData.velocity = delta.multiplyScalar(10); // Scale for more momentum
            }
            draggedBlob.userData.lastPosition = newPos.clone();
            
            // Check for potential merges
            checkForMergeCandidate(draggedBlob);
        }
    });
    
    dragControls.addEventListener('dragend', function(event) {
        // Re-enable orbit controls
        orbitControls.enabled = true;
        
        // Reset emissive color
        if (draggedBlob && draggedBlob.userData.originalEmissive) {
            draggedBlob.material.emissive.copy(draggedBlob.userData.originalEmissive);
        }
        
        // Check if we should merge blobs based on screen space overlap
        if (mergeCandidate && draggedBlob) {
            // Get screen positions
            const blob1Screen = new THREE.Vector3();
            const blob2Screen = new THREE.Vector3();
            
            draggedBlob.getWorldPosition(blob1Screen);
            mergeCandidate.getWorldPosition(blob2Screen);
            
            blob1Screen.project(camera);
            blob2Screen.project(camera);
            
            // Convert to screen coordinates
            const blob1X = (blob1Screen.x * 0.5 + 0.5) * window.innerWidth;
            const blob1Y = (blob1Screen.y * -0.5 + 0.5) * window.innerHeight;
            const blob2X = (blob2Screen.x * 0.5 + 0.5) * window.innerWidth;
            const blob2Y = (blob2Screen.y * -0.5 + 0.5) * window.innerHeight;
            
            // Calculate screen distance
            const screenDistance = Math.sqrt(
                Math.pow(blob2X - blob1X, 2) + 
                Math.pow(blob2Y - blob1Y, 2)
            );
            
            // Get blob screen radii (simplified)
            const blob1Radius = draggedBlob.userData.originalSize / 
                draggedBlob.position.distanceTo(camera.position) * 500;
            const blob2Radius = mergeCandidate.userData.originalSize / 
                mergeCandidate.position.distanceTo(camera.position) * 500;
            
            // Check if there's significant screen space overlap
            if (screenDistance < (blob1Radius + blob2Radius) * 0.8) {
                mergeBlobs(draggedBlob, mergeCandidate);
            } else {
                // Reset shapes
                resetBlobShape(draggedBlob);
                resetBlobShape(mergeCandidate);
            }
        } else if (draggedBlob) {
            // Reset shape
            resetBlobShape(draggedBlob);
        }
        
        // Reset merge indicator and state
        mergeIndicator.visible = false;
        mergeCandidate = null;
        
        // Mark as no longer dragging
        isDragging = false;
    });
}

function checkForMergeCandidate(blob) {
    let closestBlob = null;
    let closestDistance = Infinity;
    let screenOverlap = false;
    
    // Get 2D screen position of the dragged blob
    const blobScreenPosition = new THREE.Vector3();
    blob.getWorldPosition(blobScreenPosition);
    blobScreenPosition.project(camera);
    
    // Convert to screen coordinates
    const blobScreenX = (blobScreenPosition.x * 0.5 + 0.5) * window.innerWidth;
    const blobScreenY = (blobScreenPosition.y * -0.5 + 0.5) * window.innerHeight;
    
    // Get apparent radius in screen space
    // Project a point on the edge of the sphere
    const edgeWorld = new THREE.Vector3(
        blob.position.x + blob.userData.originalSize, 
        blob.position.y, 
        blob.position.z
    );
    const edgeScreen = edgeWorld.clone().project(camera);
    const edgeScreenX = (edgeScreen.x * 0.5 + 0.5) * window.innerWidth;
    const edgeScreenY = (edgeScreen.y * -0.5 + 0.5) * window.innerHeight;
    
    // Calculate screen radius based on distance between center and edge
    const blobScreenRadius = Math.sqrt(
        Math.pow(edgeScreenX - blobScreenX, 2) + 
        Math.pow(edgeScreenY - blobScreenY, 2)
    );
    
    // Find the closest blob with screen space overlap
    blobs.forEach(otherBlob => {
        if (otherBlob !== blob) {
            // Get 2D screen position of the other blob
            const otherScreenPosition = new THREE.Vector3();
            otherBlob.getWorldPosition(otherScreenPosition);
            otherScreenPosition.project(camera);
            
            // Convert to screen coordinates
            const otherScreenX = (otherScreenPosition.x * 0.5 + 0.5) * window.innerWidth;
            const otherScreenY = (otherScreenPosition.y * -0.5 + 0.5) * window.innerHeight;
            
            // Get other blob's apparent radius in screen space
            const otherEdgeWorld = new THREE.Vector3(
                otherBlob.position.x + otherBlob.userData.originalSize, 
                otherBlob.position.y, 
                otherBlob.position.z
            );
            const otherEdgeScreen = otherEdgeWorld.clone().project(camera);
            const otherEdgeScreenX = (otherEdgeScreen.x * 0.5 + 0.5) * window.innerWidth;
            const otherEdgeScreenY = (otherEdgeScreen.y * -0.5 + 0.5) * window.innerHeight;
            
            const otherScreenRadius = Math.sqrt(
                Math.pow(otherEdgeScreenX - otherScreenX, 2) + 
                Math.pow(otherEdgeScreenY - otherScreenY, 2)
            );
            
            // Calculate screen distance between blob centers
            const screenDistance = Math.sqrt(
                Math.pow(otherScreenX - blobScreenX, 2) + 
                Math.pow(otherScreenY - blobScreenY, 2)
            );
            
            // Check if there's screen space overlap
            const hasOverlap = screenDistance < (blobScreenRadius + otherScreenRadius) * 1.2;
            
            // Also check actual 3D distance for physics interactions
            const worldDistance = blob.position.distanceTo(otherBlob.position);
            
            if (hasOverlap && worldDistance < closestDistance) {
                closestDistance = worldDistance;
                closestBlob = otherBlob;
                screenOverlap = true;
            }
        }
    });
    
    // Update merge candidate
    mergeCandidate = closestBlob;
    
    // Update visual effects for merging
    if (mergeCandidate && screenOverlap) {
        // Calculate direction vector for magnetized morphing
        const direction = mergeCandidate.position.clone().sub(blob.position).normalize();
        const distance = blob.position.distanceTo(mergeCandidate.position);
        
        // Calculate overlap percentage for morphing effect
        const size1 = blob.userData.originalSize;
        const size2 = mergeCandidate.userData.originalSize;
        const totalSize = size1 + size2;
        const overlapPercent = Math.max(0, 1 - (distance / (totalSize * 1.5)));
        
        // Apply magnetized deformation to both blobs
        applyLiquidMorphing(blob, mergeCandidate, overlapPercent);
        
        // Hide wire indicator and use actual mesh deformation instead
        mergeIndicator.visible = false;
        
        // Apply attraction force toward merge candidate (stronger when overlapping)
        if (isDragging) {
            // Stronger attraction force for more magnetic feel
            const attractionStrength = params.attractionStrength * overlapPercent * 1.5;
            blob.position.add(direction.clone().multiplyScalar(attractionStrength));
        }
    } else {
        // Reset blob morphing if no overlap
        resetBlobShape(blob);
        if (mergeCandidate) {
            resetBlobShape(mergeCandidate);
        }
        
        // Hide indicator if no merge candidate
        mergeIndicator.visible = false;
    }
}

function applyLiquidMorphing(blob1, blob2, overlapPercent) {
    // Skip if we're not close enough for visible effect
    if (overlapPercent < 0.05) {
        resetBlobShape(blob1);
        resetBlobShape(blob2);
        return;
    }
    
    // Direction from blob1 to blob2
    const direction = blob2.position.clone().sub(blob1.position).normalize();
    
    // Apply deformation to both blob meshes to create liquid-like effect
    deformBlobMesh(blob1, direction, overlapPercent, true);
    deformBlobMesh(blob2, direction.clone().multiplyScalar(-1), overlapPercent, false);
    
    // Prepare blobs for possible merging
    blob1.userData.isDeformed = true;
    blob2.userData.isDeformed = true;
}

function deformBlobMesh(blob, direction, strength, isPrimary) {
    // Get the geometry
    const geometry = blob.geometry;
    const positionAttribute = geometry.attributes.position;
    const vertex = new THREE.Vector3();
    const normal = new THREE.Vector3();
    
    // Store original geometry if not already stored
    if (!blob.userData.originalVertices) {
        const originalVertices = [];
        for (let i = 0; i < positionAttribute.count; i++) {
            vertex.fromBufferAttribute(positionAttribute, i);
            originalVertices.push(vertex.clone());
        }
        blob.userData.originalVertices = originalVertices;
    }
    
    // Time for animated effects
    const time = clock.getElapsedTime();
    
    // Maximum deformation factor - higher for more dramatic effect
    const maxDeform = isPrimary ? 0.6 : 0.5;
    
    // Apply deformation
    for (let i = 0; i < positionAttribute.count; i++) {
        // Get original vertex
        const originalVertex = blob.userData.originalVertices[i].clone();
        
        // Calculate normal direction
        normal.copy(originalVertex).normalize();
        
        // Dot product to determine which side of the blob is facing the other blob
        const dot = normal.dot(direction);
        
        // Calculate base vertex position
        vertex.copy(originalVertex);
        
        // Vertices facing the other blob get stretching "magnetized" effect
        if (dot > 0) {
            // Stronger magnetized effect - stretch MORE toward direction
            const magnetStrength = Math.pow(dot, 1.5) * maxDeform * strength * 1.5;
            const stretchOffset = direction.clone().multiplyScalar(magnetStrength * blob.userData.originalSize);
            vertex.add(stretchOffset);
            
            // Add ripple effect that increases as blobs get closer
            // Ripples become more intense when the blobs are closer (higher strength)
            const rippleIntensity = 0.15 * strength;
            const rippleFrequency = 15.0;
            const rippleSpeed = 5.0;
            
            // Wave pattern that spreads from the direction of attraction
            const angle = Math.atan2(normal.y, normal.x);
            const distFromAxis = Math.abs(Math.sin(angle - Math.atan2(direction.y, direction.x)));
            
            // Circular ripple effect emanating from contact point
            const ripple = rippleIntensity * Math.sin(
                distFromAxis * rippleFrequency + 
                time * rippleSpeed
            ) * Math.pow(dot, 2);
            
            // Apply ripple along normal direction
            vertex.add(normal.clone().multiplyScalar(ripple * blob.userData.originalSize));
        } else {
            // Vertices on other side should bulge outward to maintain volume appearance
            // This creates the "pulled taffy" effect of magnetism
            const bulgeStrength = -dot * 0.2 * strength; 
            vertex.add(normal.clone().multiplyScalar(bulgeStrength * blob.userData.originalSize));
        }
        
        positionAttribute.setXYZ(i, vertex.x, vertex.y, vertex.z);
    }
    
    positionAttribute.needsUpdate = true;
}

function resetBlobShape(blob) {
    if (!blob || !blob.userData.originalVertices) return;
    
    const positionAttribute = blob.geometry.attributes.position;
    
    // Restore original vertex positions
    for (let i = 0; i < positionAttribute.count; i++) {
        const originalVertex = blob.userData.originalVertices[i];
        positionAttribute.setXYZ(i, originalVertex.x, originalVertex.y, originalVertex.z);
    }
    
    positionAttribute.needsUpdate = true;
    blob.userData.isDeformed = false;
}

function mergeBlobs(blob1, blob2) {
    // Make sure both blobs exist (one might have been merged in a previous frame)
    if (!blob1 || !blob2 || !blobs.includes(blob1) || !blobs.includes(blob2)) {
        return;
    }
    
    // Determine which blob is the destination (the one being dragged to)
    const destinationBlob = blob1 === draggedBlob ? blob2 : blob1;
    const sourceBlob = blob1 === draggedBlob ? blob1 : blob2;
    
    // Calculate properties for the new blob
    const size1 = sourceBlob.userData.originalSize;
    const size2 = destinationBlob.userData.originalSize;
    
    // Calculate combined size based on volume, adjusted by the mergedBlobSizeFactor
    const combinedSize = Math.pow(Math.pow(size1, 3) + Math.pow(size2, 3), 1/3) * params.mergedBlobSizeFactor;
    
    // Use the position of the destination blob, not weighted average
    const newPosition = destinationBlob.position.clone();
    
    // Recalculate rest position - weighted by volume
    const newOriginalPosition = new THREE.Vector3()
        .addScaledVector(sourceBlob.userData.originalPosition, Math.pow(size1, 3))
        .addScaledVector(destinationBlob.userData.originalPosition, Math.pow(size2, 3))
        .divideScalar(Math.pow(size1, 3) + Math.pow(size2, 3));
    
    // Remove old blobs
    scene.remove(sourceBlob);
    scene.remove(destinationBlob);
    blobs = blobs.filter(blob => blob !== sourceBlob && blob !== destinationBlob);
    
    // Create new merged blob with higher resolution for better morphing
    const geometry = new THREE.IcosahedronGeometry(combinedSize, 7);
    const material = destinationBlob.material.clone();
    
    const newBlob = new THREE.Mesh(geometry, material);
    newBlob.position.copy(newPosition);
    
    // Store metadata
    newBlob.userData.originalPosition = newOriginalPosition;
    newBlob.userData.originalSize = combinedSize;
    newBlob.userData.velocity = new THREE.Vector3(0, 0, 0);
    newBlob.userData.lastPosition = newPosition.clone();
    
    // Add to scene
    scene.add(newBlob);
    blobs.push(newBlob);
    
    // Reinitialize drag controls
    dragControls.dispose();
    setupDragControls();
    
    // Reset state
    draggedBlob = null;
    mergeCandidate = null;
    isDragging = false;
}

function createCenterNode() {
    const geometry = new THREE.SphereGeometry(params.nodeSize, 32, 32);
    const material = new THREE.MeshStandardMaterial({
        color: new THREE.Color(params.nodeColor),
        roughness: 0.2,
        metalness: 0.8,
        emissive: new THREE.Color(params.nodeColor),
        emissiveIntensity: 0.5
    });
    
    centerNode = new THREE.Mesh(geometry, material);
    scene.add(centerNode);
}

function createGradientTexture(c1, c2, c3) {
    const size = 512;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    const imgData = ctx.createImageData(size, size);

    const color1 = new THREE.Color(c1);
    const color2 = new THREE.Color(c2);
    const color3 = new THREE.Color(c3);

    // Compute stops and easing
    const stop1 = materialParams.stop1;
    const stop2 = materialParams.stop2;
    const stop3 = materialParams.stop3;
    const stopEase = 1; // Default ease value

    for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
            const dx = x - size / 2;
            const dy = y - size / 2;
            let dist = Math.sqrt(dx * dx + dy * dy) / (size / 2);
            dist = Math.min(dist, 1);

            let t;
            let color = new THREE.Color();

            if (dist < stop2) {
                // Interpolate from color1 to color2
                t = (dist - stop1) / (stop2 - stop1);
                t = Math.max(0, Math.min(1, t));
                color.lerpColors(color1, color2, t);
            } else {
                // Interpolate from color2 to color3, with nonlinear easing
                t = (dist - stop2) / (stop3 - stop2);
                t = Math.max(0, Math.min(1, t));
                t = Math.pow(t, stopEase); // nonlinear easing
                color.lerpColors(color2, color3, t);
            }

            const index = (y * size + x) * 4;
            imgData.data[index] = color.r * 255;
            imgData.data[index + 1] = color.g * 255;
            imgData.data[index + 2] = color.b * 255;
            imgData.data[index + 3] = 255;
        }
    }

    ctx.putImageData(imgData, 0, 0);

    const texture = new THREE.CanvasTexture(canvas);
    texture.mapping = THREE.EquirectangularReflectionMapping;
    texture.center.set(0.5, 0.5);
    texture.rotation = 0;
    texture.needsUpdate = true;

    return texture;
}

function createBlobs() {
    // Clear existing blobs
    blobs.forEach(blob => scene.remove(blob));
    blobs = [];
    
    // Create the base material with gradient texture
    const gradientTexture = createGradientTexture(
        materialParams.color1, 
        materialParams.color2, 
        materialParams.color3
    );
    
    // Generate positions for blobs in a natural cluster around the center
    const positions = generateClusteredPositions(params.totalBlobs, params.clusterRadius, params.blobPadding);
    
    // Create each blob
    for (let i = 0; i < params.totalBlobs; i++) {
        // Random size variation
        const sizeVariation = 1.0 + (Math.random() * 2 - 1) * params.sizeRandomizer;
        const size = params.blobSize * sizeVariation;
        
        // Get position from the generated positions
        const position = positions[i] || new THREE.Vector3(0, 0, 0);
        const x = position.x;
        const y = position.y;
        const z = position.z;
        
        // Create geometry
        const geometry = new THREE.IcosahedronGeometry(size, 6);
        
        // Create material (similar to main.js)
        const material = new THREE.MeshPhysicalMaterial({
            color: 0xffffff,
            roughness: materialParams.roughness,
            metalness: materialParams.metalness,
            clearcoat: materialParams.clearcoat,
            clearcoatRoughness: materialParams.clearcoatRoughness,
            transmission: materialParams.transmission,
            thickness: 1,
            reflectivity: materialParams.reflectivity,
            ior: materialParams.ior,
            transparent: true,
            envMapIntensity: materialParams.envMapIntensity,
            iridescence: materialParams.iridescence,
            iridescenceIOR: materialParams.iridescenceIOR,
            iridescenceThicknessRange: [100, 400],
        });
        
        material.envMap = gradientTexture;
        material.envMapRotation = new THREE.Euler(0, 0, 0);
        material.needsUpdate = true;
        
        // Create the blob mesh
        const blob = new THREE.Mesh(geometry, material);
        blob.position.set(x, y, z);
        
        // Store original position and size for animation
        blob.userData.originalPosition = new THREE.Vector3(x, y, z);
        blob.userData.originalSize = size;
        blob.userData.velocity = new THREE.Vector3(0, 0, 0);
        blob.userData.lastPosition = new THREE.Vector3(x, y, z);
        
        scene.add(blob);
        blobs.push(blob);
    }
    
    // Update params.totalBlobs to match actual count
    params.totalBlobs = blobs.length;
    
    // Need to reinitialize drag controls when blobs change
    if (dragControls) {
        dragControls.dispose();
        setupDragControls();
    }
    
    // Update camera position to better view the cluster
    camera.position.z = Math.max(8, params.clusterRadius * 2.5);
    orbitControls.update();
}

function addLights() {
    // Ambient light
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);
    
    // Point light at center
    const pointLight = new THREE.PointLight(0xffffff, 1);
    pointLight.position.set(0, 0, 0);
    scene.add(pointLight);
    
    // Directional light
    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(5, 5, 5);
    scene.add(directionalLight);
}

function setupGUI() {
    const gui = new GUI();
    
    // Blob controls
    const blobFolder = gui.addFolder('Blob Settings');
    blobFolder.add(params, 'blobSize', 0.1, 1.5, 0.05).name('Base Size').onChange(createBlobs);
    blobFolder.add(params, 'sizeRandomizer', 0, 1, 0.05).name('Size Randomizer').onChange(createBlobs);
    blobFolder.add(params, 'clusterRadius', 1, 10, 0.5).name('Cluster Radius').onChange(createBlobs);
    blobFolder.add(params, 'blobPadding', 0, 1, 0.05).name('Blob Padding').onChange(createBlobs);
    blobFolder.add(params, 'totalBlobs', 1, 30, 1).name('Number of Blobs').onChange(createBlobs);
    
    // Center void controls
    const voidFolder = gui.addFolder('Center Void');
    voidFolder.add(params, 'centerVoidRadius', 0.2, 3, 0.1).name('Void Radius').onChange(createBlobs);
    
    // Physics controls
    const physicsFolder = gui.addFolder('Physics');
    physicsFolder.add(params, 'springStrength', 0.01, 0.5, 0.01).name('Spring Strength');
    physicsFolder.add(params, 'damping', 0.5, 0.99, 0.01).name('Damping');
    
    // Merge controls
    const mergeFolder = gui.addFolder('Merge Settings');
    mergeFolder.add(params, 'mergeDistance', 0.5, 3, 0.1).name('Merge Detection Dist');
    mergeFolder.add(params, 'attractionStrength', 0, 1, 0.05).name('Attraction Force');
    mergeFolder.add(params, 'mergeThreshold', 0.1, 1.0, 0.05).name('Merge Threshold');
    mergeFolder.add(params, 'mergedBlobSizeFactor', 0.5, 2.0, 0.05).name('Merged Size Factor');
    
    // Center node controls
    const nodeFolder = gui.addFolder('Center Node');
    nodeFolder.add(params, 'nodeSize', 0.05, 0.5, 0.01).name('Node Size').onChange(() => {
        centerNode.scale.set(params.nodeSize * 6.67, params.nodeSize * 6.67, params.nodeSize * 6.67);
    });
    nodeFolder.addColor(params, 'nodeColor').name('Node Color').onChange(value => {
        centerNode.material.color.set(value);
        centerNode.material.emissive.set(value);
    });
    
    // Scene controls
    const sceneFolder = gui.addFolder('Scene');
    sceneFolder.addColor(params, 'backgroundColor').name('Background Color').onChange(value => {
        scene.background.set(value);
    });
}

function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}

function animate() {
    requestAnimationFrame(animate);
    
    const time = clock.getElapsedTime();
    const delta = clock.getDelta();
    
    // Process blob interactions and physics
    processInterBlobCollisions();
    
    // Apply physics to blobs
    blobs.forEach((blob, index) => {
        // Skip physics for the currently dragged blob
        if (blob === draggedBlob && isDragging) return;
        
        // Spring physics to return to original position
        const originalPos = blob.userData.originalPosition;
        const currentPos = blob.position;
        
        // Calculate spring force (F = -kx)
        const displacement = new THREE.Vector3().subVectors(currentPos, originalPos);
        const springForce = displacement.clone().multiplyScalar(-params.springStrength);
        
        // Apply spring force to velocity
        blob.userData.velocity = blob.userData.velocity || new THREE.Vector3(0, 0, 0);
        blob.userData.velocity.add(springForce);
        
        // Apply gravity towards center
        const directionToCenter = new THREE.Vector3(0, 0, 0).sub(currentPos).normalize();
        const distanceToCenter = currentPos.length();
        const gravityStrength = 0.01 * (1 / Math.max(0.5, distanceToCenter));
        const gravityForce = directionToCenter.clone().multiplyScalar(gravityStrength);
        blob.userData.velocity.add(gravityForce);
        
        // Apply center void repulsion if too close to center
        const centerVoidRadius = params.centerVoidRadius + params.blobSize;
        if (distanceToCenter < centerVoidRadius) {
            // Strong repulsion force to push blob out of the void
            const repulsionStrength = 0.05 * (centerVoidRadius - distanceToCenter) / centerVoidRadius;
            const repulsionForce = directionToCenter.clone().negate().multiplyScalar(repulsionStrength);
            blob.userData.velocity.add(repulsionForce);
        }
        
        // Apply damping
        blob.userData.velocity.multiplyScalar(params.damping);
        
        // Update position
        blob.position.add(blob.userData.velocity);
        
        // Apply additional ongoing ripple effects to all blobs (commented out as requested)
        if (blob.userData.originalVertices && !blob.userData.isDeformed) {
            applyAmbientRipples(blob, time, index);
        }
        
        // Keep material property animations for subtle effects
        blob.material.reflectivity = materialParams.reflectivity + 
            materialParams.fresnelStrength * 0.3 * Math.sin(time + index);
        blob.material.ior = materialParams.ior + 0.05 * Math.sin(time * 0.4 + index * 0.5);
        blob.material.transmission = materialParams.transmission + 0.05 * Math.sin(time * 0.6 + index * 0.3);
    });
    
    // Check for merge candidate while dragging
    if (isDragging && draggedBlob) {
        checkForMergeCandidate(draggedBlob);
    }
    
    // Update controls (for orbit camera)
    orbitControls.update();
    
    renderer.render(scene, camera);
}

// Process collisions between blobs to simulate physical interactions
function processInterBlobCollisions() {
    // Skip if there are too few blobs
    if (blobs.length < 2) return;
    
    for (let i = 0; i < blobs.length; i++) {
        const blob1 = blobs[i];
        
        // Skip if this is the blob being dragged
        if (blob1 === draggedBlob && isDragging) continue;
        
        for (let j = i + 1; j < blobs.length; j++) {
            const blob2 = blobs[j];
            
            // Skip if this is the blob being dragged
            if (blob2 === draggedBlob && isDragging) continue;
            
            // Calculate distance between blobs
            const distance = blob1.position.distanceTo(blob2.position);
            
            // Calculate minimum distance based on blob sizes and padding
            const minDistance = (blob1.userData.originalSize + blob2.userData.originalSize) * (1 + params.blobPadding);
            
            // If blobs are too close, apply repulsion force
            if (distance < minDistance) {
                // Calculate overlap
                const overlap = minDistance - distance;
                
                // Calculate direction from blob1 to blob2
                const direction = new THREE.Vector3().subVectors(blob2.position, blob1.position).normalize();
                
                // Calculate repulsion force based on overlap
                const repulsionStrength = 0.05 * overlap / minDistance;
                
                // Apply forces in opposite directions
                if (blob1.userData.velocity && !isNaN(repulsionStrength)) {
                    blob1.userData.velocity.sub(direction.clone().multiplyScalar(repulsionStrength));
                }
                
                if (blob2.userData.velocity && !isNaN(repulsionStrength)) {
                    blob2.userData.velocity.add(direction.clone().multiplyScalar(repulsionStrength));
                }
            }
        }
    }
}

function applyAmbientRipples(blob, time, index) {
    // Rippling code is commented out to focus on positioning and padding
    /*
    // Skip if the blob is already deformed by another effect
    if (blob.userData.isDeformed) return;
    
    const positionAttribute = blob.geometry.attributes.position;
    const vertex = new THREE.Vector3();
    
    // Very subtle ambient ripples when not interacting
    const rippleIntensity = 0.01;
    const rippleFrequency = 2.0;
    const rippleSpeed = 1.0;
    
    // Make each blob's ripple slightly different
    const timeOffset = index * 0.5;
    
    for (let i = 0; i < positionAttribute.count; i++) {
        if (!blob.userData.originalVertices) continue;
        
        // Get original vertex
        const originalVertex = blob.userData.originalVertices[i].clone();
        
        // Calculate normal direction
        const normal = originalVertex.clone().normalize();
        
        // Simple ripple effect based on vertex position and time
        const distFromCenter = originalVertex.length();
        const angle = Math.atan2(originalVertex.y, originalVertex.x);
        
        const ripple = rippleIntensity * Math.sin(
            distFromCenter * rippleFrequency + 
            angle * 2 + 
            (time + timeOffset) * rippleSpeed
        );
        
        // Apply ripple along normal direction
        vertex.copy(originalVertex).add(normal.multiplyScalar(ripple * blob.userData.originalSize));
        positionAttribute.setXYZ(i, vertex.x, vertex.y, vertex.z);
    }
    
    positionAttribute.needsUpdate = true;
    */
}

// Helper function to generate positions for blobs in a natural cluster with a center void
function generateClusteredPositions(count, radius, padding) {
    const positions = [];
    const minDistance = params.blobSize * (1 + padding) * 2; // Minimum distance between blob centers
    const centerVoidRadius = params.centerVoidRadius + params.blobSize; // Minimum distance from center
    
    // Try to place blobs with padding
    let attempts = 0;
    const maxAttempts = 2000; // Prevent infinite loops
    
    while (positions.length < count && attempts < maxAttempts) {
        attempts++;
        
        // Generate a random position within the cluster radius
        const theta = Math.random() * Math.PI * 2; // Random angle
        const phi = Math.acos(2 * Math.random() - 1); // Random inclination
        
        // Generate radius between centerVoidRadius and max radius
        // Use a distribution that favors positions closer to the center void
        const minR = centerVoidRadius;
        const maxR = radius;
        const r = minR + (maxR - minR) * Math.pow(Math.random(), 0.5);
        
        const x = r * Math.sin(phi) * Math.cos(theta);
        const y = r * Math.sin(phi) * Math.sin(theta);
        const z = 0; // Keep all blobs on the same z-plane
        
        const newPos = new THREE.Vector3(x, y, z);
        
        // Check if this position is far enough from existing blobs
        let isFarEnough = true;
        
        // Check distance from center (enforce void)
        const distFromCenter = newPos.length();
        if (distFromCenter < centerVoidRadius) {
            isFarEnough = false;
        } else {
            // Check distance from other blobs
            for (const pos of positions) {
                if (pos.distanceTo(newPos) < minDistance) {
                    isFarEnough = false;
                    break;
                }
            }
        }
        
        if (isFarEnough) {
            positions.push(newPos);
        }
    }
    
    // If we couldn't place all blobs with padding, fill the remaining positions
    // with blobs that might overlap with each other (but still respect the center void)
    while (positions.length < count) {
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        
        // Still respect the center void
        const minR = centerVoidRadius;
        const maxR = radius;
        const r = minR + (maxR - minR) * Math.random();
        
        const x = r * Math.sin(phi) * Math.cos(theta);
        const y = r * Math.sin(phi) * Math.sin(theta);
        const z = 0;
        
        const newPos = new THREE.Vector3(x, y, z);
        
        // Only add if it respects the center void
        if (newPos.length() >= centerVoidRadius) {
            positions.push(newPos);
        }
    }
    
    return positions;
}

export { scene, camera, blobs, centerNode, params };
