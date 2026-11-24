"use client"

/**
 * GasGauge3D: a procedural 3D LPG cylinder on a digital weighing platform.
 *
 * - Data in, nothing out: the parent supplies gasLevel / remainingGas / cylinderWeight /
 *   cylinderCapacity / dataSource / connectionStatus. This component never reads a sensor,
 *   never generates readings and knows nothing about Arduino, Wokwi or serial ports.
 * - The Three.js scene is created once. Changing props only updates targets that are
 *   eased inside the render loop, so live readings never rebuild the scene.
 * - All geometry is procedural (no external model or texture downloads).
 */

import * as React from "react"
import * as THREE from "three"
import { OrbitControls } from "three/addons/controls/OrbitControls.js"
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js"
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js"
import { cn } from "@/lib/utils"

/* ───────────────────────────── Public API ───────────────────────────── */

export type GasDataSource = "wokwi" | "hardware" | "demo"
export type GasConnectionStatus = "connected" | "disconnected"
export type GasGaugeView = "cylinder" | "cutaway" | "sensor" | "exploded"
export type GasGaugePart =
  | "valve"
  | "collar"
  | "cylinder"
  | "gas"
  | "plate"
  | "loadCell"
  | "hx711"
  | "display"
  | "base"

export interface GasGauge3DProps {
  /** Remaining gas, 0-100. Non-finite values are drawn as "no data". */
  gasLevel: number
  /** Remaining LPG in kg. */
  remainingGas: number
  /** Total (gross) cylinder weight in kg, shown on the platform display. */
  cylinderWeight: number
  /** LPG capacity in kg. */
  cylinderCapacity: number
  dataSource: GasDataSource
  connectionStatus: GasConnectionStatus
  /** Level (%) at or below which the gas turns amber. Default 25. */
  lowThreshold?: number
  /** Level (%) at or below which the gas turns red. Default 10. */
  criticalThreshold?: number
  initialView?: GasGaugeView
  onViewChange?: (view: GasGaugeView) => void
  onPartSelect?: (part: GasGaugePart | null) => void
  className?: string
  /** CSS height of the viewer. Default 520. */
  height?: number | string
}

/* ───────────────────────────── Constants ───────────────────────────── */

const C = {
  lime: "#c6f135",
  forest: "#2f9e63",
  amber: "#f2a93b",
  red: "#d0605c",
  idle: "#6d786f",
  paper: "#ecefe8",
  charcoal: "#101311",
}

const VIEWS: { id: GasGaugeView; label: string }[] = [
  { id: "cylinder", label: "Cylinder View" },
  { id: "cutaway", label: "Cutaway View" },
  { id: "sensor", label: "Sensor Assembly" },
  { id: "exploded", label: "Exploded View" },
]

const SOURCE_CHIP: Record<GasDataSource, { text: string; cls: string }> = {
  demo: { text: "DEMO", cls: "border-[#f2a93b]/70 text-[#f2a93b]" },
  wokwi: { text: "WOKWI", cls: "border-[#2f9e63]/70 text-[#5fd08f]" },
  hardware: { text: "LIVE HARDWARE", cls: "border-[#c6f135]/70 text-[#c6f135]" },
}

const PART_INFO: Record<GasGaugePart, { title: string; text: string }> = {
  valve: { title: "Cylinder valve", text: "Brass valve with a side outlet. Schematic model, not to scale." },
  collar: { title: "Protective collar", text: "Guard ring that shields the valve from knocks and drops." },
  cylinder: { title: "LPG cylinder", text: "Steel shell. The lit level window on the side tracks the remaining gas." },
  gas: {
    title: "LPG volume",
    text: "Fill height is volume-based and follows the gasLevel prop. 100% is drawn at an 85% fill limit.",
  },
  plate: { title: "Weighing plate", text: "Stainless plate that passes the cylinder's weight to the load cell." },
  loadCell: {
    title: "Load cell",
    text: "Strain-gauge bar. Wire colours follow E+ red, E− black, A− white, A+ green.",
  },
  hx711: { title: "HX711 amplifier", text: "24-bit ADC that digitises the load-cell signal for the microcontroller." },
  display: { title: "Weight display", text: "Shows the cylinderWeight value supplied by the dashboard." },
  base: { title: "Base frame", text: "Powder-coated frame with rubber feet and ventilation slots." },
}

/** Which part labels are shown in each view. */
const LABELS_FOR_VIEW: Record<GasGaugeView, GasGaugePart[]> = {
  cylinder: ["valve", "collar", "cylinder", "display"],
  cutaway: ["gas", "cylinder"],
  sensor: ["loadCell", "hx711", "plate", "display"],
  exploded: ["valve", "collar", "cylinder", "gas", "plate", "loadCell", "hx711", "display", "base"],
}

const CAMERA: Record<GasGaugeView, { pos: [number, number, number]; target: [number, number, number] }> = {
  cylinder: { pos: [6.6, 4.4, 8.6], target: [0, 3.1, 0] },
  cutaway: { pos: [2.4, 3.9, 9.2], target: [0, 3.0, 0] },
  sensor: { pos: [4.2, 2.2, 5.8], target: [0.2, 0.5, 0.2] },
  exploded: { pos: [9.5, 6.4, 15.5], target: [0, 4.6, 0] },
}

// Geometry (scene units; 1 unit is roughly 10 cm)
const R = 1.5 // cylinder radius
const FOOT_H = 0.3
const SHOULDER_Y = 3.35
const NECK_Y = 4.3
const NECK_R = 0.42
const WALL = 0.07
const CYL_Y = 0.84 // cylinder base height above the floor
const FILL_LIMIT = 0.85 // 100% is drawn at an 85% fill, like a real cylinder
const LED_COUNT = 20

/* ───────────────────────────── Small helpers ───────────────────────────── */

const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v))
const lerp = (a: number, b: number, t: number) => a + (b - a) * t
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n)
const fmt = (n: number | null | undefined, d = 1) => (finite(n) ? n.toFixed(d) : "—")

type Status = "ok" | "low" | "critical"
const statusOf = (level: number, low: number, crit: number): Status =>
  level <= crit ? "critical" : level <= low ? "low" : "ok"
const STATUS_COLOR: Record<Status, string> = { ok: C.lime, low: C.amber, critical: C.red }
const STATUS_TEXT: Record<Status, string> = { ok: "NORMAL", low: "LOW", critical: "CRITICAL" }

interface LiveState {
  level: number | null
  remaining: number | null
  weight: number | null
  capacity: number | null
  source: GasDataSource
  connected: boolean
  low: number
  critical: number
}

function canvasTexture(
  w: number,
  h: number,
  draw: (g: CanvasRenderingContext2D, w: number, h: number) => void,
  srgb = true,
) {
  const canvas = document.createElement("canvas")
  canvas.width = w
  canvas.height = h
  const g = canvas.getContext("2d")
  if (!g) throw new Error("2D canvas is not available")
  draw(g, w, h)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace
  tex.anisotropy = 8
  return tex
}

function redraw(tex: THREE.CanvasTexture, draw: (g: CanvasRenderingContext2D, w: number, h: number) => void) {
  const canvas = tex.image as HTMLCanvasElement
  const g = canvas.getContext("2d")
  if (!g) return
  g.clearRect(0, 0, canvas.width, canvas.height)
  draw(g, canvas.width, canvas.height)
  tex.needsUpdate = true
}

function brushedTexture() {
  const tex = canvasTexture(
    512,
    512,
    (g, w, h) => {
      g.fillStyle = "#808080"
      g.fillRect(0, 0, w, h)
      for (let i = 0; i < 5000; i++) {
        const x = Math.random() * w
        const y = Math.random() * h
        const len = 20 + Math.random() * 180
        const v = Math.floor(100 + Math.random() * 110)
        g.strokeStyle = `rgba(${v},${v},${v},${0.08 + Math.random() * 0.18})`
        g.lineWidth = 0.3 + Math.random() * 1.4
        g.beginPath()
        g.moveTo(x, y)
        g.lineTo(x + len, y + (Math.random() - 0.5) * 1.2)
        g.stroke()
      }
    },
    false,
  )
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping
  tex.repeat.set(2, 2)
  return tex
}

/** Outline of a cylinder with a rounded bottom edge and rounded shoulders (radius, height). */
function makeProfile(r: number, y0: number, yShoulder: number, yNeck: number, rNeck: number) {
  const pts: THREE.Vector2[] = [new THREE.Vector2(0.001, y0), new THREE.Vector2(r * 0.6, y0)]
  const bevel = 0.22
  for (let i = 0; i <= 8; i++) {
    const a = -Math.PI / 2 + (i / 8) * (Math.PI / 2)
    pts.push(new THREE.Vector2(r - bevel + bevel * Math.cos(a), y0 + bevel + bevel * Math.sin(a)))
  }
  pts.push(new THREE.Vector2(r, yShoulder))
  for (let i = 1; i <= 18; i++) {
    const phi = (i / 18) * (Math.PI / 2)
    pts.push(new THREE.Vector2(rNeck + (r - rNeck) * Math.cos(phi), yShoulder + (yNeck - yShoulder) * Math.sin(phi)))
  }
  pts.push(new THREE.Vector2(0.001, yNeck))
  return pts
}

interface VolumeTable {
  ys: number[]
  vs: number[]
  total: number
}

function volumeTable(pts: THREE.Vector2[]): VolumeTable {
  const ys: number[] = []
  const vs: number[] = []
  let v = 0
  pts.forEach((p, i) => {
    if (i > 0) {
      const a = pts[i - 1]
      const dy = p.y - a.y
      if (dy > 0) v += (Math.PI * dy * (a.x * a.x + a.x * p.x + p.x * p.x)) / 3
    }
    ys.push(p.y)
    vs.push(v)
  })
  return { ys, vs, total: v }
}

function yAtFraction(t: VolumeTable, f: number) {
  const target = clamp(f, 0, 1) * t.total
  for (let i = 1; i < t.vs.length; i++) {
    if (t.vs[i] >= target) {
      const span = t.vs[i] - t.vs[i - 1]
      return lerp(t.ys[i - 1], t.ys[i], span > 0 ? (target - t.vs[i - 1]) / span : 0)
    }
  }
  return t.ys[t.ys.length - 1]
}

function radiusAtY(pts: THREE.Vector2[], y: number) {
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1]
    const b = pts[i]
    if (b.y > a.y && y >= a.y && y <= b.y) return lerp(a.x, b.x, (y - a.y) / (b.y - a.y))
  }
  return 0
}

function roundedRect(w: number, d: number, r: number) {
  const s = new THREE.Shape()
  const x = -w / 2
  const y = -d / 2
  s.moveTo(x + r, y)
  s.lineTo(x + w - r, y)
  s.absarc(x + w - r, y + r, r, -Math.PI / 2, 0, false)
  s.lineTo(x + w, y + d - r)
  s.absarc(x + w - r, y + d - r, r, 0, Math.PI / 2, false)
  s.lineTo(x + r, y + d)
  s.absarc(x + r, y + d - r, r, Math.PI / 2, Math.PI, false)
  s.lineTo(x, y + r)
  s.absarc(x + r, y + r, r, Math.PI, Math.PI * 1.5, false)
  return s
}

/** Bevelled slab whose bottom face is at y = -bevel and top face at y = h + bevel. */
function slab(w: number, d: number, h: number, r: number, bevel: number) {
  const g = new THREE.ExtrudeGeometry(roundedRect(w, d, r), {
    depth: h,
    bevelEnabled: true,
    bevelSize: bevel,
    bevelThickness: bevel,
    bevelSegments: 3,
    curveSegments: 12,
  })
  g.rotateX(-Math.PI / 2)
  return g
}

const MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

function drawCylinderLabel(g: CanvasRenderingContext2D, w: number, h: number, capacity: number | null) {
  g.fillStyle = "rgba(0,0,0,0)"
  g.clearRect(0, 0, w, h)
  g.fillStyle = C.lime
  g.fillRect(w * 0.08, h * 0.1, w * 0.84, 6)
  g.fillStyle = C.paper
  g.textAlign = "center"
  g.textBaseline = "middle"
  g.font = `700 ${h * 0.2}px ${MONO}`
  g.fillText("GAS GAUGE", w / 2, h * 0.28)
  g.font = `500 ${h * 0.065}px ${MONO}`
  g.fillStyle = "rgba(236,239,232,0.75)"
  g.fillText("LIQUEFIED PETROLEUM GAS", w / 2, h * 0.43)
  g.fillStyle = C.paper
  g.font = `700 ${h * 0.26}px ${MONO}`
  g.fillText(finite(capacity) ? `${capacity % 1 === 0 ? capacity.toFixed(0) : capacity.toFixed(1)} kg` : "— kg", w / 2, h * 0.67)
  g.font = `500 ${h * 0.06}px ${MONO}`
  g.fillStyle = "rgba(236,239,232,0.7)"
  g.fillText("NET CONTENT", w / 2, h * 0.84)
  // flammable diamond
  g.save()
  g.translate(w * 0.86, h * 0.84)
  g.rotate(Math.PI / 4)
  g.strokeStyle = C.red
  g.lineWidth = 5
  g.strokeRect(-h * 0.045, -h * 0.045, h * 0.09, h * 0.09)
  g.restore()
  g.fillStyle = C.lime
  g.fillRect(w * 0.08, h * 0.93, w * 0.84, 6)
}

function drawPlateLabel(g: CanvasRenderingContext2D, w: number, h: number) {
  g.clearRect(0, 0, w, h)
  g.fillStyle = "rgba(20,26,22,0.92)"
  g.textBaseline = "middle"
  g.textAlign = "left"
  g.font = `700 ${h * 0.46}px ${MONO}`
  g.fillText("GAS GAUGE", w * 0.04, h * 0.5)
  g.textAlign = "right"
  g.font = `500 ${h * 0.3}px ${MONO}`
  g.fillText("LOAD CELL PLATFORM  ▲ PLACE CYLINDER", w * 0.96, h * 0.5)
}

function drawLedScale(g: CanvasRenderingContext2D, w: number, h: number) {
  g.clearRect(0, 0, w, h)
  g.fillStyle = "rgba(236,239,232,0.85)"
  g.font = `600 ${w * 0.5}px ${MONO}`
  g.textAlign = "left"
  g.textBaseline = "middle"
  ;[0, 25, 50, 75, 100].forEach((v) => g.fillText(String(v), w * 0.04, h - (v / 100) * (h * 0.9) - h * 0.05))
}

function drawDisplay(g: CanvasRenderingContext2D, w: number, h: number, s: LiveState) {
  g.fillStyle = "#070b08"
  g.fillRect(0, 0, w, h)
  const hasLevel = finite(s.level)
  const status = hasLevel ? statusOf(s.level as number, s.low, s.critical) : "ok"
  const col = !s.connected || !hasLevel ? "#8a948c" : STATUS_COLOR[status]
  g.fillStyle = "rgba(198,241,53,0.05)"
  for (let y = 0; y < h; y += 4) g.fillRect(0, y, w, 1)
  g.textBaseline = "alphabetic"
  g.textAlign = "left"
  g.fillStyle = "rgba(236,239,232,0.6)"
  g.font = `600 ${h * 0.11}px ${MONO}`
  g.fillText("WEIGHT", w * 0.06, h * 0.2)
  g.textAlign = "right"
  g.fillText(s.source === "hardware" ? "HW" : s.source === "wokwi" ? "SIM" : "DEMO", w * 0.94, h * 0.2)
  g.textAlign = "left"
  g.fillStyle = col
  g.font = `700 ${h * 0.34}px ${MONO}`
  g.fillText(finite(s.weight) ? s.weight.toFixed(2) : "--.--", w * 0.06, h * 0.62)
  g.font = `600 ${h * 0.14}px ${MONO}`
  g.fillText("kg", w * 0.78, h * 0.62)
  g.font = `600 ${h * 0.12}px ${MONO}`
  g.fillStyle = col
  const line = !s.connected ? "NO SIGNAL · LAST VALUE" : hasLevel ? `GAS ${(s.level as number).toFixed(0)}% · ${STATUS_TEXT[status]}` : "WAITING FOR DATA"
  g.fillText(line, w * 0.06, h * 0.88)
}

/* ───────────────────────────── Scene ───────────────────────────── */

interface SceneCallbacks {
  onSelect: (part: GasGaugePart | null) => void
  onContextLost: () => void
}

interface SceneApi {
  setView: (view: GasGaugeView, animate: boolean) => void
  resetCamera: () => void
  setLive: (state: LiveState) => void
  setReducedMotion: (reduced: boolean) => void
  select: (part: GasGaugePart | null) => void
  dispose: () => void
}

interface Part {
  id: GasGaugePart
  group: THREE.Group
  base: THREE.Vector3
  explode: THREE.Vector3
  label: { obj: CSS2DObject; el: HTMLButtonElement } | null
}

const LABEL_CLASS =
  "pointer-events-auto cursor-pointer select-none whitespace-nowrap rounded-md border border-[#c6f135]/40 bg-[#101311]/85 px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-[#ecefe8] backdrop-blur-sm transition-colors hover:border-[#c6f135] hover:text-[#c6f135] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#c6f135]"

function createScene(mount: HTMLElement, cb: SceneCallbacks, initial: LiveState, startView: GasGaugeView, reducedInit: boolean): SceneApi {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" })
  const canvas = renderer.domElement
  const textures: THREE.Texture[] = []
  const labelRenderer = new CSS2DRenderer()
  let raf = 0
  let disposed = false

  try {
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.05
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFShadowMap
    renderer.localClippingEnabled = true
    canvas.className = "absolute inset-0 block h-full w-full outline-none"
    canvas.style.touchAction = "none"
    mount.appendChild(canvas)
    labelRenderer.domElement.style.position = "absolute"
    labelRenderer.domElement.style.inset = "0"
    labelRenderer.domElement.style.pointerEvents = "none"
    mount.appendChild(labelRenderer.domElement)
  } catch (err) {
    renderer.dispose()
    throw err
  }

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 120)
  const pmrem = new THREE.PMREMGenerator(renderer)
  const envScene = new RoomEnvironment()
  const envTarget = pmrem.fromScene(envScene, 0.04)
  scene.environment = envTarget.texture
  scene.environmentIntensity = 0.55

  let reduced = reducedInit
  let live: LiveState = initial
  let view: GasGaugeView = startView
  let selected: GasGaugePart | null = null
  let hovered: GasGaugePart | null = null
  let visible = true
  let dirty = true

  /* ── lights ── */
  scene.add(new THREE.HemisphereLight(0xdfe8dc, 0x0b0f0c, 0.35))
  const key = new THREE.DirectionalLight(0xfff2dc, 2.4)
  key.position.set(6, 11, 7)
  key.castShadow = true
  key.shadow.mapSize.set(2048, 2048)
  key.shadow.camera.left = -8
  key.shadow.camera.right = 8
  key.shadow.camera.top = 10
  key.shadow.camera.bottom = -4
  key.shadow.camera.far = 40
  key.shadow.bias = -0.0004
  key.shadow.normalBias = 0.03
  scene.add(key)
  const rimLime = new THREE.DirectionalLight(new THREE.Color(C.lime), 0.9)
  rimLime.position.set(-7, 4, -6)
  scene.add(rimLime)
  const rimForest = new THREE.DirectionalLight(new THREE.Color(C.forest), 1.3)
  rimForest.position.set(7, 3, -7)
  scene.add(rimForest)
  const displayGlow = new THREE.PointLight(new THREE.Color(C.lime), 0.0, 5, 2)
  displayGlow.position.set(0, 0.9, 3.2)
  scene.add(displayGlow)

  /* ── floor ── */
  const gridTex = canvasTexture(1024, 1024, (g, w, h) => {
    g.clearRect(0, 0, w, h)
    g.strokeStyle = "rgba(198,241,53,0.16)"
    g.lineWidth = 2
    for (let i = 1; i <= 8; i++) {
      g.beginPath()
      g.arc(w / 2, h / 2, (i / 8) * (w / 2 - 6), 0, Math.PI * 2)
      g.stroke()
    }
    g.strokeStyle = "rgba(198,241,53,0.09)"
    for (let i = 0; i < 24; i++) {
      const a = (i / 24) * Math.PI * 2
      g.beginPath()
      g.moveTo(w / 2, h / 2)
      g.lineTo(w / 2 + Math.cos(a) * (w / 2 - 6), h / 2 + Math.sin(a) * (w / 2 - 6))
      g.stroke()
    }
  })
  textures.push(gridTex)
  const floorGrid = new THREE.Mesh(
    new THREE.CircleGeometry(13, 96),
    new THREE.MeshBasicMaterial({ map: gridTex, transparent: true, depthWrite: false, opacity: 0.9 }),
  )
  floorGrid.rotation.x = -Math.PI / 2
  floorGrid.position.y = -0.004
  scene.add(floorGrid)
  const floorShadow = new THREE.Mesh(new THREE.CircleGeometry(13, 64), new THREE.ShadowMaterial({ opacity: 0.45 }))
  floorShadow.rotation.x = -Math.PI / 2
  floorShadow.receiveShadow = true
  scene.add(floorShadow)

  /* ── materials ── */
  const brushed = brushedTexture()
  textures.push(brushed)
  const steel = () =>
    new THREE.MeshStandardMaterial({ color: 0xaab2b9, metalness: 1, roughness: 0.42, roughnessMap: brushed, bumpMap: brushed, bumpScale: 0.5 })
  const paint = new THREE.MeshPhysicalMaterial({
    color: 0x1f5a3d,
    metalness: 0.55,
    roughness: 0.38,
    clearcoat: 0.8,
    clearcoatRoughness: 0.25,
    side: THREE.FrontSide,
  })
  const innerWall = new THREE.MeshStandardMaterial({ color: 0x2a312d, metalness: 0.9, roughness: 0.55, side: THREE.BackSide })
  const brass = new THREE.MeshStandardMaterial({ color: 0xb8903f, metalness: 1, roughness: 0.32 })
  const darkMetal = new THREE.MeshStandardMaterial({ color: 0x1b201d, metalness: 0.8, roughness: 0.5 })
  const rubber = new THREE.MeshStandardMaterial({ color: 0x0d0f0e, metalness: 0, roughness: 0.95 })
  const plateMat = steel()
  const baseMat = new THREE.MeshStandardMaterial({ color: 0x1c211e, metalness: 0.6, roughness: 0.55 })
  const alu = new THREE.MeshStandardMaterial({ color: 0xc3c9cf, metalness: 1, roughness: 0.3 })

  const cutPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), 3)
  paint.clippingPlanes = [cutPlane]
  paint.clipShadows = true
  innerWall.clippingPlanes = [cutPlane]
  innerWall.clipShadows = true

  /* ── root + parts ── */
  const root = new THREE.Group()
  scene.add(root)
  const parts = new Map<GasGaugePart, Part>()

  const addPart = (
    id: GasGaugePart,
    base: [number, number, number],
    explode: [number, number, number],
    labelText: string | null,
    labelAnchor: [number, number, number],
  ) => {
    const group = new THREE.Group()
    group.position.set(...base)
    root.add(group)
    let label: Part["label"] = null
    if (labelText) {
      const el = document.createElement("button")
      el.type = "button"
      el.textContent = labelText
      el.className = LABEL_CLASS
      el.setAttribute("aria-label", `Inspect ${PART_INFO[id].title}`)
      el.addEventListener("click", () => select(id))
      const obj = new CSS2DObject(el)
      obj.position.set(...labelAnchor)
      group.add(obj)
      label = { obj, el }
    }
    const part: Part = { id, group, base: new THREE.Vector3(...base), explode: new THREE.Vector3(...explode), label }
    parts.set(id, part)
    return group
  }

  /* Cylinder ------------------------------------------------------------- */
  const cylinder = addPart("cylinder", [0, CYL_Y, 0], [0, 3.9, 0], "Level window", [-1.65, 2.6, 0])
  const outerProfile = makeProfile(R, FOOT_H, SHOULDER_Y, NECK_Y, NECK_R)
  const innerProfile = makeProfile(R - WALL, FOOT_H + WALL, SHOULDER_Y, NECK_Y - WALL, NECK_R - WALL)
  const vol = volumeTable(innerProfile)
  cylinder.add(new THREE.Mesh(new THREE.LatheGeometry(outerProfile, 128), paint))
  cylinder.add(new THREE.Mesh(new THREE.LatheGeometry(innerProfile, 96), innerWall))

  const footProfile = [
    new THREE.Vector2(R - 0.34, FOOT_H + 0.02),
    new THREE.Vector2(R - 0.34, 0.03),
    new THREE.Vector2(R - 0.28, 0),
    new THREE.Vector2(R - 0.08, 0),
    new THREE.Vector2(R - 0.02, 0.05),
    new THREE.Vector2(R - 0.02, FOOT_H - 0.04),
    new THREE.Vector2(R - 0.08, FOOT_H),
  ]
  const footMat = darkMetal.clone()
  footMat.side = THREE.DoubleSide
  cylinder.add(new THREE.Mesh(new THREE.LatheGeometry(footProfile, 96), footMat))
  ;[FOOT_H + 0.9, SHOULDER_Y - 0.05].forEach((y) => {
    const seam = new THREE.Mesh(new THREE.TorusGeometry(R + 0.006, 0.022, 8, 128), darkMetal)
    seam.rotation.x = Math.PI / 2
    seam.position.y = y
    cylinder.add(seam)
  })

  // Printed label wrapped around the front of the body
  const labelTex = canvasTexture(1024, 640, (g, w, h) => drawCylinderLabel(g, w, h, initial.capacity))
  textures.push(labelTex)
  const arc = 1.5
  const labelMesh = new THREE.Mesh(
    new THREE.CylinderGeometry(R + 0.006, R + 0.006, 1.9, 64, 1, true, -arc / 2, arc),
    new THREE.MeshStandardMaterial({ map: labelTex, transparent: true, roughness: 0.55, metalness: 0.1, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2 }),
  )
  labelMesh.position.y = 1.95
  ;(labelMesh.material as THREE.MeshStandardMaterial).clippingPlanes = [cutPlane]
  cylinder.add(labelMesh)

  // Level window: a row of LEDs set into a dark housing, with a 0-100 scale
  const WIN_ANGLE = 0.66
  const winH = 2.5
  const winY0 = FOOT_H + 0.75
  const winGroup = new THREE.Group()
  winGroup.position.set(Math.sin(WIN_ANGLE) * R, 0, Math.cos(WIN_ANGLE) * R)
  winGroup.rotation.y = WIN_ANGLE
  cylinder.add(winGroup)
  const housing = new THREE.Mesh(new THREE.BoxGeometry(0.34, winH + 0.2, 0.09), darkMetal)
  housing.position.set(0, winY0 + winH / 2, 0.02)
  winGroup.add(housing)
  const ledMats: THREE.MeshStandardMaterial[] = []
  for (let i = 0; i < LED_COUNT; i++) {
    const m = new THREE.MeshStandardMaterial({ color: 0x0b0e0c, emissive: new THREE.Color(0x000000), emissiveIntensity: 0, roughness: 0.4 })
    ledMats.push(m)
    const seg = new THREE.Mesh(new THREE.BoxGeometry(0.22, (winH / LED_COUNT) * 0.72, 0.05), m)
    seg.position.set(0, winY0 + (i + 0.5) * (winH / LED_COUNT), 0.07)
    winGroup.add(seg)
  }
  const scaleTex = canvasTexture(64, 512, drawLedScale)
  textures.push(scaleTex)
  const scale = new THREE.Mesh(
    new THREE.PlaneGeometry(0.3, winH + 0.2),
    new THREE.MeshBasicMaterial({ map: scaleTex, transparent: true, depthWrite: false }),
  )
  scale.position.set(0.3, winY0 + winH / 2, 0.067)
  winGroup.add(scale)

  /* LPG volume (gas) ---------------------------------------------------- */
  const gas = addPart("gas", [0, CYL_Y, 0], [-4.6, 3.9, 0], "LPG level", [1.4, 1.2, 0])
  const fillPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0)
  const liquidMat = new THREE.MeshPhysicalMaterial({
    color: C.lime,
    emissive: new THREE.Color(C.lime),
    emissiveIntensity: 0.55,
    transparent: true,
    opacity: 0.6,
    roughness: 0.12,
    metalness: 0,
    side: THREE.DoubleSide,
    depthWrite: false,
  })
  liquidMat.clippingPlanes = [fillPlane, cutPlane]
  const fillProfile = makeProfile(R - WALL - 0.03, FOOT_H + WALL + 0.02, SHOULDER_Y, NECK_Y - WALL - 0.02, NECK_R - WALL - 0.03)
  const liquid = new THREE.Mesh(new THREE.LatheGeometry(fillProfile, 96), liquidMat)
  gas.add(liquid)
  const surfaceMat = new THREE.MeshBasicMaterial({ color: C.lime, transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false })
  surfaceMat.clippingPlanes = [cutPlane]
  const surface = new THREE.Mesh(new THREE.CircleGeometry(1, 64), surfaceMat)
  surface.rotation.x = -Math.PI / 2
  gas.add(surface)
  const ringMat = new THREE.MeshBasicMaterial({ color: C.lime })
  ringMat.clippingPlanes = [cutPlane]
  const ring = new THREE.Mesh(new THREE.TorusGeometry(1, 0.014, 8, 96), ringMat)
  ring.rotation.x = Math.PI / 2
  gas.add(ring)
  // flat cross-section shown on the cut face
  const secPts = [...fillProfile, ...[...fillProfile].reverse().map((p) => new THREE.Vector2(-p.x, p.y))]
  const sectionMat = new THREE.MeshBasicMaterial({ color: C.lime, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1 })
  sectionMat.clippingPlanes = [fillPlane]
  const section = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(secPts)), sectionMat)
  gas.add(section)

  /* Collar ------------------------------------------------------------------ */
  const collar = addPart("collar", [0, CYL_Y, 0], [0, 7.6, 0], "Protective collar", [-1.05, 4.9, 0])
  const collarY0 = NECK_Y - 0.1
  const collarH = 0.95
  ;[collarY0 + 0.04, collarY0 + collarH].forEach((y, i) => {
    const t = new THREE.Mesh(new THREE.TorusGeometry(0.92, i === 0 ? 0.09 : 0.07, 14, 64), paint.clone())
    t.rotation.x = Math.PI / 2
    t.position.y = y
    collar.add(t)
  })
  for (let i = 0; i < 4; i++) {
    const a = (i / 4) * Math.PI * 2 + Math.PI / 4
    const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, collarH, 14), paint.clone())
    bar.position.set(Math.cos(a) * 0.92, collarY0 + collarH / 2 + 0.02, Math.sin(a) * 0.92)
    collar.add(bar)
    const bolt = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.075, 0.05, 6), darkMetal)
    bolt.position.set(Math.cos(a) * 0.92, collarY0 + 0.15, Math.sin(a) * 0.92)
    collar.add(bolt)
  }
  const collarBase = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.8, 0.14, 48), darkMetal)
  collarBase.position.y = collarY0 + 0.07
  collar.add(collarBase)

  /* Valve ------------------------------------------------------------------- */
  const valve = addPart("valve", [0, CYL_Y, 0], [0, 9.2, 0], "Valve", [0.75, 5.35, 0])
  const vy = NECK_Y
  const vBody = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.34, 0.7, 40), brass)
  vBody.position.y = vy + 0.35
  valve.add(vBody)
  const hex = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 0.16, 6), brass)
  hex.position.y = vy + 0.1
  valve.add(hex)
  const outlet = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.15, 0.6, 28), brass)
  outlet.rotation.z = Math.PI / 2
  outlet.position.set(0.5, vy + 0.45, 0)
  valve.add(outlet)
  const outletRim = new THREE.Mesh(new THREE.CylinderGeometry(0.19, 0.19, 0.08, 28), brass)
  outletRim.rotation.z = Math.PI / 2
  outletRim.position.set(0.82, vy + 0.45, 0)
  valve.add(outletRim)
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.25, 20), brass)
  stem.position.y = vy + 0.82
  valve.add(stem)
  const knob = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, 0.16, 24), new THREE.MeshStandardMaterial({ color: 0x151816, roughness: 0.7, metalness: 0.2 }))
  knob.position.y = vy + 1.02
  valve.add(knob)
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2
    const rib = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.16, 0.05), darkMetal)
    rib.position.set(Math.cos(a) * 0.35, vy + 1.02, Math.sin(a) * 0.35)
    valve.add(rib)
  }

  /* Weighing plate ------------------------------------------------------------ */
  const plate = addPart("plate", [0, 0, 0], [0, 2.8, 0], "Weighing plate", [-2.3, 0.7, 1.9])
  const plateTop = new THREE.Mesh(slab(4.4, 4.4, 0.16, 0.24, 0.03), plateMat)
  plateTop.position.y = 0.6 + 0.03
  plate.add(plateTop)
  const mat = new THREE.Mesh(new THREE.CylinderGeometry(1.75, 1.75, 0.03, 64), rubber)
  mat.position.y = CYL_Y - 0.015
  plate.add(mat)
  ;[-1, 1].forEach((sx) =>
    [-1, 1].forEach((sz) => {
      const washer = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.15, 0.02, 24), alu)
      washer.position.set(sx * 1.85, 0.82, sz * 1.85)
      plate.add(washer)
      const boltHead = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.07, 6), darkMetal)
      boltHead.position.set(sx * 1.85, 0.86, sz * 1.85)
      plate.add(boltHead)
    }),
  )
  const plateLabelTex = canvasTexture(1024, 96, drawPlateLabel)
  textures.push(plateLabelTex)
  const plateLabel = new THREE.Mesh(
    new THREE.PlaneGeometry(3.4, 0.32),
    new THREE.MeshStandardMaterial({ map: plateLabelTex, transparent: true, roughness: 0.6, metalness: 0.4, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2 }),
  )
  plateLabel.rotation.x = -Math.PI / 2
  plateLabel.position.set(0, 0.825, 1.98)
  plate.add(plateLabel)

  /* Base frame ------------------------------------------------------------------ */
  const base = addPart("base", [0, 0, 0], [0, 0, 0], "Base frame", [2.4, 0.2, 2.0])
  const frame = new THREE.Mesh(slab(4.6, 4.6, 0.2, 0.28, 0.03), baseMat)
  frame.position.y = 0.09 + 0.03
  base.add(frame)
  ;[-1, 1].forEach((sx) =>
    [-1, 1].forEach((sz) => {
      const foot = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.22, 0.09, 24), rubber)
      foot.position.set(sx * 1.9, 0.045, sz * 1.9)
      base.add(foot)
    }),
  )
  for (let i = 0; i < 6; i++) {
    const slot = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.07, 0.5), rubber)
    slot.position.set(2.33, 0.2, -1.4 + i * 0.56)
    base.add(slot)
  }

  /* Load cell ------------------------------------------------------------------- */
  const loadCell = addPart("loadCell", [0, 0, 0], [0, 1.2, 0], "Load cell", [0, 0.75, 0.35])
  const lcBar = new THREE.Mesh(new THREE.BoxGeometry(2.3, 0.26, 0.5), alu)
  lcBar.position.set(0, 0.45, 0)
  loadCell.add(lcBar)
  ;[-0.38, 0.38].forEach((x) => {
    const hole = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.52, 24), rubber)
    hole.rotation.x = Math.PI / 2
    hole.position.set(x, 0.45, 0)
    loadCell.add(hole)
  })
  const gauge = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.16, 0.52), new THREE.MeshStandardMaterial({ color: 0xb4772c, roughness: 0.6 }))
  gauge.position.set(0, 0.45, 0)
  loadCell.add(gauge)
  ;[-0.95, 0.95].forEach((x) => {
    const b = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.06, 6), darkMetal)
    b.position.set(x, 0.6, 0)
    loadCell.add(b)
  })
  const gland = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.2, 20), rubber)
  gland.rotation.z = Math.PI / 2
  gland.position.set(-1.25, 0.45, 0)
  loadCell.add(gland)

  /* HX711 board ----------------------------------------------------------------- */
  const hx = addPart("hx711", [1.4, 0.34, -1.2], [2.4, 1.2, -0.8], "HX711", [0, 0.5, 0])
  const pcbTex = canvasTexture(256, 192, (g, w, h) => {
    g.fillStyle = "#1c7a4a"
    g.fillRect(0, 0, w, h)
    g.fillStyle = "rgba(255,255,255,0.88)"
    g.font = `700 22px ${MONO}`
    g.textAlign = "center"
    g.fillText("HX711", w / 2, h * 0.28)
    g.font = `600 12px ${MONO}`
    g.fillText("LOAD CELL AMP", w / 2, h * 0.4)
    g.font = `600 10px ${MONO}`
    g.textAlign = "left"
    g.fillText("E+ E- A- A+", 14, h * 0.92)
    g.textAlign = "right"
    g.fillText("GND DT SCK VCC", w - 14, h * 0.1)
  })
  textures.push(pcbTex)
  // BoxGeometry material order: +x, -x, +y (top, printed), -y, +z, -z
  const pcbSide = new THREE.MeshStandardMaterial({ color: 0x15693f, roughness: 0.6 })
  const pcbTop = new THREE.MeshStandardMaterial({ map: pcbTex, roughness: 0.55, metalness: 0.1 })
  const pcb = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.05, 0.8), [pcbSide, pcbSide, pcbTop, pcbSide, pcbSide, pcbSide])
  hx.add(pcb)
  const chip = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.06, 0.22), rubber)
  chip.position.set(0, 0.05, -0.02)
  hx.add(chip)
  for (let i = 0; i < 4; i++) {
    const pin = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.1, 0.06), new THREE.MeshStandardMaterial({ color: 0xd2b25a, metalness: 1, roughness: 0.3 }))
    pin.position.set(-0.3 + i * 0.2, 0.07, -0.32)
    hx.add(pin)
    const pin2 = pin.clone()
    pin2.position.set(-0.3 + i * 0.2, 0.07, 0.32)
    hx.add(pin2)
  }
  const terminal = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.14, 0.18), new THREE.MeshStandardMaterial({ color: 0x1f4fa8, roughness: 0.5 }))
  terminal.position.set(-0.2, 0.09, 0.28)
  hx.add(terminal)

  /* Display --------------------------------------------------------------------- */
  const display = addPart("display", [0, 0, 0], [0, 0, 2.4], "Weight display", [0, 0.62, 0.2])
  const bezel = new THREE.Mesh(new THREE.BoxGeometry(1.9, 0.62, 0.34), darkMetal)
  bezel.position.set(0, 0.3, 2.45)
  bezel.rotation.x = -0.35
  display.add(bezel)
  const screenTex = canvasTexture(512, 192, (g, w, h) => drawDisplay(g, w, h, initial))
  textures.push(screenTex)
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(1.74, 0.5), new THREE.MeshBasicMaterial({ map: screenTex, toneMapped: false }))
  screen.position.set(0, 0, 0.175)
  bezel.add(screen)

  /* Wires between load cell, HX711 and the outgoing signal cable ------------------- */
  const wireColors = [0xd33b34, 0x151515, 0xf0f0f0, 0x2faa55]
  const outColors = [0xd33b34, 0x151515, 0xe7c23a, 0x3a7fe0]
  const wireMeshes: THREE.Mesh[] = []
  const wireCurves: THREE.CatmullRomCurve3[] = []
  const wireMats = [...wireColors, ...outColors].map((c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.6 }))
  const a = new THREE.Vector3()
  const b = new THREE.Vector3()
  const rebuildWires = () => {
    root.updateMatrixWorld(true)
    wireMeshes.splice(0).forEach((m) => {
      root.remove(m)
      m.geometry.dispose()
    })
    wireCurves.length = 0
    for (let i = 0; i < 4; i++) {
      a.set(-1.35, 0.45, (i - 1.5) * 0.04)
      loadCell.localToWorld(a)
      b.set(-0.4 + i * 0.11, 0.17, 0.28)
      hx.localToWorld(b)
      const mid = a.clone().lerp(b, 0.5)
      mid.y = Math.min(a.y, b.y) - 0.05
      mid.z += 0.18 + i * 0.03
      const curve = new THREE.CatmullRomCurve3([a.clone(), a.clone().add(new THREE.Vector3(-0.2, -0.06, 0.12)), mid, b.clone().add(new THREE.Vector3(0, 0.25, 0.3)), b.clone()])
      wireCurves.push(curve)
      const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, 28, 0.022, 6, false), wireMats[i])
      mesh.userData.partId = "loadCell"
      root.add(mesh)
      wireMeshes.push(mesh)
    }
    for (let i = 0; i < 4; i++) {
      a.set(-0.3 + i * 0.2, 0.12, -0.32)
      hx.localToWorld(a)
      b.set(a.x + (i - 1.5) * 0.04, 0.2, -2.32)
      const curve = new THREE.CatmullRomCurve3([a.clone(), a.clone().add(new THREE.Vector3(0, 0.18, -0.2)), new THREE.Vector3(a.x, 0.28, (a.z + b.z) / 2), b.clone()])
      wireCurves.push(curve)
      const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, 20, 0.022, 6, false), wireMats[4 + i])
      mesh.userData.partId = "hx711"
      root.add(mesh)
      wireMeshes.push(mesh)
    }
  }
  const pulseMat = new THREE.MeshBasicMaterial({ color: C.lime })
  const pulses: THREE.Mesh[] = []
  for (let i = 0; i < 8; i++) {
    const p = new THREE.Mesh(new THREE.SphereGeometry(0.05, 12, 12), pulseMat)
    p.visible = false
    root.add(p)
    pulses.push(p)
  }

  /* Tag every mesh with its part, shadows, pick list */
  const pickables: THREE.Object3D[] = []
  parts.forEach((part) =>
    part.group.traverse((o) => {
      const mesh = o as THREE.Mesh
      if (mesh.isMesh) {
        mesh.userData.partId = part.id
        const m = mesh.material as THREE.Material
        const decal = (m as THREE.MeshStandardMaterial).transparent && mesh !== liquid
        mesh.castShadow = !decal && mesh !== liquid && mesh !== surface && mesh !== section
        mesh.receiveShadow = !decal
        pickables.push(mesh)
      }
    }),
  )
  liquid.castShadow = false

  /* ── controls ── */
  const controls = new OrbitControls(camera, canvas)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.minDistance = 4
  controls.maxDistance = 28
  controls.maxPolarAngle = Math.PI * 0.495
  controls.screenSpacePanning = false
  controls.autoRotateSpeed = 0.7
  controls.listenToKeyEvents(mount)
  const homePos = new THREE.Vector3()
  const homeTarget = new THREE.Vector3()
  let tween: null | { t0: number; dur: number; p0: THREE.Vector3; p1: THREE.Vector3; q0: THREE.Vector3; q1: THREE.Vector3 } = null
  let idleSince = performance.now()
  controls.addEventListener("start", () => {
    tween = null
    controls.autoRotate = false
    idleSince = performance.now()
    dirty = true
  })
  controls.addEventListener("end", () => {
    idleSince = performance.now()
  })

  const goTo = (v: GasGaugeView, animate: boolean) => {
    const c = CAMERA[v]
    homePos.set(...c.pos)
    homeTarget.set(...c.target)
    if (!animate || reduced) {
      camera.position.copy(homePos)
      controls.target.copy(homeTarget)
      tween = null
    } else {
      tween = { t0: performance.now(), dur: 950, p0: camera.position.clone(), p1: homePos.clone(), q0: controls.target.clone(), q1: homeTarget.clone() }
    }
    controls.update()
    dirty = true
  }

  /* ── view factors (eased in the loop) ── */
  const f = { explode: 0, cut: 0, ghost: 0, ghostShell: 0 }
  const target = { explode: 0, cut: 0, ghost: 0, ghostShell: 0 }
  const applyViewTargets = () => {
    target.explode = view === "exploded" ? 1 : 0
    target.cut = view === "cutaway" ? 1 : 0
    target.ghost = view === "sensor" ? 1 : 0
    target.ghostShell = view === "sensor" ? 1 : 0
    parts.forEach((p) => {
      if (!p.label) return
      const show = LABELS_FOR_VIEW[view].includes(p.id)
      p.label.obj.visible = show
      p.label.el.tabIndex = show ? 0 : -1
    })
    dirty = true
  }

  const setView = (v: GasGaugeView, animate: boolean) => {
    view = v
    applyViewTargets()
    goTo(v, animate)
    controls.autoRotate = false
    idleSince = performance.now()
  }

  /* ── live state ── */
  const colorNow = new THREE.Color(C.lime)
  const colorTarget = new THREE.Color(C.lime)
  let levelTarget = 0
  let levelShown = 0
  let hasLevel = false
  let lastScreenKey = ""
  let lastLabelKey = ""

  const setLive = (s: LiveState) => {
    live = s
    hasLevel = finite(s.level)
    levelTarget = hasLevel ? clamp(s.level as number, 0, 100) : 0
    const status = statusOf(levelTarget, s.low, s.critical)
    colorTarget.set(!s.connected || !hasLevel ? C.idle : STATUS_COLOR[status])
    const key = [s.weight?.toFixed(2), s.level?.toFixed(0), s.connected, s.source, s.low, s.critical].join("|")
    if (key !== lastScreenKey) {
      lastScreenKey = key
      redraw(screenTex, (g, w, h) => drawDisplay(g, w, h, live))
    }
    const capKey = String(s.capacity)
    if (capKey !== lastLabelKey) {
      lastLabelKey = capKey
      redraw(labelTex, (g, w, h) => drawCylinderLabel(g, w, h, live.capacity))
    }
    dirty = true
  }

  /* ── selection + hover ── */
  let selBox: THREE.BoxHelper | null = null
  const select = (id: GasGaugePart | null) => {
    selected = id
    if (selBox) {
      scene.remove(selBox)
      selBox.geometry.dispose()
      ;(selBox.material as THREE.Material).dispose()
      selBox = null
    }
    const p = id ? parts.get(id) : null
    if (p) {
      selBox = new THREE.BoxHelper(p.group, C.lime)
      scene.add(selBox)
    }
    cb.onSelect(id)
    dirty = true
  }

  const ray = new THREE.Raycaster()
  const ndc = new THREE.Vector2()
  const pick = (ev: PointerEvent): GasGaugePart | null => {
    const r = canvas.getBoundingClientRect()
    ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1)
    ray.setFromCamera(ndc, camera)
    const hit = ray.intersectObjects(pickables, false).find((h) => {
      const m = (h.object as THREE.Mesh).material as THREE.Material & { opacity?: number }
      return h.object.visible && (m.opacity ?? 1) > 0.3
    })
    return (hit?.object.userData.partId as GasGaugePart | undefined) ?? null
  }
  let down: { x: number; y: number; t: number } | null = null
  let hoverPending = false
  const onDown = (e: PointerEvent) => {
    down = { x: e.clientX, y: e.clientY, t: performance.now() }
  }
  const onUp = (e: PointerEvent) => {
    if (!down) return
    const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y)
    const quick = performance.now() - down.t < 600
    down = null
    if (moved < 5 && quick) {
      const id = pick(e)
      select(id === selected ? null : id)
    }
  }
  const onMove = (e: PointerEvent) => {
    if (hoverPending || down) return
    hoverPending = true
    requestAnimationFrame(() => {
      hoverPending = false
      if (disposed) return
      const id = pick(e)
      if (id !== hovered) {
        hovered = id
        canvas.style.cursor = id ? "pointer" : ""
        dirty = true
      }
    })
  }
  canvas.addEventListener("pointerdown", onDown)
  canvas.addEventListener("pointerup", onUp)
  canvas.addEventListener("pointermove", onMove)
  const onLost = (e: Event) => {
    e.preventDefault()
    cb.onContextLost()
  }
  canvas.addEventListener("webglcontextlost", onLost)

  /* ── sizing, visibility ── */
  const resize = () => {
    const w = Math.max(1, mount.clientWidth)
    const h = Math.max(1, mount.clientHeight)
    renderer.setSize(w, h, false)
    labelRenderer.setSize(w, h)
    camera.aspect = w / h
    camera.fov = camera.aspect < 0.9 ? 58 : camera.aspect < 1.3 ? 46 : 38
    camera.updateProjectionMatrix()
    dirty = true
  }
  const ro = new ResizeObserver(resize)
  ro.observe(mount)
  const io = new IntersectionObserver((entries) => {
    visible = entries.some((en) => en.isIntersecting) && !document.hidden
    dirty = true
  })
  io.observe(mount)
  const onVis = () => {
    visible = !document.hidden
    dirty = true
  }
  document.addEventListener("visibilitychange", onVis)

  /* ── render loop ── */
  const approach = (cur: number, tgt: number, rate: number, dt: number) => {
    if (reduced) return tgt
    const next = cur + (tgt - cur) * (1 - Math.exp(-dt * rate))
    return Math.abs(tgt - next) < 0.001 ? tgt : next
  }
  let last = performance.now()
  let wiresKey = -1

  const tick = (now: number) => {
    raf = requestAnimationFrame(tick)
    if (!visible || disposed) return
    const dt = Math.min(0.05, (now - last) / 1000)
    last = now
    let animating = false

    // level + colour
    if (Math.abs(levelTarget - levelShown) > 0.02) {
      levelShown = reduced ? levelTarget : levelShown + (levelTarget - levelShown) * (1 - Math.exp(-dt * 4))
      animating = true
    } else if (levelShown !== levelTarget) {
      levelShown = levelTarget
      animating = true
    }
    if (Math.abs(colorNow.r - colorTarget.r) + Math.abs(colorNow.g - colorTarget.g) + Math.abs(colorNow.b - colorTarget.b) > 0.004) {
      colorNow.lerp(colorTarget, reduced ? 1 : 1 - Math.exp(-dt * 6))
      animating = true
    } else {
      colorNow.copy(colorTarget)
    }

    // view factors
    ;(Object.keys(f) as (keyof typeof f)[]).forEach((k) => {
      if (f[k] !== target[k]) {
        f[k] = approach(f[k], target[k], 3.2, dt)
        animating = true
      }
    })
    const ex = ease(f.explode)
    parts.forEach((p) => p.group.position.copy(p.base).addScaledVector(p.explode, ex))
    cutPlane.constant = lerp(3, 0, ease(f.cut))
    const dim = live.connected ? 1 : 0.55

    // fill
    const fillLocal = yAtFraction(vol, (levelShown / 100) * FILL_LIMIT)
    const showFill = hasLevel && levelShown > 0.05
    liquid.visible = surface.visible = ring.visible = showFill
    section.visible = showFill
    if (showFill) {
      fillPlane.constant = gas.position.y + fillLocal
      const rr = Math.max(0.05, radiusAtY(fillProfile, fillLocal))
      surface.position.y = ring.position.y = fillLocal
      surface.scale.set(rr, rr, 1)
      ring.scale.set(rr, rr, 1)
      if (!reduced) {
        const wob = Math.sin(now / 900) * 0.006
        surface.position.y += wob
        ring.position.y += wob
      }
    }
    liquidMat.color.copy(colorNow)
    liquidMat.emissive.copy(colorNow)
    liquidMat.emissiveIntensity = 0.55 * dim
    liquidMat.opacity = 0.62 * dim
    surfaceMat.color.copy(colorNow)
    surfaceMat.opacity = 0.85 * dim
    ringMat.color.copy(colorNow)
    sectionMat.color.copy(colorNow)
    sectionMat.opacity = 0.38 * ease(f.cut) * dim

    // LEDs
    for (let i = 0; i < LED_COUNT; i++) {
      const frac = clamp((levelShown - i * (100 / LED_COUNT)) / (100 / LED_COUNT), 0, 1)
      const m = ledMats[i]
      m.emissive.copy(frac > 0 ? colorNow : new THREE.Color(0x000000))
      m.emissiveIntensity = frac * 2.4 * dim
    }

    // ghosting (sensor view)
    const ghostP = ease(f.ghost)
    const ghostS = ease(f.ghostShell)
    const setGhost = (mat: THREE.Material, amount: number, min: number) => {
      const o = lerp(1, min, amount)
      const wantT = amount > 0.001
      if (mat.transparent !== wantT) {
        mat.transparent = wantT
        mat.depthWrite = !wantT
        mat.needsUpdate = true
      }
      mat.opacity = o
    }
    setGhost(plateMat, ghostP, 0.1)
    setGhost(paint, ghostS, 0.16)
    setGhost(innerWall, ghostS, 0.12)
    setGhost(footMat, ghostS, 0.2)

    // display glow follows status
    displayGlow.color.copy(colorNow)
    displayGlow.intensity = 1.3 * dim

    // wires and pulses
    const wk = Math.round(ex * 1000)
    if (wk !== wiresKey) {
      wiresKey = wk
      rebuildWires()
    }
    const pulsing = live.connected && !reduced && (view === "sensor" || view === "exploded")
    pulses.forEach((p, i) => {
      p.visible = pulsing
      if (pulsing) {
        const curve = wireCurves[i % wireCurves.length]
        if (curve) p.position.copy(curve.getPoint(((now / 1800 + i * 0.37) % 1 + 1) % 1))
      }
    })
    if (pulsing) animating = true

    // camera tween + autorotate
    if (tween) {
      const t = clamp((now - tween.t0) / tween.dur, 0, 1)
      const e = ease(t)
      camera.position.lerpVectors(tween.p0, tween.p1, e)
      controls.target.lerpVectors(tween.q0, tween.q1, e)
      if (t >= 1) tween = null
      animating = true
    }
    if (!reduced && view === "cylinder" && !tween && now - idleSince > 6000 && !selected) controls.autoRotate = true
    else controls.autoRotate = false
    if (controls.autoRotate) animating = true
    const moved = controls.update()

    if (selBox) {
      selBox.update()
      animating = true
    }
    // hovered label hint
    parts.forEach((p) => {
      if (p.label) p.label.el.style.borderColor = p.id === selected ? C.lime : p.id === hovered ? "rgba(198,241,53,0.8)" : ""
    })
    if (animating || moved || dirty) {
      dirty = false
      renderer.render(scene, camera)
      labelRenderer.render(scene, camera)
    }
  }

  /* ── start ── */
  setLive(initial)
  levelShown = levelTarget
  colorNow.copy(colorTarget)
  setView(startView, false)
  resize()
  raf = requestAnimationFrame(tick)

  const api: SceneApi = {
    setView,
    resetCamera: () => goTo(view, true),
    setLive,
    setReducedMotion: (r) => {
      reduced = r
      dirty = true
    },
    select,
    dispose: () => {
      if (disposed) return
      disposed = true
      cancelAnimationFrame(raf)
      ro.disconnect()
      io.disconnect()
      document.removeEventListener("visibilitychange", onVis)
      canvas.removeEventListener("pointerdown", onDown)
      canvas.removeEventListener("pointerup", onUp)
      canvas.removeEventListener("pointermove", onMove)
      canvas.removeEventListener("webglcontextlost", onLost)
      controls.dispose()
      if (selBox) {
        selBox.geometry.dispose()
        ;(selBox.material as THREE.Material).dispose()
      }
      scene.traverse((o) => {
        const mesh = o as THREE.Mesh
        if (mesh.geometry) mesh.geometry.dispose()
        const mats = mesh.material ? (Array.isArray(mesh.material) ? mesh.material : [mesh.material]) : []
        mats.forEach((m) => {
          ;(["map", "bumpMap", "roughnessMap", "alphaMap"] as const).forEach((k) => {
            const t = (m as THREE.MeshStandardMaterial)[k]
            if (t) t.dispose()
          })
          m.dispose()
        })
      })
      textures.forEach((t) => t.dispose())
      envTarget.dispose()
      pmrem.dispose()
      envScene.traverse((o) => {
        const mesh = o as THREE.Mesh
        if (mesh.geometry) mesh.geometry.dispose()
        const m = mesh.material as THREE.Material | undefined
        if (m) m.dispose()
      })
      parts.forEach((p) => p.label?.el.remove())
      renderer.dispose()
      renderer.forceContextLoss()
      canvas.remove()
      labelRenderer.domElement.remove()
    },
  }
  return api
}

/* ───────────────────────────── React component ───────────────────────────── */

function usePrefersReducedMotion() {
  const [reduced, setReduced] = React.useState(false)
  React.useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)")
    setReduced(mq.matches)
    const h = (e: MediaQueryListEvent) => setReduced(e.matches)
    mq.addEventListener("change", h)
    return () => mq.removeEventListener("change", h)
  }, [])
  return reduced
}

export function GasGauge3D({
  gasLevel,
  remainingGas,
  cylinderWeight,
  cylinderCapacity,
  dataSource,
  connectionStatus,
  lowThreshold = 25,
  criticalThreshold = 10,
  initialView = "cylinder",
  onViewChange,
  onPartSelect,
  className,
  height = 520,
}: GasGauge3DProps) {
  const mountRef = React.useRef<HTMLDivElement>(null)
  const apiRef = React.useRef<SceneApi | null>(null)
  const reduced = usePrefersReducedMotion()
  const [view, setView] = React.useState<GasGaugeView>(initialView)
  const [selected, setSelected] = React.useState<GasGaugePart | null>(null)
  const [glError, setGlError] = React.useState<string | null>(null)
  const [sceneKey, setSceneKey] = React.useState(0)
  const [announce, setAnnounce] = React.useState("")

  const live = React.useMemo<LiveState>(
    () => ({
      level: finite(gasLevel) ? gasLevel : null,
      remaining: finite(remainingGas) ? remainingGas : null,
      weight: finite(cylinderWeight) ? cylinderWeight : null,
      capacity: finite(cylinderCapacity) ? cylinderCapacity : null,
      source: dataSource,
      connected: connectionStatus === "connected",
      low: lowThreshold,
      critical: criticalThreshold,
    }),
    [gasLevel, remainingGas, cylinderWeight, cylinderCapacity, dataSource, connectionStatus, lowThreshold, criticalThreshold],
  )

  // latest values for the scene (read when the scene is (re)created)
  const liveRef = React.useRef(live)
  liveRef.current = live
  const viewRef = React.useRef(view)
  viewRef.current = view
  const reducedRef = React.useRef(reduced)
  reducedRef.current = reduced
  const cbRef = React.useRef({ onPartSelect, onViewChange })
  cbRef.current = { onPartSelect, onViewChange }

  // Create the scene once (and again only after a lost WebGL context).
  React.useEffect(() => {
    const mount = mountRef.current
    if (!mount) return
    try {
      apiRef.current = createScene(
        mount,
        {
          onSelect: (p) => {
            setSelected(p)
            cbRef.current.onPartSelect?.(p)
          },
          onContextLost: () => setGlError("The graphics context was lost. Reload the 3D view."),
        },
        liveRef.current,
        viewRef.current,
        reducedRef.current,
      )
      setGlError(null)
    } catch (err) {
      apiRef.current = null
      setGlError(err instanceof Error ? err.message : "WebGL is not available in this browser.")
    }
    return () => {
      apiRef.current?.dispose()
      apiRef.current = null
    }
  }, [sceneKey])

  // New readings only update the existing scene.
  React.useEffect(() => {
    apiRef.current?.setLive(live)
  }, [live])
  React.useEffect(() => {
    apiRef.current?.setReducedMotion(reduced)
  }, [reduced])
  React.useEffect(() => {
    apiRef.current?.setView(view, true)
    cbRef.current.onViewChange?.(view)
  }, [view])

  // Screen-reader summary: only when the band changes or the level moves 5+ points.
  const lastAnnounced = React.useRef<{ band: string; level: number; conn: boolean } | null>(null)
  React.useEffect(() => {
    const level = live.level
    const band = level == null ? "none" : statusOf(level, lowThreshold, criticalThreshold)
    const prev = lastAnnounced.current
    if (!prev || prev.band !== band || prev.conn !== live.connected || (level != null && Math.abs(level - prev.level) >= 5)) {
      lastAnnounced.current = { band, level: level ?? 0, conn: live.connected }
      setAnnounce(
        level == null
          ? "Gas level unavailable."
          : `Gas level ${level.toFixed(0)} percent, ${STATUS_TEXT[band as Status].toLowerCase()}. ${live.connected ? "Sensor connected." : "Sensor disconnected."}`,
      )
    }
  }, [live, lowThreshold, criticalThreshold])

  const level = live.level
  const status: Status | null = level == null ? null : statusOf(level, lowThreshold, criticalThreshold)
  const accent = !live.connected || status == null ? C.idle : STATUS_COLOR[status]
  const chip = SOURCE_CHIP[dataSource]
  const summary = `3D LPG cylinder on a weighing platform. ${announce}`

  return (
    <section
      aria-label="Gas Gauge 3D view"
      className={cn(
        "relative isolate w-full overflow-hidden rounded-[28px] border border-white/10 bg-[#101311] text-[#ecefe8] shadow-[0_24px_80px_-28px_rgba(0,0,0,0.85)]",
        className,
      )}
      style={{ height }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_38%,rgba(47,158,99,0.26),transparent_62%),radial-gradient(ellipse_at_50%_115%,rgba(198,241,53,0.10),transparent_55%)]"
      />
      <div
        ref={mountRef}
        key={sceneKey}
        role="img"
        aria-label={summary}
        tabIndex={0}
        className="absolute inset-0 cursor-grab outline-none focus-visible:ring-2 focus-visible:ring-[#c6f135]/60 active:cursor-grabbing"
      />
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>

      {glError && (
        <div role="alert" className="absolute inset-0 z-20 grid place-items-center bg-[#101311]/95 p-6 text-center">
          <div className="max-w-sm">
            <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-[#f2a93b]">3D view unavailable</p>
            <p className="mt-3 font-mono text-5xl font-semibold" style={{ color: accent }}>
              {fmt(level, 1)}
              <span className="text-xl text-[#8d9791]">%</span>
            </p>
            <p className="mt-2 font-mono text-xs text-[#8d9791]">
              {fmt(remainingGas, 2)} kg remaining · {fmt(cylinderWeight, 2)} kg total
            </p>
            <p className="mt-4 text-xs leading-relaxed text-[#8d9791]">{glError}</p>
            <button
              type="button"
              onClick={() => setSceneKey((k) => k + 1)}
              className="mt-4 rounded-md border border-[#c6f135]/50 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-[#c6f135] hover:bg-[#c6f135]/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#c6f135]"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {/* top-left: provenance + link state */}
      <div className="pointer-events-none absolute left-3 top-3 z-10 flex flex-wrap items-center gap-2 sm:left-5 sm:top-4">
        <span className={cn("rounded-md border bg-[#101311]/80 px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.18em] backdrop-blur-sm", chip.cls)}>
          {chip.text}
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-2 rounded-full border bg-[#101311]/80 px-2.5 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] backdrop-blur-sm",
            live.connected ? "border-[#c6f135]/40 text-[#c6f135]" : "border-[#d0605c]/60 text-[#d0605c]",
          )}
        >
          <i className={cn("size-1.5 rounded-full bg-current", live.connected && !reduced && "animate-pulse")} />
          {live.connected ? "Connected" : "Disconnected"}
        </span>
      </div>

      {/* top-right: view controls */}
      <div className="absolute right-3 top-3 z-10 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center justify-end gap-2 sm:right-5 sm:top-4">
        <div role="group" aria-label="View mode" className="flex flex-wrap rounded-xl border border-white/10 bg-[#101311]/80 p-0.5 backdrop-blur-md">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              aria-pressed={view === v.id}
              onClick={() => setView(v.id)}
              className={cn(
                "rounded-[10px] px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#c6f135]",
                view === v.id ? "bg-[#c6f135] text-[#0e1a10]" : "text-[#9aa49d] hover:text-[#ecefe8]",
              )}
            >
              {v.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => apiRef.current?.resetCamera()}
          className="rounded-xl border border-white/10 bg-[#101311]/80 px-2.5 py-2 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-[#9aa49d] backdrop-blur-md transition-colors hover:text-[#c6f135] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#c6f135]"
        >
          Reset camera
        </button>
      </div>

      {!live.connected && (
        <div className="pointer-events-none absolute left-1/2 top-16 z-10 -translate-x-1/2 rounded-md border border-[#d0605c]/60 bg-[#d0605c]/15 px-3 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.2em] text-[#ff9b94] backdrop-blur-sm sm:top-14">
          No signal · showing last values
        </div>
      )}

      {/* bottom-left: readout */}
      <div className="pointer-events-none absolute bottom-3 left-3 z-10 sm:bottom-5 sm:left-5">
        <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-[#8d9791]">Remaining gas</p>
        <p className="font-mono text-5xl font-semibold leading-none tracking-tight sm:text-6xl" style={{ color: accent }}>
          {fmt(level, 1)}
          <span className="ml-1 text-xl text-[#8d9791]">%</span>
        </p>
        <p className="mt-2 font-mono text-xs text-[#ecefe8]">
          {fmt(remainingGas, 2)} kg <span className="text-[#8d9791]">of {fmt(cylinderCapacity, 1)} kg</span>
        </p>
        <p className="font-mono text-[11px] text-[#8d9791]">Total weight {fmt(cylinderWeight, 2)} kg</p>
        {status && (
          <span
            className="mt-2 inline-block rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-[0.18em]"
            style={{ color: accent, borderColor: `${accent}88`, background: `${accent}18` }}
          >
            {STATUS_TEXT[status]}
          </span>
        )}
      </div>

      {/* bottom-right: part info or hint */}
      <div className="absolute bottom-[5.5rem] left-3 right-3 z-10 sm:bottom-5 sm:left-auto sm:right-5 sm:max-w-xs">
        {selected ? (
          <div className="rounded-xl border border-[#c6f135]/40 bg-[#101311]/85 p-3 backdrop-blur-md">
            <div className="flex items-start justify-between gap-3">
              <p className="font-mono text-[11px] font-bold uppercase tracking-[0.16em] text-[#c6f135]">{PART_INFO[selected].title}</p>
              <button
                type="button"
                aria-label="Close part details"
                onClick={() => apiRef.current?.select(null)}
                className="-mr-1 -mt-1 rounded px-1.5 font-mono text-sm text-[#8d9791] hover:text-[#ecefe8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#c6f135]"
              >
                ×
              </button>
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-[#c9d0ca]">{PART_INFO[selected].text}</p>
          </div>
        ) : (
          <p className="pointer-events-none text-right font-mono text-[9px] sm:text-[10px] uppercase leading-relaxed tracking-[0.16em] text-[#6d786f]">
            Drag to rotate · Pinch/scroll to zoom
            <br />
            Click a part to inspect
          </p>
        )}
      </div>
    </section>
  )
}

export default GasGauge3D
