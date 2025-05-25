// Blob Mixer recreation in Three.js
// Based on parameters from: https://blobmixer.14islands.com/view?ambient=0.08&angle1=0.88&angle2=1.57&angle3=1.17&bloom=1.47&ccRougness=1&clearColor=%23fdb38a&clearcoat=0&color=%23383838&color1=%23ffffff&color2=%23ffffff&color3=%23ffffff&decay1=0&decay2=0&decay3=0&dist1=20&dist2=20&dist3=11.8&distort=0.18&dynEnv=false&envMap=2&flatShading=false&frequency=1.37&glitch=true&gradient=white&int1=5&int2=1.5&int3=4.2&lights[0]=1&lights[1]=2&lights[2]=3&metalness=0&noise=0.24&numWaves=2.13&penum3=0.69&pp=false&roughness=0&rshad=false&rx=0.03&ry=-1.44&scale=1.01&segments=512&shadow1=false&shadowMap=false&speed=3&surfPoleAmount=1&surfaceDistort=0.83&surfaceFrequency=0.48&surfaceSpeed=1&surfacespeed=1&transmission=1&useGradient=true&uv=true&wireframe=false&x1=4.13&x2=-7.67&x3=10&y1=-4.07&y2=-7.67&y3=7.47&z2=-3.53&z3=-0.53

// Import Three.js and dependencies
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { GlitchPass } from 'three/examples/jsm/postprocessing/GlitchPass.js';
import { ShaderMaterial } from 'three';

// Parse URL parameters
const params = {
  // Scene
  clearColor: '#fdb38a',
  
  // Blob
  color: '#383838',
  scale: 1.01,
  segments: 512,
  wireframe: false,
  flatShading: false,
  
  // Surface wave settings
  surfaceDistort: 0.83,
  surfaceFrequency: 0.48,
  surfaceSpeed: 1,
  surfPoleAmount: 1,
  
  // Distortion 
  distort: 0.18,
  frequency: 1.37,
  numWaves: 2.13,
  speed: 3,
  noise: 0.24,
  
  // Material properties
  metalness: 0,
  roughness: 0,
  transmission: 1,
  clearcoat: 0,
  ccRougness: 1,
  
  // Rotations
  rx: 0.03,
  ry: -1.44,
  
  // UV
  uv: true,
  
  // Environment
  envMap: 2,
  dynEnv: false,
  useGradient: true,
  gradient: 'white',
  
  // Bloom effect
  bloom: 1.47,
  
  // Glitch effect
  glitch: true,
  
  // Lights
  ambient: 0.08,
  lights: [1, 2, 3],
  
  // Light 1
  angle1: 0.88,
  decay1: 0,
  dist1: 20,
  int1: 5,
  x1: 4.13,
  y1: -4.07,
  color1: '#ffffff',
  shadow1: false,
  
  // Light 2
  angle2: 1.57,
  decay2: 0,
  dist2: 20,
  int2: 1.5,
  x2: -7.67,
  y2: -7.67,
  z2: -3.53,
  color2: '#ffffff',
  
  // Light 3
  angle3: 1.17,
  decay3: 0,
  dist3: 11.8,
  int3: 4.2,
  penum3: 0.69,
  x3: 10,
  y3: 7.47,
  z3: -0.53,
  color3: '#ffffff'
};

// Initialize scene
const scene = new THREE.Scene();
scene.background = new THREE.Color(params.clearColor);

// Initialize camera
const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
camera.position.z = 5;

// Initialize renderer
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);
document.body.appendChild(renderer.domElement);

// Create and configure environment map
let envMap;
if (params.envMap === 2) {
  const pmremGenerator = new THREE.PMREMGenerator(renderer);
  pmremGenerator.compileEquirectangularShader();
  
  const cubeTextureLoader = new THREE.CubeTextureLoader();
  cubeTextureLoader.setPath('../public/env/env1/');
  
  const cubeTexture = cubeTextureLoader.load([
    'px.png', 'nx.png',
    'py.png', 'ny.png',
    'pz.png', 'nz.png'
  ]);
  
  envMap = pmremGenerator.fromCubemap(cubeTexture).texture;
  pmremGenerator.dispose();
}

// Create blob material
// We'll need to create a custom shader for the blob material
const blobMaterial = new THREE.MeshPhysicalMaterial({
  color: new THREE.Color(params.color),
  metalness: params.metalness,
  roughness: params.roughness,
  transmission: params.transmission,
  clearcoat: params.clearcoat,
  clearcoatRoughness: params.ccRougness,
  wireframe: params.wireframe,
  flatShading: params.flatShading,
  envMap: envMap,
  envMapIntensity: 1.0
});

// Custom vertex shader for blob distortion
const blobVertexShader = `
  uniform float time;
  uniform float distort;
  uniform float frequency;
  uniform float numWaves;
  uniform float noise;
  uniform float surfaceDistort;
  uniform float surfaceFrequency;
  uniform float surfaceSpeed;
  uniform float surfPoleAmount;
  
  // Simple noise function
  vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 permute(vec4 x) { return mod289(((x*34.0)+1.0)*x); }
  vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
  float snoise(vec3 v) {
    const vec2 C = vec2(1.0/6.0, 1.0/3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    
    // First corner
    vec3 i  = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    
    // Other corners
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    
    // Permutations
    i = mod289(i);
    vec4 p = permute(permute(permute(
              i.z + vec4(0.0, i1.z, i2.z, 1.0))
            + i.y + vec4(0.0, i1.y, i2.y, 1.0))
            + i.x + vec4(0.0, i1.x, i2.x, 1.0));
            
    // Gradients
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    
    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    
    // Normalise gradients
    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x;
    p1 *= norm.y;
    p2 *= norm.z;
    p3 *= norm.w;
    
    // Mix final noise value
    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
  }

  void main() {
    // Base position
    vec3 pos = position;
    
    // Surface wave distortion
    float surfTime = time * surfaceSpeed;
    float poleStrength = 1.0 - surfPoleAmount * pow(abs(position.y), 2.0);
    
    // Add noise-based distortion
    float noiseValue = snoise(position * surfaceFrequency + vec3(0, 0, surfTime)) * surfaceDistort * poleStrength;
    pos += normal * noiseValue;
    
    // Global wave distortion
    for (float i = 1.0; i <= numWaves; i++) {
      float waveFreq = frequency * i;
      float waveSpeed = time * speed / i;
      float waveHeight = distort / i;
      
      pos.x += sin(position.y * waveFreq + waveSpeed) * waveHeight;
      pos.y += sin(position.z * waveFreq + waveSpeed) * waveHeight;
      pos.z += sin(position.x * waveFreq + waveSpeed) * waveHeight;
    }
    
    // Add noise distortion
    if (noise > 0.0) {
      float noiseScale = noise * 0.1;
      vec3 noisePos = position * 2.0 + time;
      pos += vec3(
        snoise(noisePos.xyz) * noiseScale,
        snoise(noisePos.yzx) * noiseScale,
        snoise(noisePos.zxy) * noiseScale
      );
    }
    
    // Calculate the modified normal
    vec3 newNormal = normal; // Would need proper recalculation in a production setting
    
    // Send to fragment shader
    gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
  }
`;

// Fragment shader (simplified for this example)
const blobFragmentShader = `
  uniform vec3 color;
  
  void main() {
    gl_FragColor = vec4(color, 1.0);
  }
`;

// Create custom shader material (in a real implementation, we'd combine this with the MeshPhysicalMaterial properties)
const customMaterial = new THREE.ShaderMaterial({
  uniforms: {
    time: { value: 0 },
    color: { value: new THREE.Color(params.color) },
    distort: { value: params.distort },
    frequency: { value: params.frequency },
    numWaves: { value: params.numWaves },
    noise: { value: params.noise },
    surfaceDistort: { value: params.surfaceDistort },
    surfaceFrequency: { value: params.surfaceFrequency },
    surfaceSpeed: { value: params.surfaceSpeed },
    surfPoleAmount: { value: params.surfPoleAmount }
  },
  vertexShader: blobVertexShader,
  fragmentShader: blobFragmentShader,
  wireframe: params.wireframe
});

// In a full implementation, we would combine the shader-based displacement with MeshPhysicalMaterial
// This would require implementing a custom onBeforeCompile function

// Create blob geometry
const blobGeometry = new THREE.SphereGeometry(
  params.scale, // radius
  params.segments, // widthSegments
  Math.floor(params.segments / 2) // heightSegments
);

// Create the blob mesh
const blob = new THREE.Mesh(blobGeometry, params.wireframe ? customMaterial : blobMaterial);
blob.rotation.x = params.rx;
blob.rotation.y = params.ry;
scene.add(blob);

// Add ambient light
const ambientLight = new THREE.AmbientLight(0xffffff, params.ambient);
scene.add(ambientLight);

// Add the three spotlights
if (params.lights[0] === 1) {
  const light1 = new THREE.SpotLight(
    params.color1, // color
    params.int1, // intensity 
    params.dist1, // distance
    params.angle1, // angle
    0.5, // penumbra (not specified in URL params)
    params.decay1 // decay
  );
  light1.position.set(params.x1, params.y1, 5); // z not specified in params, using default
  scene.add(light1);
  
  // Add spotlight helper for debugging
  // const spotLightHelper1 = new THREE.SpotLightHelper(light1);
  // scene.add(spotLightHelper1);
}

if (params.lights[1] === 2) {
  const light2 = new THREE.SpotLight(
    params.color2, // color
    params.int2, // intensity
    params.dist2, // distance
    params.angle2, // angle
    0.5, // penumbra (not specified in URL params)
    params.decay2 // decay
  );
  light2.position.set(params.x2, params.y2, params.z2);
  scene.add(light2);
  
  // Add spotlight helper for debugging
  // const spotLightHelper2 = new THREE.SpotLightHelper(light2);
  // scene.add(spotLightHelper2);
}

if (params.lights[2] === 3) {
  const light3 = new THREE.SpotLight(
    params.color3, // color
    params.int3, // intensity
    params.dist3, // distance
    params.angle3, // angle
    params.penum3, // penumbra
    params.decay3 // decay
  );
  light3.position.set(params.x3, params.y3, params.z3);
  scene.add(light3);
  
  // Add spotlight helper for debugging
  // const spotLightHelper3 = new THREE.SpotLightHelper(light3);
  // scene.add(spotLightHelper3);
}

// Set up post-processing
const composer = new EffectComposer(renderer);
const renderPass = new RenderPass(scene, camera);
composer.addPass(renderPass);

// Add bloom effect
if (params.bloom > 0) {
  const bloomPass = new UnrealBloomPass(
    new THREE.Vector2(window.innerWidth, window.innerHeight),
    params.bloom, // strength
    0.5, // radius
    0.85 // threshold
  );
  composer.addPass(bloomPass);
}

// Add glitch effect
if (params.glitch) {
  const glitchPass = new GlitchPass();
  glitchPass.goWild = false; // Controlled glitch
  composer.addPass(glitchPass);
}

// Handle window resize
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  composer.setSize(window.innerWidth, window.innerHeight);
});

// Animation loop
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  
  const elapsedTime = clock.getElapsedTime();
  
  // Update shader uniforms
  if (customMaterial.uniforms) {
    customMaterial.uniforms.time.value = elapsedTime;
  }
  
  // Slowly rotate the blob
  blob.rotation.x += 0.001;
  blob.rotation.y += 0.002;
  
  // Render with post-processing
  composer.render();
}

// Start animation
animate();