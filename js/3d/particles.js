/**
 * particles.js — one Points object whose vertices morph on the GPU between
 * the chaos / logo / system shapes. THREE is passed in (loaded lazily).
 */
import { chaosPositions, logoPositions, systemPositions, seededRandom } from "./shapes.js";

const vertexShader = /* glsl */ `
  uniform float uTime;
  uniform float uMorph1;
  uniform float uMorph2;
  uniform float uScatter;
  uniform float uSize;
  uniform float uPixelRatio;
  attribute vec3 aLogo;
  attribute vec3 aSystem;
  attribute float aRand;
  attribute float aScale;
  attribute vec3 aColor;
  varying vec3 vColor;
  varying float vAlpha;

  void main() {
    float delay = aRand * 0.45;
    float m1 = smoothstep(delay, delay + 0.55, uMorph1);
    float m2 = smoothstep(delay, delay + 0.55, uMorph2);

    vec3 p = mix(position, aLogo, m1);
    p = mix(p, aSystem, m2);

    float amp = 0.035 + (1.0 - m1) * 0.45;
    p += vec3(
      sin(uTime * 0.7 + aRand * 40.0),
      cos(uTime * 0.6 + aRand * 27.0),
      sin(uTime * 0.5 + aRand * 13.0)
    ) * amp;

    p = mix(p, position * 1.6, uScatter * (0.4 + aRand * 0.6));

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSize * aScale * uPixelRatio / -mv.z;

    float twinkle = 0.75 + 0.25 * sin(uTime * 2.0 + aRand * 60.0);
    vAlpha = twinkle * (1.0 - uScatter * 0.6);
    vColor = aColor;
  }
`;

const fragmentShader = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;

  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    float strength = pow(1.0 - d * 2.0, 1.8);
    gl_FragColor = vec4(vColor * strength, strength * vAlpha);
  }
`;

export function createParticles(THREE, count) {
  const rand = seededRandom(1987);
  const geometry = new THREE.BufferGeometry();

  geometry.setAttribute("position", new THREE.BufferAttribute(chaosPositions(count, rand), 3));
  geometry.setAttribute("aLogo", new THREE.BufferAttribute(logoPositions(count, rand), 3));
  geometry.setAttribute("aSystem", new THREE.BufferAttribute(systemPositions(count, rand), 3));

  const rands = new Float32Array(count);
  const scales = new Float32Array(count);
  const colors = new Float32Array(count * 3);
  const blue = new THREE.Color("#3b82f6");
  const cyan = new THREE.Color("#22d3ee");
  const white = new THREE.Color("#e8f4ff");
  const tmp = new THREE.Color();

  for (let i = 0; i < count; i++) {
    rands[i] = rand();
    const sparkle = rand() < 0.04;
    scales[i] = sparkle ? 2.2 + rand() : 0.6 + rand() * 0.9;
    if (sparkle) tmp.copy(white);
    else tmp.copy(blue).lerp(cyan, rand());
    tmp.multiplyScalar(0.8);
    colors[i * 3] = tmp.r;
    colors[i * 3 + 1] = tmp.g;
    colors[i * 3 + 2] = tmp.b;
  }

  geometry.setAttribute("aRand", new THREE.BufferAttribute(rands, 1));
  geometry.setAttribute("aScale", new THREE.BufferAttribute(scales, 1));
  geometry.setAttribute("aColor", new THREE.BufferAttribute(colors, 3));

  const material = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uMorph1: { value: 0 },
      uMorph2: { value: 0 },
      uScatter: { value: 0 },
      uSize: { value: 30 },
      uPixelRatio: { value: 1 }
    },
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });

  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  return points;
}
