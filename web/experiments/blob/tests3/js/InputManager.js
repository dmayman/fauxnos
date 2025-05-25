import * as THREE from 'three';

export class InputManager {
    constructor(renderer, camera, scene, world, params, onBlobDropped) {
        this.renderer = renderer;
        this.camera = camera;
        this.scene = scene;
        this.world = world;
        this.params = params;
        this.onBlobDropped = onBlobDropped;
        
        this.raycaster = new THREE.Raycaster();
        this.mouse = new THREE.Vector2();
        this.plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
        
        // Dragging state
        this.draggedBlob = null;
        this.isDragging = false;
        
        // Bind methods
        this.onPointerDown = this.onPointerDown.bind(this);
        this.onPointerMove = this.onPointerMove.bind(this);
        this.onPointerUp = this.onPointerUp.bind(this);
        
        // Add event listeners
        this.addEventListeners();
    }
    
    addEventListeners() {
        this.renderer.domElement.addEventListener('pointerdown', this.onPointerDown);
        this.renderer.domElement.addEventListener('pointermove', this.onPointerMove);
        this.renderer.domElement.addEventListener('pointerup', this.onPointerUp);
        this.renderer.domElement.addEventListener('pointerleave', this.onPointerUp);
    }
    
    removeEventListeners() {
        this.renderer.domElement.removeEventListener('pointerdown', this.onPointerDown);
        this.renderer.domElement.removeEventListener('pointermove', this.onPointerMove);
        this.renderer.domElement.removeEventListener('pointerup', this.onPointerUp);
        this.renderer.domElement.removeEventListener('pointerleave', this.onPointerUp);
    }
    
    getIntersectedObjects() {
        this.raycaster.setFromCamera(this.mouse, this.camera);
        return this.raycaster.intersectObjects(this.scene.children, true);
    }
    
    getIntersectionPoint() {
        this.raycaster.setFromCamera(this.mouse, this.camera);
        const intersects = this.raycaster.ray.intersectPlane(
            this.plane,
            new THREE.Vector3()
        );
        return intersects || null;
    }
    
    onPointerDown(event) {
        if (this.isDragging) return;
        
        const rect = this.renderer.domElement.getBoundingClientRect();
        this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        
        const intersects = this.getIntersectedObjects();
        
        if (intersects.length > 0) {
            // Find the blob that was clicked
            for (const intersect of intersects) {
                const blob = this.params.blobs.find(b => b.mesh === intersect.object);
                if (blob) {
                    this.draggedBlob = blob;
                    this.isDragging = true;
                    
                    // Set blob as dragged
                    blob.setDragged(true);
                    
                    // Move blob to pointer position
                    const intersection = this.getIntersectionPoint();
                    if (intersection) {
                        blob.setPosition(intersection.x, intersection.y, 5); // Slightly above the plane
                    }
                    
                    // Disable orbit controls if they exist
                    if (this.params.controls) {
                        this.params.controls.enabled = false;
                    }
                    
                    break;
                }
            }
        }
    }
    
    onPointerMove(event) {
        if (!this.isDragging || !this.draggedBlob) return;
        
        const rect = this.renderer.domElement.getBoundingClientRect();
        this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        
        const intersection = this.getIntersectionPoint();
        if (intersection) {
            // Match original behavior: maintain z=5 while dragging
            this.draggedBlob.setPosition(intersection.x, intersection.y, 5);
            
            // Check if we've moved away from center
            const distToCenter = Math.sqrt(
                this.draggedBlob.body.position.x * this.draggedBlob.body.position.x +
                this.draggedBlob.body.position.z * this.draggedBlob.body.position.z
            );
            
            // If moved away from center, update collision filters
            if (distToCenter > this.params.dropZoneRadius * 0.8) {
                this.draggedBlob.body.collisionFilterGroup = this.params.collisionGroups.BLOBS;
                this.draggedBlob.body.collisionFilterMask = 
                    this.params.collisionGroups.BLOBS | 
                    this.params.collisionGroups.BOUNDARY | 
                    this.params.collisionGroups.DRAGGED;
            }
        }
    }
    
    onPointerUp(event) {
        if (!this.isDragging || !this.draggedBlob) return;
        
        // Reset blob state
        this.draggedBlob.setDragged(false);
        
        // Re-enable orbit controls if they exist
        if (this.params.controls) {
            this.params.controls.enabled = true;
        }
        
        // Notify about the drop
        if (this.onBlobDropped) {
            const rect = this.renderer.domElement.getBoundingClientRect();
            this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
            this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
            
            const intersection = this.getIntersectionPoint();
            if (intersection) {
                this.onBlobDropped(this.draggedBlob, intersection);
            }
        }
        
        // Reset dragging state
        this.draggedBlob = null;
        this.isDragging = false;
    }
    
    dispose() {
        this.removeEventListeners();
    }
}
