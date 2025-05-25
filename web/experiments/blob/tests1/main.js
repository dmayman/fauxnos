import * as THREE from 'three';
import GUI from 'lil-gui';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RGBELoader } from 'three/examples/jsm/loaders/RGBELoader.js';

let scene, camera, renderer, blob, plane, clock, material;
let previewPlane, previewMaterial;
let controls;

let params = {
    useArtTexture: false,
    envMapIntensity: 1.25,
    color1: '#be62df',
    color2: '#628fea',
    color3: '#a47f98',
    bgcolor: '#000000',
    roughness: 0,
    metalness: 0.09,
    clearcoat: 1,
    clearcoatRoughness: 0,
    transmission: 1,
    reflectivity: 1,
    ior: 1.93,
    speed: 2,
    distortAmount: 0.18,
    stop1: 0.0,
    stop2: 0.6,
    stop3: 0.9,
    fresnelStrength: 1,
    bulgeAmount: 0.9,
    envMapRotation: 90,
    stopEase: 1,
    pixelRatio: window.devicePixelRatio,
    glowColor: '#ffffff',
    glowIntensity: 0.25,
    iridescence: 1,
    iridescenceIOR: 1.3,
};

init();
// -------- PNG CAPTURE --------
async function capturePNG() {
    // Ensure the latest frame is rendered
    renderer.render(scene, camera);

    renderer.domElement.toBlob(async (blob) => {
        try {
            await navigator.clipboard.write([
                new ClipboardItem({ 'image/png': blob })
            ]);
            console.log('Blob PNG copied to clipboard');
            alert('PNG copied to clipboard!');
        } catch (err) {
            console.error('Clipboard write failed:', err);
            alert('Failed to copy PNG. Check browser permissions / HTTPS.');
        }
    }, 'image/png');
}

animate();

function init() {
    // Scene and camera
    scene = new THREE.Scene();
    scene.background = new THREE.Color(params.bgcolor);

    camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 100);
    camera.position.z = 6;

    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(params.pixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.VSMShadowMap;
    renderer.physicallyCorrectLights = true;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    document.getElementById('app').appendChild(renderer.domElement);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.enablePan = false;
    controls.minDistance = 3;
    controls.maxDistance = 10;

    // Add background plane with album art texture
    const artTexturePlane = new THREE.TextureLoader().load('../public/art3.png');
    const planeGeometry = new THREE.PlaneGeometry(2.5, 2.5);
    const planeMaterial = new THREE.MeshBasicMaterial({ map: artTexturePlane });
    plane = new THREE.Mesh(planeGeometry, planeMaterial);
    plane.position.z = 0;
    plane.visible = params.useArtTexture;

    // Geometry + material
    const geometry = new THREE.IcosahedronGeometry(1.04, 6);
    material = new THREE.MeshPhysicalMaterial({
        color: 0xffffff,
        roughness: 0,
        metalness: 0,
        clearcoat: 1,
        clearcoatRoughness: 0,
        transmission: 1,
        thickness: 1,
        reflectivity: 1,
        ior: 1.5,
        transparent: true,
        envMapIntensity: params.envMapIntensity,
        iridescence: params.iridescence,
        iridescenceIOR: params.iridescenceIOR,
        iridescenceThicknessRange: [100, 400],
    });

    const gradientTexture = createGradientTexture(params.color1, params.color2, params.color3);
    gradientTexture.center.set(0.5, 0.5);
    material.envMap = gradientTexture;
    material.envMapRotation = new THREE.Euler(0, THREE.MathUtils.degToRad(params.envMapRotation), 0);

    // const rgbeLoader = new RGBELoader();
    // rgbeLoader.load('public/env1.hdr', (hdrTexture) => {
    //     hdrTexture.mapping = THREE.EquirectangularReflectionMapping;
    //     material.envMap = hdrTexture;
    //     material.envMapRotation = params.envMapRotation;  // <- add this line!
    //     material.needsUpdate = true;
    // });

    material.needsUpdate = true;


    blob = new THREE.Mesh(geometry, material);
    blob.position.z = 0.05;
    blob.castShadow = true;
    blob.receiveShadow = false;

    const glowGeom = new THREE.SphereGeometry(1.3, 32, 32);   // slightly larger
    const glowMat  = new THREE.MeshBasicMaterial({
        color: new THREE.Color(params.glowColor),
        transparent: true,
        opacity: params.glowIntensity,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        side: THREE.FrontSide
    });
    const glowMesh = new THREE.Mesh(glowGeom, glowMat);
    blob.add(glowMesh);

    const group = new THREE.Group();
    group.add(plane);
    group.add(blob);
    scene.add(group);

    // Clean up any existing lights
    scene.children.forEach(child => {
        if (child.isLight) {
            scene.remove(child);
        }
    });

    // Create an extremely simple lighting setup
    // Just ambient light for base illumination
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
    scene.add(ambientLight);

    // Single soft directional light for shadows on wall only
    const shadowLight = new THREE.DirectionalLight(0xffffff, 0.7);
    shadowLight.position.set(0, 0, 8); // Position in front of blob, pointing at wall
    shadowLight.castShadow = true;
    shadowLight.shadow.mapSize.width = 2048;
    shadowLight.shadow.mapSize.height = 2048;
    shadowLight.shadow.camera.near = 0.5;
    shadowLight.shadow.camera.far = 15;
    shadowLight.shadow.camera.left = -3;
    shadowLight.shadow.camera.right = 3;
    shadowLight.shadow.camera.top = 3;
    shadowLight.shadow.camera.bottom = -3;
    shadowLight.shadow.radius = 12; // Very soft shadow
    shadowLight.shadow.bias = -0.0005;
    shadowLight.shadow.normalBias = 0.02;
    scene.add(shadowLight);

    // Create vertical background plane
    const bgPlaneGeometry = new THREE.PlaneGeometry(20, 20);
    const bgPlaneMaterial = new THREE.MeshStandardMaterial({ 
        color: 0x000000,
        roughness: 0.9,
        metalness: 0.1,
        envMapIntensity: 0.5
    });
    const bgPlane = new THREE.Mesh(bgPlaneGeometry, bgPlaneMaterial);
    bgPlane.position.z = -2;
    bgPlane.receiveShadow = true;
    scene.add(bgPlane);

    // Remove any existing shadow plane
    scene.children.forEach(child => {
        if (child.material && child.material.isShadowMaterial) {
            scene.remove(child);
        }
    });

    clock = new THREE.Clock();

    // GUI Controls
    const gui = new GUI({ width: 350 });
    
    // Helper function to create sliders with value display
    function addSlider(folder, object, property, min, max, step, name, onChange = null) {
        const controller = folder.add(object, property, min, max, step);
        // Store the original name as a property on the controller
        controller.originalName = name;
        updateSliderDisplay(controller, object[property]);
        controller.onChange(value => {
            updateSliderDisplay(controller, value);
            if (onChange) onChange(value);
        });
        return controller;
    }

    function updateSliderDisplay(controller, value) {
        // Format the value to show appropriate decimal places
        const displayValue = Number.isInteger(controller._step) ? 
            value.toFixed(0) : value.toFixed(2);
        // Always use the original name when updating
        controller.name(`${controller.originalName}: ${displayValue}`);
    }

    // Material Settings
    const materialFolder = gui.addFolder('Material');
    addSlider(materialFolder, params, 'roughness', 0, 1, 0.01, 'Roughness', 
        value => { material.roughness = value; });
    addSlider(materialFolder, params, 'metalness', 0, 1, 0.01, 'Metalness',
        value => { material.metalness = value; });
    addSlider(materialFolder, params, 'clearcoat', 0, 1, 0.01, 'Clearcoat',
        value => { material.clearcoat = value; });
    addSlider(materialFolder, params, 'clearcoatRoughness', 0, 1, 0.01, 'Clearcoat Roughness',
        value => { material.clearcoatRoughness = value; });
    addSlider(materialFolder, params, 'transmission', 0, 1, 0.01, 'Transmission',
        value => { material.transmission = value; });
    addSlider(materialFolder, params, 'reflectivity', 0, 1, 0.01, 'Reflectivity',
        value => { material.reflectivity = value; });
    addSlider(materialFolder, params, 'ior', 1, 2.5, 0.01, 'IOR',
        value => { material.ior = value; });
    addSlider(materialFolder, params, 'envMapIntensity', 0, 5, 0.01, 'Env Map Intensity',
        value => { material.envMapIntensity = value; });
    addSlider(materialFolder, params, 'iridescence', 0, 1, 0.01, 'Iridescence',
        value => { material.iridescence = value; });
    addSlider(materialFolder, params, 'iridescenceIOR', 1, 2.33, 0.01, 'Iridescence IOR',
        value => { material.iridescenceIOR = value; });
    
    // Color Settings
    const colorFolder = gui.addFolder('Colors');
    colorFolder.addColor(params, 'color1').name('Color 1').onChange(updateEnvMap);
    colorFolder.addColor(params, 'color2').name('Color 2').onChange(updateEnvMap);
    colorFolder.addColor(params, 'color3').name('Color 3').onChange(updateEnvMap);
    colorFolder.addColor(params, 'bgcolor').name('Background').onChange((value) => {
        scene.background = new THREE.Color(value);
    });
    addSlider(colorFolder, params, 'glowIntensity', 0, 1, 0.01, 'Glow Intensity');
    colorFolder.addColor(params, 'glowColor').name('Glow Color');
    
    // Animation Settings
    const animationFolder = gui.addFolder('Animation');
    addSlider(animationFolder, params, 'speed', 0.1, 5, 0.1, 'Wave Speed');
    addSlider(animationFolder, params, 'distortAmount', 0, 1, 0.01, 'Distortion');
    addSlider(animationFolder, params, 'bulgeAmount', -1, 1, 0.01, 'Bulge');
    addSlider(animationFolder, params, 'fresnelStrength', 0, 5, 0.1, 'Fresnel');
    addSlider(animationFolder, params, 'envMapRotation', 0, 360, 1, 'Env Rotation')
        .onChange(() => {
            material.envMapRotation.y = THREE.MathUtils.degToRad(params.envMapRotation);
            material.needsUpdate = true;
        });
    
    // Gradient Stops
    const gradientFolder = gui.addFolder('Gradient Stops');
    addSlider(gradientFolder, params, 'stop1', 0, 1, 0.01, 'Stop 1').onChange(updateEnvMap);
    addSlider(gradientFolder, params, 'stop2', 0, 1, 0.01, 'Stop 2').onChange(updateEnvMap);
    addSlider(gradientFolder, params, 'stop3', 0, 1, 0.01, 'Stop 3').onChange(updateEnvMap);
    addSlider(gradientFolder, params, 'stopEase', 0.1, 5, 0.1, 'Easing').onChange(updateEnvMap);
    
    // Toggles
    const toggleFolder = gui.addFolder('Toggles');
    toggleFolder.add(params, 'useArtTexture').name('Show Album Art').onChange((value) => {
        plane.visible = value;
        updateEnvMap();
    });
    
    // Display Settings
    const displayFolder = gui.addFolder('Display');
    displayFolder.add(params, 'pixelRatio', 0.5, 2, 0.1).name('Pixel Ratio').onChange(() => {
        renderer.setPixelRatio(params.pixelRatio);
    });
    
    // Add a button to capture the current view as PNG
    gui.add({ capture: capturePNG }, 'capture').name('📸 Capture PNG');
    
    // Open all folders by default
    materialFolder.open();
    colorFolder.open();
    animationFolder.open();
    gradientFolder.open();
    toggleFolder.open();
    displayFolder.open();

    const artTexture = new THREE.TextureLoader().load('public/art3.png');
    artTexture.mapping = THREE.EquirectangularReflectionMapping;
    artTexture.needsUpdate = true;

    // Shadow & Lighting Settings
    const shadowFolder = gui.addFolder('Shadow & Lighting');
    
    // Light position controls
    const lightXCtrl = addSlider(shadowFolder, shadowLight.position, 'x', -10, 10, 0.1, 'Light X');
    const lightYCtrl = addSlider(shadowFolder, shadowLight.position, 'y', -10, 10, 0.1, 'Light Y');
    const lightZCtrl = addSlider(shadowFolder, shadowLight.position, 'z', 0, 15, 0.1, 'Light Z');
    
    // Light intensity controls
    addSlider(shadowFolder, shadowLight, 'intensity', 0, 2, 0.05, 'Light Intensity');
    addSlider(shadowFolder, ambientLight, 'intensity', 0, 2, 0.05, 'Ambient Light');
    
    // Shadow controls
    addSlider(shadowFolder, shadowLight.shadow, 'radius', 0, 3000, 0.5, 'Shadow Softness');
    addSlider(shadowFolder, bgPlane.position, 'z', -5, 0, 0.1, 'Wall Distance');
    
    // Wall color control
    shadowFolder.addColor({wallColor: '#000000'}, 'wallColor').name('Wall Color').onChange(value => {
        bgPlane.material.color.set(value);
    });
    
    // Update light position displays when changed through other means
    shadowLight.position.onChange = () => {
        updateSliderDisplay(lightXCtrl, shadowLight.position.x);
        updateSliderDisplay(lightYCtrl, shadowLight.position.y);
        updateSliderDisplay(lightZCtrl, shadowLight.position.z);
    };

    // Handle window resize

    // Handle resize
    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setPixelRatio(params.pixelRatio);
        renderer.setSize(window.innerWidth, window.innerHeight);
    });

    function updateEnvMap() {
        plane.visible = params.useArtTexture;
        const updatedTexture = createGradientTexture(params.color1, params.color2, params.color3);
        updatedTexture.center.set(0.5, 0.5);
        // Update blob's envMap if using gradient (CanvasTexture)
        if (material.envMap && material.envMap.isCanvasTexture) {
            material.envMap = updatedTexture;
            material.needsUpdate = true;
        }
    }

}

function createGradientTexture(c1, c2, c3) {
    const size = 512; // reduce for performance, but you can set higher for more smoothness
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    const imgData = ctx.createImageData(size, size);

    const color1 = new THREE.Color(c1);
    const color2 = new THREE.Color(c2);
    const color3 = new THREE.Color(c3);

    // Compute stops and easing
    const stop1 = params.stop1;
    const stop2 = params.stop2;
    const stop3 = params.stop3;
    const stopEase = params.stopEase;

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

function animate() {
    requestAnimationFrame(animate);

    const time = clock.getElapsedTime();
    const positionAttribute = blob.geometry.attributes.position;
    const vertex = new THREE.Vector3();
    const bulge = params.bulgeAmount;

    for (let i = 0; i < positionAttribute.count; i++) {
        vertex.fromBufferAttribute(positionAttribute, i);
        const waveFreq = 3.0;
        const rippleSpeed = params.speed * 0.5;
        const rippleDepth = 0.04;
        
        // Create concentric ripples
        const distFromCenter = Math.sqrt(vertex.x * vertex.x + vertex.y * vertex.y);
        const ripple = rippleDepth * Math.sin(distFromCenter * waveFreq - time * rippleSpeed);
        
        // Combine with existing waves
        const wave = 0.12 * Math.sin(vertex.x * 2 + time * params.speed) + 
                     0.12 * Math.cos(vertex.y * 2 + time * params.speed) + 
                     ripple;
        vertex.normalize().multiplyScalar(1 + wave * params.distortAmount + bulge);
        positionAttribute.setXYZ(i, vertex.x, vertex.y, vertex.z);
    }
    positionAttribute.needsUpdate = true;


    material.reflectivity = params.reflectivity + params.fresnelStrength * Math.abs(Math.sin(time));
    material.ior = params.ior + 0.05 * Math.sin(time * 0.4);
    material.transmission = params.transmission + 0.01 * Math.sin(time * 0.6);
    material.iridescenceIOR = params.iridescenceIOR + 0.2 * Math.sin(time * 0.8);
    // Removed material.envMapRotation assignment here per instructions

    controls.update();

    renderer.render(scene, camera);
}