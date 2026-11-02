/* Animated backgrounds. A gradient shader on Login (an empty page seen briefly) and a Vanta net on Dashboard (a number-heavy page, so the net stays far behind and dimmed). Everything stops under `prefers-reduced-motion` and when the tab is hidden. */
(function () {
  "use strict";

  var kurangGerak = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Fragment shader, BSP palette. Green dominates, yellow appears as highlights on the wave crests, red only as a thin edge (level 0.40): in a monitoring tool red means "something is broken", so it must not dominate the background. */
  var FRAG = [
    "precision highp float;",
    "uniform float waktu;",
    "uniform vec2  ukuran;",
    "uniform float merahnya;",
    "varying vec2  vUv;",
    "float acak(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }",
    "float noise(vec2 p){",
    "  vec2 i = floor(p), f = fract(p);",
    "  vec2 u = f * f * (3.0 - 2.0 * f);",
    "  return mix(mix(acak(i), acak(i + vec2(1,0)), u.x),",
    "             mix(acak(i + vec2(0,1)), acak(i + vec2(1,1)), u.x), u.y);",
    "}",
    "float fbm(vec2 p){",
    "  float v = 0.0, a = 0.5;",
    "  for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.02; a *= 0.5; }",
    "  return v;",
    "}",
    "void main(){",
    "  vec2 uv = vUv;",
    "  uv.x *= ukuran.x / ukuran.y;",
    "  float t = waktu * 0.04;",
    "  vec2 q = vec2(fbm(uv * 1.5 + t), fbm(uv * 1.5 - t + 4.2));",
    "  float n = fbm(uv * 2.1 + q * 1.8 + t * 0.55);",
    "  float m = fbm(uv * 3.4 - q * 1.1 - t * 0.9);",
    "  vec3 gelap  = vec3(0.031, 0.082, 0.068);",
    "  vec3 hijau  = vec3(0.169, 0.376, 0.286);",
    "  vec3 hijauT = vec3(0.290, 0.667, 0.494);",
    "  vec3 kuning = vec3(0.910, 0.698, 0.122);",
    "  vec3 merah  = vec3(0.788, 0.216, 0.180);",
    "  vec3 c = mix(gelap, hijau, smoothstep(0.14, 0.66, n));",
    "  c = mix(c, hijauT, smoothstep(0.56, 0.92, n) * 0.66);",
    "  float emas = smoothstep(0.46, 0.84, n * 0.68 + m * 0.42);",
    "  c = mix(c, kuning, emas * 0.74);",
    "  float tepi = smoothstep(0.68, 0.93, m) * smoothstep(0.30, 0.58, q.x);",
    "  c = mix(c, merah, tepi * merahnya);",
    /* Fine grain: without it, a screen-wide gradient bands on 8-bit displays. */
    "  c += (acak(vUv * ukuran + waktu) - 0.5) * 0.015;",
    "  gl_FragColor = vec4(c, 1.0);",
    "}"
  ].join("\n");

  var VERT = "varying vec2 vUv;\n" +
             "void main(){ vUv = uv; gl_Position = vec4(position, 1.0); }";

  function pasangKanvas(induk) {
    var k = document.createElement("canvas");
    k.setAttribute("aria-hidden", "true");
    /* z-index -10, below the `body::before` shade layer at -9, which keeps table text readable. */
    k.style.cssText = "position:fixed;inset:0;width:100%;height:100%;" +
                      "z-index:-10;pointer-events:none;display:block";
    induk.appendChild(k);
    return k;
  }

  function mulaiShader() {
    if (typeof THREE === "undefined") return;
    var kanvas = pasangKanvas(document.body);
    var render = new THREE.WebGLRenderer({ canvas: kanvas, antialias: false });
    render.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));

    var scene = new THREE.Scene();
    var kamera = new THREE.Camera();
    var seragam = {
      waktu:    { value: 0 },
      ukuran:   { value: new THREE.Vector2(1, 1) },
      merahnya: { value: 0.40 }
    };
    scene.add(new THREE.Mesh(
      new THREE.PlaneGeometry(2, 2),
      new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG,
                                 uniforms: seragam })));

    function ukur() {
      var w = window.innerWidth, h = window.innerHeight;
      render.setSize(w, h, false);
      seragam.ukuran.value.set(w, h);
    }
    ukur();
    window.addEventListener("resize", ukur);

    var t0 = performance.now(), id = 0;

    function bingkai() {
      id = requestAnimationFrame(bingkai);
      seragam.waktu.value = (performance.now() - t0) / 1000;
      render.render(scene, kamera);
    }

    if (kurangGerak) {
      /* Drawn once and left static. */
      seragam.waktu.value = 12;
      render.render(scene, kamera);
      return;
    }

    bingkai();
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        cancelAnimationFrame(id);
      } else {
        t0 = performance.now() - seragam.waktu.value * 1000;
        bingkai();
      }
    });
  }

  function mulaiVanta() {
    if (typeof THREE === "undefined" || typeof VANTA === "undefined") return;
    if (kurangGerak) return;   

    var latar = document.createElement("div");
    latar.setAttribute("aria-hidden", "true");
    /* Container opacity raised from 0.42 to 0.88: combined with the shade layer, the net was reduced to 6-24% of its strength. The shade is also loosened for these pages (see `body[data-latar]::before` in nsm.css). */
    latar.style.cssText = "position:fixed;inset:0;z-index:-10;pointer-events:none;" +
                          "opacity:.88";
    document.body.appendChild(latar);

    var efek = VANTA.NET({
      el: latar, THREE: THREE,
      /* mouseControls is off: on Dashboard the cursor is used for reading cards, and a reactive background would pull attention. */
      mouseControls: false, touchControls: false, gyroControls: false,
      minHeight: 200, minWidth: 200, scale: 1, scaleMobile: 1,
      color: 0x5fd6a0, backgroundColor: 0x0a0a0d,
      points: 11, maxDistance: 23, spacing: 16, showDots: true
    });

    document.addEventListener("visibilitychange", function () {
      try {
        if (document.hidden) { efek.pause && efek.pause(); }
        else { efek.play && efek.play(); }
      } catch (e) {  }
    });
  }

  var jenis = document.body.getAttribute("data-latar");
  if (jenis === "shader") {
    mulaiShader();
  } else if (jenis === "jaring") {
    mulaiVanta();
  }
})();
