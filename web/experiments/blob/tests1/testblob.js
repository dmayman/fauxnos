import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RGBELoader } from 'three/examples/jsm/loaders/RGBELoader.js';
import { Blob } from './blob.js';

class TestBlobs {
    constructor() {
        this.initScene();
        this.createBlobs();
        this.animate();
        this.handleResize();
    }

    createGradientTexture(color1, color2) {
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        canvas.width = 1;
        canvas.height = 512;
        
        const gradient = context.createLinearGradient(0, 0, 0, 512);
        gradient.addColorStop(0, color1);
        gradient.addColorStop(1, color2);
        
        context.fillStyle = gradient;
        context.fillRect(0, 0, 1, 512);
        
        const texture = new THREE.CanvasTexture(canvas);
        texture.minFilter = THREE.LinearFilter;
        return texture;
    }

    initScene() {
        // Create scene
        this.scene = new THREE.Scene();
        
        // Create gradient background
        const gradientTexture = this.createGradientTexture('#4f7cd9', '#8f2b63');
        this.scene.background = gradientTexture;
        this.scene.background.encoding = THREE.sRGBEncoding;
        
        // Create renderer first
        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setSize(window.innerWidth, window.innerHeight);
        this.renderer.setPixelRatio(window.devicePixelRatio);
        document.body.appendChild(this.renderer.domElement);
        
        // Now we can create PMREMGenerator
        const pmremGenerator = new THREE.PMREMGenerator(this.renderer);
        pmremGenerator.compileEquirectangularShader();
        
        // Load environment map
        const loader = new RGBELoader();
        loader.load('../public/env/env2.hdr', (texture) => {
            texture.encoding = THREE.sRGBEncoding;
            
            const envMap = pmremGenerator.fromEquirectangular(texture).texture;
            this.scene.environment = envMap;  // This affects reflections on objects
            // Keep the original gradient background
            // this.scene.background = this.createGradientTexture('#0f0fff', '#ff0fff');
            
            // // Update all materials with the new environment map
            // this.scene.traverse((child) => {
            //     if (child.isMesh && child.material) {
            //         child.material.envMap = envMap;
            //         child.material.needsUpdate = true;
            //     }
            // });
            
            // texture.dispose();
        }, undefined, (error) => {
            console.error('Error loading environment map:', error);
        });
        
        // Environment map intensity
        // this.scene.environmentIntensity = 0.5;

        // Create camera
        this.camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
        this.camera.position.z = 10;


        // Add multiple lights for better depth
        // const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
        // this.scene.add(ambientLight);

        // Main key light
        // const keyLight = new THREE.DirectionalLight(0xffffff, 1.2);
        // keyLight.position.set(2, 3, 4);
        // keyLight.castShadow = true;
        // keyLight.shadow.mapSize.width = 2048;
        // keyLight.shadow.mapSize.height = 2048;
        // this.scene.add(keyLight);
        
        // Fill light
        // const fillLight = new THREE.DirectionalLight(0x88ccff, 0.5);
        // fillLight.position.set(-3, -2, -1);
        // this.scene.add(fillLight);
        
        // Back light
        // const backLight = new THREE.DirectionalLight(0xffaa88, 0.6);
        // backLight.position.set(-3, 3, -5);
        // this.scene.add(backLight);

        // Add orbit controls
        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
    }

    createBlobs() {
        this.blobs = [];
        
        // Create 3 blobs with different positions and colors
        const positions = [
            { x: -4, y: 0, z: 0 },
            { x: 4, y: 0, z: 0 },
            { x: 0, y: 4, z: 0 }
        ];
        
        const colors = [
            { color1: '#000000', color2: '#000000', color3: '#000000' },
            { color1: '#000000', color2: '#000000', color3: '#000000' },
            { color1: '#000000', color2: '#000000', color3: '#000000' }
        ];
        
        positions.forEach((pos, index) => {
            const blob = new Blob();
            
            // Customize blob parameters
            Object.assign(blob.params, colors[index % colors.length]);
            blob.params.speed = 1 + Math.random() * 2; // Random speed
            blob.params.distortAmount = 0.1 + Math.random() * 0.2; // Random distortion
            
            // Position the blob
            blob.getMesh().position.set(pos.x, pos.y, pos.z);
            
            // Add to scene and store reference
            this.scene.add(blob.getMesh());
            this.blobs.push(blob);
        });
    }

    // Sort objects back to front for proper transparency
    sortObjects() {
        // Get all transparent objects
        const transparentObjects = [];
        this.scene.traverse((object) => {
            if (object.isMesh && object.material && object.material.transparent) {
                transparentObjects.push(object);
            }
        });

        // Sort by distance from camera (farthest to nearest)
        const cameraPosition = this.camera.position.clone();
        transparentObjects.sort((a, b) => {
            const d1 = a.position.distanceToSquared(cameraPosition);
            const d2 = b.position.distanceToSquared(cameraPosition);
            return d2 - d1;
        });

        // Update render order
        transparentObjects.forEach((obj, i) => {
            obj.renderOrder = i;
        });
    }

    animate() {
        requestAnimationFrame(() => this.animate());
        
        // Update each blob
        this.blobs.forEach(blob => blob.update());
        
        // Sort transparent objects by distance
        // this.sortObjects();
        
        // Update controls
        this.controls.update();
        
        // Ensure the renderer sorts objects by depth
        // this.renderer.sortObjects = true;
        
        // Render scene
        this.renderer.render(this.scene, this.camera);
    }

    handleResize() {
        window.addEventListener('resize', () => {
            this.camera.aspect = window.innerWidth / window.innerHeight;
            this.camera.updateProjectionMatrix();
            this.renderer.setSize(window.innerWidth, window.innerHeight);
        });
    }
}

// Initialize the test
new TestBlobs();
