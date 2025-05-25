import * as THREE from 'three';

export class Blob {
    constructor() {
        // Default parameters
        this.params = {
            color1: '#be62df',
            color2: '#628fea',
            color3: '#a47f98',
            roughness: 0,
            metalness: 0,
            clearcoat: 1,
            clearcoatRoughness: 0,
            transmission: 1,
            reflectivity: 1,
            ior: 1.5,
            envMapIntensity: 1.25,
            iridescence: 1,
            iridescenceIOR: 1.3,
            iridescenceThicknessRange: [100, 400],
            speed: 2,
            distortAmount: 0.18,
            fresnelStrength: 1,
            bulgeAmount: 0.9,
            envMapRotation: 90
        };

        this.clock = new THREE.Clock();
        this.mesh = this.createBlob();
    }

    createBlob() {
        // Create geometry
        const geometry = new THREE.IcosahedronGeometry(1.04, 6);
        
        // Create material with settings from the example
        const material = new THREE.MeshPhysicalMaterial({
            color: 0xffffff,
            roughness: 0.1,
            metalness: 0,
            clearcoat: 1.0,
            clearcoatRoughness: 0.1,
            transmission: 0.9,  // Slightly reduced for better visibility
            thickness: -.15,
            ior: 2,  // Slightly higher IOR
            transparent: true,
            opacity: 0.8,
            depthWrite: false,
            depthTest: true,
            side: THREE.DoubleSide,  // Changed to DoubleSide
            envMapIntensity: 0.1,
            premultipliedAlpha: true,
            blending: THREE.NormalBlending
        });
        
        // Apply parameters to material
        this.updateMaterial(material);
        
        // Create mesh
        const blob = new THREE.Mesh(geometry, material);
        blob.position.z = 0.05;
        
        // Store reference to geometry for animation
        this.geometry = geometry;
        
        return blob;
    }
    
    updateMaterial(material) {
        // Apply all material properties from params
        Object.entries(this.params).forEach(([key, value]) => {
            if (key in material) {
                material[key] = value;
            }
        });
        material.needsUpdate = true;
    }
    
    update() {
        const time = this.clock.getElapsedTime();
        const positionAttribute = this.geometry.attributes.position;
        const vertex = new THREE.Vector3();
        
        for (let i = 0; i < positionAttribute.count; i++) {
            vertex.fromBufferAttribute(positionAttribute, i);
            const waveFreq = 3.0;
            const rippleSpeed = this.params.speed * 0.5;
            const rippleDepth = 0.04;
            
            // Create concentric ripples
            const distFromCenter = Math.sqrt(vertex.x * vertex.x + vertex.y * vertex.y);
            const ripple = rippleDepth * Math.sin(distFromCenter * waveFreq - time * rippleSpeed);
            
            // Combine with existing waves
            const wave = 0.12 * Math.sin(vertex.x * 2 + time * this.params.speed) + 
                         0.12 * Math.cos(vertex.y * 2 + time * this.params.speed) + 
                         ripple;
            
            vertex.normalize().multiplyScalar(1 + wave * this.params.distortAmount + this.params.bulgeAmount);
            positionAttribute.setXYZ(i, vertex.x, vertex.y, vertex.z);
        }
        
        positionAttribute.needsUpdate = true;
        
        // Update material properties that change over time
        if (this.mesh.material) {
            this.mesh.material.reflectivity = this.params.reflectivity + 
                this.params.fresnelStrength * Math.abs(Math.sin(time));
            this.mesh.material.ior = this.params.ior + 0.05 * Math.sin(time * 0.4);
            this.mesh.material.transmission = this.params.transmission + 0.01 * Math.sin(time * 0.6);
            this.mesh.material.iridescenceIOR = this.params.iridescenceIOR + 0.2 * Math.sin(time * 0.8);
        }
    }
    
    getMesh() {
        return this.mesh;
    }
    
    setSize(width, height) {
        // Optional: Handle resizing if needed
        // This can be expanded to handle responsive behavior
    }
    
    dispose() {
        if (this.geometry) {
            this.geometry.dispose();
        }
        if (this.mesh.material) {
            this.mesh.material.dispose();
        }
    }
}
