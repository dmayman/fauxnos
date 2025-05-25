import * as THREE from 'three';
import * as CANNON from 'cannon-es';

export class Blob {
    constructor(radius, position, params, world, scene) {
        this.radius = radius;
        this.params = params;
        this.world = world;
        this.scene = scene;
        this.isDragged = false;
        this.isInCenter = false;
        
        this.initPhysics(position);
        this.initVisuals();
    }

    initPhysics(position) {
        // Create physics body with original properties
        this.body = new CANNON.Body({
            mass: 1,
            shape: new CANNON.Sphere(this.radius),
            position: new CANNON.Vec3(position.x, position.y, position.z),
            collisionResponse: true,
            collisionFilterGroup: this.params.collisionGroups.BLOBS,
            collisionFilterMask: this.params.collisionGroups.BLOBS | 
                              this.params.collisionGroups.CENTER | 
                              this.params.collisionGroups.BOUNDARY |
                              this.params.collisionGroups.DRAGGED,
            material: this.params.physicsMaterial
        });

        // Match original physics properties
        this.body.linearDamping = 0.3;
        this.body.angularDamping = 0.3;
        this.body.linearSleepingThreshold = 0.5;
        this.body.angularSleepingThreshold = 0.5;
        this.body.updateMassProperties();

        // Add to world
        this.world.addBody(this.body);
    }


    initVisuals() {
        // Create mesh
        const geometry = new THREE.SphereGeometry(this.radius, 32, 32);
        const material = new THREE.MeshStandardMaterial({
            color: new THREE.Color().setHSL(Math.random(), 0.7, 0.5),
            roughness: 0.5,
            metalness: 0.2,
        });
        
        this.mesh = new THREE.Mesh(geometry, material);
        this.scene.add(this.mesh);
        
        // Initial sync
        this.updateVisuals();
    }

    setDragged(isDragged) {
        this.isDragged = isDragged;
        
        // Update physics properties when dragged
        if (isDragged) {
            this.body.collisionFilterGroup = this.params.collisionGroups.DRAGGED;
            this.body.collisionFilterMask = this.params.collisionGroups.BLOBS | 
                                         this.params.collisionGroups.BOUNDARY | 
                                         this.params.collisionGroups.DRAGGED;
        } else {
            this.body.collisionFilterGroup = this.params.collisionGroups.BLOBS;
            this.body.collisionFilterMask = this.params.collisionGroups.BLOBS | 
                                         this.params.collisionGroups.CENTER | 
                                         this.params.collisionGroups.BOUNDARY | 
                                         this.params.collisionGroups.DRAGGED;
        }
    }

    setPosition(x, y, z) {
        this.body.position.set(x, y, z);
        this.body.velocity.set(0, 0, 0);
        this.body.angularVelocity.set(0, 0, 0);
        this.body.force.set(0, 0, 0);
        this.body.torque.set(0, 0, 0);
    }


    updateVisuals() {
        // Sync physics body with visual mesh
        this.mesh.position.copy(this.body.position);
        this.mesh.quaternion.copy(this.body.quaternion);
        
        // Visual feedback for dragging
        const targetScale = this.isDragged ? this.params.activeScale : 1.0;
        this.mesh.scale.lerp(
            new THREE.Vector3(targetScale, targetScale, targetScale),
            0.1
        );
    }

    update(deltaTime) {
        if (!this.isDragged) {
            // Apply any continuous physics here
        }
        this.updateVisuals();
    }

    dispose() {
        // Cleanup
        this.world.removeBody(this.body);
        this.scene.remove(this.mesh);
        this.mesh.geometry.dispose();
        this.mesh.material.dispose();
    }
}
