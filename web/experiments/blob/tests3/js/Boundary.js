import * as THREE from 'three';
import * as CANNON from 'cannon-es';

export class Boundary {
    constructor(type, position, size, params, world, scene) {
        this.type = type;
        this.size = size;
        this.params = params;
        this.world = world;
        this.scene = scene;
        
        this.initPhysics(position);
        this.initVisuals();
    }

    initPhysics(position) {
        let shape;
        
        // Create different shapes based on boundary type
        switch (this.type) {
            case 'floor':
                shape = new CANNON.Plane();
                this.body = new CANNON.Body({
                    mass: 0, // Static body
                    shape: shape,
                    position: new CANNON.Vec3(position.x, position.y, position.z),
                    quaternion: new CANNON.Quaternion().setFromAxisAngle(
                        new CANNON.Vec3(1, 0, 0), -Math.PI / 2
                    ),
                    collisionFilterGroup: this.params.collisionGroups.BOUNDARY,
                    collisionFilterMask: -1, // Collide with everything
                    material: this.params.physicsMaterial
                });
                break;
                
            case 'wall':
                shape = new CANNON.Box(new CANNON.Vec3(
                    this.size.width / 2,
                    this.size.height / 2,
                    this.size.depth / 2
                ));
                this.body = new CANNON.Body({
                    mass: 0, // Static body
                    shape: shape,
                    position: new CANNON.Vec3(position.x, position.y, position.z),
                    collisionFilterGroup: this.params.collisionGroups.BOUNDARY,
                    collisionFilterMask: -1, // Collide with everything
                    material: this.params.physicsMaterial
                });
                break;
        }

        this.world.addBody(this.body);
    }

    initVisuals() {
        switch (this.type) {
            case 'floor':
                const floorGeometry = new THREE.PlaneGeometry(100, 100);
                const floorMaterial = new THREE.MeshStandardMaterial({
                    color: 0x444444,
                    side: THREE.DoubleSide,
                    roughness: 0.8,
                    metalness: 0.2
                });
                this.mesh = new THREE.Mesh(floorGeometry, floorMaterial);
                this.mesh.rotation.x = -Math.PI / 2;
                this.mesh.receiveShadow = true;
                break;
                
            case 'wall':
                const wallGeometry = new THREE.BoxGeometry(
                    this.size.width,
                    this.size.height,
                    this.size.depth
                );
                const wallMaterial = new THREE.MeshStandardMaterial({
                    color: 0x333333,
                    transparent: true,
                    opacity: 0.8,
                    wireframe: true
                });
                this.mesh = new THREE.Mesh(wallGeometry, wallMaterial);
                break;
        }
        
        this.mesh.position.copy(this.body.position);
        this.mesh.quaternion.copy(this.body.quaternion);
        this.scene.add(this.mesh);
    }

    update(deltaTime) {
        // Update visual representation if needed
        this.mesh.position.copy(this.body.position);
        this.mesh.quaternion.copy(this.body.quaternion);
    }

    dispose() {
        this.world.removeBody(this.body);
        this.scene.remove(this.mesh);
        this.mesh.geometry.dispose();
        this.mesh.material.dispose();
    }
}
