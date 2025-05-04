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
    color3: '#000000',
    bgcolor: '#000000',
    roughness: 0.3,
    metalness: 0.0,
    clearcoat: 0.1,
    clearcoatRoughness: 0,
    transmission: 0.34,
    reflectivity: 1,
    ior: 1.93,
    speed: 1,
    distortAmount: 0.43,
    stop1: 0.0,
    stop2: 0.35,
    stop3: 0.62,
    fresnelStrength: 1,
    bulgeAmount: 0.9,
    envMapRotation: 90,
    stopEase: 1,
    pixelRatio: window.devicePixelRatio,
    glowColor: '#ffffff',
    glowIntensity: 0.25,
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
    document.getElementById('app').appendChild(renderer.domElement);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.enablePan = false;
    controls.minDistance = 3;
    controls.maxDistance = 10;

    // Add background plane with album art texture
    const artTexturePlane = new THREE.TextureLoader().load('public/art3.png');
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
        envMapIntensity: params.envMapIntensity
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

    // (Removed vertical shadow plane)

    const light1 = new THREE.SpotLight(0x00fff8, 0.58);
    light1.position.set(-5, 0.07, 1.93);
    scene.add(light1);

    const light2 = new THREE.SpotLight(0x7800ff, 3);
    light2.position.set(-2.73, -6.67, 5.73);
    scene.add(light2);

    const light3 = new THREE.SpotLight(0xffffff, 2);
    light3.position.set(1.2, 2.67, 4.6);
    scene.add(light3);

    clock = new THREE.Clock();

    const artTexture = new THREE.TextureLoader().load('public/art3.png');
    artTexture.mapping = THREE.EquirectangularReflectionMapping;
    artTexture.needsUpdate = true;

    // Rotate the scene + counter-rotate the group to align the env map visually
    // without needing custom shader hacks. This is lightweight and production-safe.
    // scene.rotation.y = Math.PI / 2;
    // group.rotation.y = -Math.PI / 2;

    // GUI controls
    const gui = new GUI();
    gui.add(material, 'envMapIntensity', 0, 5, 0.01).name('Env Map Intensity').onChange(value => {
        material.envMapIntensity = value;
    });
    gui.addColor(params, 'color1').name('Color 1').onChange(updateEnvMap);
    gui.addColor(params, 'color2').name('Color 2').onChange(updateEnvMap);
    gui.addColor(params, 'color3').name('Color 3').onChange(updateEnvMap);
    gui.add(params, 'stop1', 0, 1, 0.01).name('Stop 1').onChange(updateEnvMap);
    gui.add(params, 'stop2', 0, 1, 0.01).name('Stop 2').onChange(updateEnvMap);
    gui.add(params, 'stop3', 0, 1, 0.01).name('Stop 3').onChange(updateEnvMap);
    gui.add(params, 'stopEase', 0, 1, 0.01).name('Stop Ease').onChange(updateEnvMap);
    gui.add(params, 'roughness', 0, 1, 0.01).onChange(() => { material.roughness = params.roughness; });
    gui.add(params, 'metalness', 0, 1, 0.01).onChange(() => { material.metalness = params.metalness; });
    gui.add(params, 'clearcoat', 0, 1, 0.01).onChange(() => { material.clearcoat = params.clearcoat; });
    gui.add(params, 'clearcoatRoughness', 0, 1, 0.01).onChange(() => { material.clearcoatRoughness = params.clearcoatRoughness; });
    gui.add(params, 'transmission', 0, 1, 0.01).onChange(() => { material.transmission = params.transmission; });
    gui.add(params, 'reflectivity', 0, 1, 0.01).onChange(() => { material.reflectivity = params.reflectivity; });
    gui.add(params, 'ior', 1, 2.5, 0.01).onChange(() => { material.ior = params.ior; });
    gui.add(params, 'speed', 0, 5, 0.01).name('Wave Speed');
    gui.add(params, 'distortAmount', 0, 1, 0.01).name('Distort Amount');
    gui.add(params, 'bulgeAmount', -1.0, 1.0, 0.01).name('Bulge Amount');
    gui.add(params, 'useArtTexture').name('Use Art Texture').onChange(updateEnvMap);
    gui.add(params, 'fresnelStrength', 0, 50, 0.1).name('Fresnel Strength');
    gui.addColor(params, 'bgcolor').name('Background Color').onChange(() => {
        scene.background.set(params.bgcolor);
    });
    gui.add(params, 'envMapRotation', 0, 360, 0.01).name('Env Map Rotation').onChange(() => {
        material.envMapRotation.y = THREE.MathUtils.degToRad(params.envMapRotation);
        material.needsUpdate = true;
    });
    gui.add(params, 'pixelRatio', 0.5, 2, 0.1).name('Pixel Ratio').onChange(() => {
        renderer.setPixelRatio(params.pixelRatio);
    });
    gui.addColor(params, 'glowColor').name('Glow Color').onChange(() => {
        glowMat.color.set(params.glowColor);
    });
    gui.add(params, 'glowIntensity', 0, 1, 0.01).name('Glow Intensity').onChange(() => {
        glowMat.opacity = params.glowIntensity;
    });
    gui.add({ 'Copy PNG': capturePNG }, 'Copy PNG').name('Copy PNG');


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
        const wave = 0.12 * Math.sin(vertex.x * 2 + time * params.speed) + 0.12 * Math.cos(vertex.y * 2 + time * params.speed);
        vertex.normalize().multiplyScalar(1 + wave * params.distortAmount + bulge);
        positionAttribute.setXYZ(i, vertex.x, vertex.y, vertex.z);
    }
    positionAttribute.needsUpdate = true;


    material.reflectivity = params.reflectivity + params.fresnelStrength * Math.abs(Math.sin(time));
    material.ior = params.ior + params.fresnelStrength * 0.1 * Math.abs(Math.sin(time));
    // Removed material.envMapRotation assignment here per instructions

    controls.update();

    renderer.render(scene, camera);
}