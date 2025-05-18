

import * as THREE from 'three';

class Blob {
  constructor(size, position, velocity, acceleration, attractor, params = {}) {
    const {
      damping = 0.1,
      hitAreaScale = 1.0,  // Scale factor for hit area relative to visual size
      velocityThreshold = 0.02,  // Minimum velocity before considering the blob at rest
      collisionObjects = []  // Objects to check for collisions with
    } = params;
    
    this.visualSize = size;  // Visual size (rendered size)
    this.hitAreaScale = hitAreaScale;
    this.hitAreaSize = size * hitAreaScale;  // Size used for collision detection
    this.size = this.hitAreaSize;  // Use hitAreaSize for collision detection
    this.position = position.clone();
    this.velocity = velocity.clone();
    this.acceleration = acceleration.clone();
    this.attractor = attractor.clone();
    this.collisionObjects = [...collisionObjects]; // Store a copy of the initial array
    this.damping = damping;
    this.mass = size * size * size; // Mass based on volume
    this.restitution = 0.7; // Bounciness (0-1)
    this.maxSpeed = 5.0;
    this.maxForce = 5.0;
    this.velocityThreshold = velocityThreshold;  // Minimum velocity before coming to rest

    // Create mesh with size and random color
    this.mesh = new THREE.Mesh(
      new THREE.SphereGeometry(this.visualSize, 16, 16),
      new THREE.MeshStandardMaterial({ 
        color: new THREE.Color().setHSL(Math.random(), 0.7, 0.6),
        roughness: 0.3,
        metalness: 0.1
      })
    );
    this.mesh.position.copy(this.position);
    this.mesh.castShadow = true;
    this.mesh.receiveShadow = true;
  }

  applyForce(force) {
    // F=ma, but since we assume mass=1 for now, F=a
    this.acceleration.add(force);
  }

  update(deltaTime = 1/60) {
    // Apply attraction force
    this.applyAttraction();
    
    // Update velocity with acceleration and damping
    this.velocity.add(this.acceleration.multiplyScalar(deltaTime));
    
    // Apply damping (continuous, not just on collision)
    this.velocity.multiplyScalar(1 - this.damping * deltaTime * 60);
    
    // If velocity is very small, set to zero to prevent micro-vibrations
    if (this.velocity.lengthSq() < this.velocityThreshold * this.velocityThreshold) {
      this.velocity.set(0, 0, 0);
    }
    // Limit speed if above threshold
    else if (this.velocity.lengthSq() > this.maxSpeed * this.maxSpeed) {
      this.velocity.normalize().multiplyScalar(this.maxSpeed);
    }
    
    // Update position
    this.position.add(this.velocity.clone().multiplyScalar(deltaTime * 60));
    
    // Keep z constant
    this.position.z = 0;
    
    // Reset acceleration
    this.acceleration.set(0, 0, 0);
    
    // Update mesh position
    this.mesh.position.copy(this.position);
  }
  
  applyAttraction() {
    const direction = new THREE.Vector3().subVectors(this.attractor, this.position);
    const distanceSq = direction.lengthSq();
    const minDistance = 0.1; // Avoid division by zero
    
    if (distanceSq > 0) {
      direction.normalize();
      
      // Constant force
      const forceMagnitude = this.maxForce;
      
      // Apply force
      this.applyForce(direction.multiplyScalar(forceMagnitude));
    }
  }
  
  // Add an object to the collision detection list
  addCollisionObject(obj) {
    if (!this.collisionObjects.includes(obj)) {
      this.collisionObjects.push(obj);
    }
    return this; // Allow method chaining
  }
  
  // Remove an object from the collision detection list
  removeCollisionObject(obj) {
    const index = this.collisionObjects.indexOf(obj);
    if (index > -1) {
      this.collisionObjects.splice(index, 1);
    }
    return this; // Allow method chaining
  }
  
  // Clear all collision objects
  clearCollisionObjects() {
    this.collisionObjects = [];
    return this; // Allow method chaining
  }
  
  // Get all collision objects
  getCollisionObjects() {
    return [...this.collisionObjects]; // Return a copy of the array
  }
  
  // Handle collision with another object
  handleCollision(other) {
    // Skip if other object is invalid or missing required properties
    if (!other || !other.position || typeof other.size === 'undefined') {
      return;
    }
    
    const direction = new THREE.Vector3().subVectors(this.position, other.position);
    const distance = direction.length();
    const minDistance = this.size + other.size;
    
    if (distance < minDistance && distance > 0) {
      // Calculate collision normal
      const normal = direction.normalize();
      
      // Calculate relative velocity
      const relativeVelocity = new THREE.Vector3().subVectors(
          this.velocity, 
          other.velocity
      );
      
      // Calculate impulse
      const velocityAlongNormal = relativeVelocity.dot(normal);
      
      // Only resolve if objects are moving towards each other
      if (velocityAlongNormal < 0) {
        // Calculate restitution (bounciness)
        const e = Math.min(this.restitution, other.restitution);
        
        // Calculate impulse scalar
        const j = -(1 + e) * velocityAlongNormal;
        
        // Apply impulse
        const impulse = normal.clone().multiplyScalar(j);
        this.velocity.add(impulse);
        
        // Separate the objects to prevent sticking
        const correction = normal.clone().multiplyScalar((minDistance - distance) * 0.5);
        this.position.add(correction);
        other.position.sub(correction);
      }
    }
  }
}

class BlobGenerator {
  constructor(scene, params = {}) {
    this.scene = scene;
    this.params = {
      numBlobs: 15,
      minSize: 0.3,
      maxSize: 1.5,
      worldSize: 20,
      damping: 0.1,          // Default damping value
      hitAreaScale: 1.0,     // Default hit area scale (1.0 = same as visual size)
      dropzone: null,        // Optional dropzone object
      ...params
    };
    
    this.blobs = [];
    this.attractor = new THREE.Vector3(0, 0, 0);
    this.lastTime = 0;
    this.fixedTimeStep = 1 / 60; // 60 FPS physics
    this.accumulator = 0;
    
    // Add dropzone to collision objects if it exists
    if (this.params.dropzone) {
      this.dropzone = this.params.dropzone;
    }
  }

  generateBlobs() {
    // Clear existing blobs
    this.clearBlobs();
    
    // Generate new blobs
    for (let i = 0; i < this.params.numBlobs; i++) {
      const size = this.params.minSize + Math.random() * (this.params.maxSize - this.params.minSize);
      const angle = Math.random() * Math.PI * 2;
      const radius = 5 + Math.random() * 10;
      
      const position = new THREE.Vector3(
        Math.cos(angle) * radius,
        Math.sin(angle) * radius,
        0
      );
      
      const velocity = new THREE.Vector3(
        (Math.random() - 0.5) * 2,
        (Math.random() - 0.5) * 2,
        0
      );
      
      // Create collision objects array with existing blobs
      const collisionObjects = [...this.blobs];
      
      // Add dropzone to collision objects if it exists
      if (this.dropzone) {
        collisionObjects.push(this.dropzone);
      }
      
      // Create new blob with collision objects
      const blob = new Blob(
        size,
        position,
        velocity,
        new THREE.Vector3(),
        this.attractor,
        {
          damping: this.params.damping,
          hitAreaScale: this.params.hitAreaScale,
          collisionObjects: collisionObjects
        }
      );
      
      // Add the new blob to collision lists of existing blobs and dropzone
      this.blobs.forEach(existingBlob => {
        existingBlob.addCollisionObject(blob);
        blob.addCollisionObject(existingBlob);
      });
      
      // Add blob to dropzone's collision list if it exists
      if (this.dropzone) {
        blob.addCollisionObject(this.dropzone);
      }
      
      this.blobs.push(blob);
      this.scene.add(blob.mesh);
    }
  }
  
  clearBlobs() {
    // Clear all collision references and remove meshes
    for (const blob of this.blobs) {
      if (blob.mesh) {
        this.scene.remove(blob.mesh);
      }
      if (blob.clearCollisionObjects) {
        blob.clearCollisionObjects();
      }
    }
    this.blobs = [];
  }
  
  update(currentTime = 0) {
    // Calculate delta time in seconds
    if (this.lastTime === 0) this.lastTime = currentTime;
    let deltaTime = (currentTime - this.lastTime) / 1000;
    this.lastTime = currentTime;
    
    // Cap delta time to avoid the "spiral of death"
    deltaTime = Math.min(deltaTime, 0.1);
    
    // Fixed timestep physics
    this.accumulator += deltaTime;
    
    while (this.accumulator >= this.fixedTimeStep) {
      // Update physics
      for (const blob of this.blobs) {
        blob.update(this.fixedTimeStep);
      }
      
      // Handle collisions - each blob checks its own collision objects
      for (const blob of this.blobs) {
        if (!blob || !blob.getCollisionObjects) continue;
        
        const collisionObjects = blob.getCollisionObjects();
        if (!Array.isArray(collisionObjects)) continue;
        
        for (const obj of collisionObjects) {
          // Skip if the object is the blob itself or invalid
          if (!obj || obj === blob) continue;
          
          try {
            blob.handleCollision(obj);
          } catch (error) {
            console.warn('Error in collision handling:', error);
          }
        }
      }
      
      this.accumulator -= this.fixedTimeStep;
    }
    
    // Update attractor position (could be animated)
    // this.attractor.x = Math.sin(currentTime * 0.001) * 5;
    // this.attractor.y = Math.cos(currentTime * 0.001) * 5;
  }
}

export { Blob, BlobGenerator };