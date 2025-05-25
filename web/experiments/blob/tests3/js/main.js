import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import * as CANNON from 'cannon-es';
import { Blob } from './Blob.js';
import { Boundary } from './Boundary.js';
import { InputManager } from './InputManager.js';

class BlobApp {
    constructor() {
        this.initThree();
        this.initPhysics();
        this.initScene();
        this.initLights();
        this.initBoundaries();
        this.initBlobs();
        this.initControls();
        this.initInput();
        this.animate();
    }

    initThree() {
        // Create renderer
        this.renderer = new THREE.WebGLRenderer({ antialias: true });
        this.renderer.setSize(window.innerWidth, window.innerHeight);
        this.renderer.shadowMap.enabled = true;
        document.body.appendChild(this.renderer.domElement);

        // Create camera
        this.camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
        this.camera.position.set(0, 10, 20);
        this.camera.lookAt(0, 0, 0);

        // Create scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x111111);

        // Handle window resize
        window.addEventListener('resize', () => this.onWindowResize());
    }

    initPhysics() {
        // Create physics world
        this.world = new CANNON.World({
            gravity: new CANNON.Vec3(0, -9.82, 0),
        });
        
        // Match original physics settings
        this.world.broadphase = new CANNON.NaiveBroadphase();
        this.world.solver.iterations = 10;

        // Create default material with original properties
        this.physicsMaterial = new CANNON.Material('default');
        const defaultContactMaterial = new CANNON.ContactMaterial(
            this.physicsMaterial,
            this.physicsMaterial,
            {
                friction: 0.1,
                restitution: 0.7,
            }
        );
        this.world.addContactMaterial(defaultContactMaterial);
        this.world.defaultContactMaterial = defaultContactMaterial;

        // Collision groups
        this.collisionGroups = {
            BLOBS: 1,
            CENTER: 2,
            DRAGGED: 4,
            BOUNDARY: 8
        };
    }

    initScene() {
        // Add grid helper
        const gridHelper = new THREE.GridHelper(100, 100);
        this.scene.add(gridHelper);

        // Add coordinate axes
        const axesHelper = new THREE.AxesHelper(5);
        this.scene.add(axesHelper);
    }

    initLights() {
        // Ambient light
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
        this.scene.add(ambientLight);

        // Directional light
        const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
        directionalLight.position.set(10, 20, 10);
        directionalLight.castShadow = true;
        directionalLight.shadow.mapSize.width = 2048;
        directionalLight.shadow.mapSize.height = 2048;
        this.scene.add(directionalLight);
    }

    initBoundaries() {
        this.boundaries = [];
        
        // Floor
        const floor = new Boundary(
            'floor',
            { x: 0, y: -1, z: 0 },
            { width: 100, height: 0.1, depth: 100 },
            {
                physicsMaterial: this.physicsMaterial,
                collisionGroups: this.collisionGroups
            },
            this.world,
            this.scene
        );
        this.boundaries.push(floor);
        
        // Walls
        const wallSize = 20;
        const wallThickness = 0.5;
        const wallHeight = 10;
        
        // Left wall
        const leftWall = new Boundary(
            'wall',
            { x: -wallSize/2, y: wallHeight/2, z: 0 },
            { width: wallThickness, height: wallHeight, depth: wallSize },
            {
                physicsMaterial: this.physicsMaterial,
                collisionGroups: this.collisionGroups
            },
            this.world,
            this.scene
        );
        this.boundaries.push(leftWall);
        
        // Right wall
        const rightWall = new Boundary(
            'wall',
            { x: wallSize/2, y: wallHeight/2, z: 0 },
            { width: wallThickness, height: wallHeight, depth: wallSize },
            {
                physicsMaterial: this.physicsMaterial,
                collisionGroups: this.collisionGroups
            },
            this.world,
            this.scene
        );
        this.boundaries.push(rightWall);
        
        // Back wall
        const backWall = new Boundary(
            'wall',
            { x: 0, y: wallHeight/2, z: -wallSize/2 },
            { width: wallSize, height: wallHeight, depth: wallThickness },
            {
                physicsMaterial: this.physicsMaterial,
                collisionGroups: this.collisionGroups
            },
            this.world,
            this.scene
        );
        this.boundaries.push(backWall);
    }

    initBlobs() {
        this.blobs = [];
        this.centerBlobIndices = [];
        const radius = 1;
        const count = 10;
        const angleStep = (Math.PI * 2) / count;
        const distance = 5;

        // Create blobs in a circular pattern to match original
        for (let i = 0; i < count; i++) {
            const angle = i * angleStep;
            const x = Math.cos(angle) * distance;
            const z = Math.sin(angle) * distance;
            const y = 10 + Math.random() * 5; // Random height within range
            
            const blob = new Blob(
                radius,
                { x, y, z },
                {
                    physicsMaterial: this.physicsMaterial,
                    collisionGroups: this.collisionGroups,
                    activeScale: 1.2
                },
                this.world,
                this.scene
            );
            
            this.blobs.push(blob);
        }
    }

    initControls() {
        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.05;
    }

    initInput() {
        this.inputManager = new InputManager(
            this.renderer,
            this.camera,
            this.scene,
            this.world,
            {
                blobs: this.blobs,
                controls: this.controls,
                collisionGroups: this.collisionGroups,
                dropZoneRadius: 5
            },
            (blob, position) => this.onBlobDropped(blob, position)
        );
    }

    onBlobDropped(blob, position) {
        // Check if blob was dropped in the center zone
        const distanceToCenter = Math.sqrt(position.x * position.x + position.z * position.z);
        
        if (distanceToCenter < this.params.dropZoneRadius) {
            // If dropped in center, snap to center and make static
            blob.setPosition(0, 0, 0);
            blob.body.velocity.set(0, 0, 0);
            blob.body.angularVelocity.set(0, 0, 0);
            
            // Update collision filters for center blobs
            blob.body.collisionFilterGroup = this.collisionGroups.CENTER;
            blob.body.collisionFilterMask = this.collisionGroups.BLOBS | 
                                         this.collisionGroups.BOUNDARY | 
                                         this.collisionGroups.DRAGGED;
            
            // Add to center blobs array if not already present
            if (!this.centerBlobIndices) this.centerBlobIndices = [];
            const index = this.blobs.indexOf(blob);
            if (index !== -1 && !this.centerBlobIndices.includes(index)) {
                this.centerBlobIndices.push(index);
            }
        } else {
            // If dropped outside, ensure it's treated as a regular blob
            blob.body.collisionFilterGroup = this.collisionGroups.BLOBS;
            blob.body.collisionFilterMask = this.collisionGroups.BLOBS | 
                                         this.collisionGroups.CENTER | 
                                         this.collisionGroups.BOUNDARY | 
                                         this.collisionGroups.DRAGGED;
        }
    }

    onWindowResize() {
        this.camera.aspect = window.innerWidth / window.innerHeight;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(window.innerWidth, window.innerHeight);
    }

    updatePhysics(deltaTime) {
        // Step the physics world
        this.world.step(1/60, deltaTime, 3);
    }

    update(deltaTime) {
        // Update controls
        this.controls.update();
        
        // Update physics
        this.updatePhysics(deltaTime);
        
        // Update blobs
        for (const blob of this.blobs) {
            blob.update(deltaTime);
        }
        
        // Update boundaries
        for (const boundary of this.boundaries) {
            boundary.update(deltaTime);
        }
    }

    render() {
        this.renderer.render(this.scene, this.camera);
    }

    animate() {
        const clock = new THREE.Clock();
        const animateLoop = () => {
            requestAnimationFrame(animateLoop);
            
            const deltaTime = Math.min(clock.getDelta(), 0.1);
            
            this.update(deltaTime);
            this.render();
        };
        
        animateLoop();
    }

    dispose() {
        // Clean up resources
        this.inputManager.dispose();
        
        for (const blob of this.blobs) {
            blob.dispose();
        }
        
        for (const boundary of this.boundaries) {
            boundary.dispose();
        }
        
        this.renderer.dispose();
        
        // Remove event listeners
        window.removeEventListener('resize', this.onWindowResize);
    }
}

// Start the application
const app = new BlobApp();

// For debugging
window.app = app;
