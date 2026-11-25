import * as React from "react"
import { createRoot } from "react-dom/client"
import "./index.css"
import {
  GasGauge3D,
  type GasConnectionStatus,
  type GasDataSource,
  type GasGaugeView,
} from "@/components/ui/gas-gauge-3d"
import { Streamlit, useStreamlitArgs, type StreamlitArgs } from "./streamlit"

/** JSON null / missing / strings become NaN, which the component draws as "no data". */
const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : Number.NaN)

const SOURCES: GasDataSource[] = ["wokwi", "hardware", "demo"]
const VIEWS: GasGaugeView[] = ["cylinder", "cutaway", "sensor", "exploded"]

function FromStreamlit() {
  const args = useStreamlitArgs()
  const requested = typeof args?.height === "number" ? (args.height as number) : 520
  // Shorter viewer on phones so the page stays scrollable.
  const [narrow, setNarrow] = React.useState(() => window.innerWidth < 640)
  React.useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 640)
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])
  const height = narrow ? Math.min(requested, 440) : requested

  React.useEffect(() => {
    Streamlit.setFrameHeight(height)
  }, [height])

  if (!args) return null
  return <Viewer args={args} height={height} />
}

function Viewer({ args, height }: { args: StreamlitArgs; height: number }) {
  const source = SOURCES.includes(args.dataSource as GasDataSource) ? (args.dataSource as GasDataSource) : "demo"
  const status: GasConnectionStatus = args.connectionStatus === "connected" ? "connected" : "disconnected"
  const view = VIEWS.includes(args.initialView as GasGaugeView) ? (args.initialView as GasGaugeView) : "cylinder"
  return (
    <GasGauge3D
      gasLevel={num(args.gasLevel)}
      remainingGas={num(args.remainingGas)}
      cylinderWeight={num(args.cylinderWeight)}
      cylinderCapacity={num(args.cylinderCapacity)}
      dataSource={source}
      connectionStatus={status}
      lowThreshold={Number.isFinite(num(args.lowThreshold)) ? num(args.lowThreshold) : 25}
      criticalThreshold={Number.isFinite(num(args.criticalThreshold)) ? num(args.criticalThreshold) : 10}
      mediumThreshold={Number.isFinite(num(args.mediumThreshold)) ? num(args.mediumThreshold) : 60}
      initialView={view}
      height={height}
    />
  )
}

/**
 * Standalone preview for `npm run dev` (outside Streamlit). The sliders only exercise the
 * visual states; they are not sensor data and are never shown inside the dashboard.
 */
function DevPreview() {
  const [level, setLevel] = React.useState(70)
  const [connected, setConnected] = React.useState(true)
  const [source, setSource] = React.useState<GasDataSource>("demo")
  const capacity = 14.2
  const empty = 15
  const remaining = (level / 100) * capacity
  return (
    <div className="min-h-screen bg-[#0b0d0c] p-4 text-[#ecefe8]">
      <GasGauge3D
        gasLevel={level}
        remainingGas={remaining}
        cylinderWeight={empty + remaining}
        cylinderCapacity={capacity}
        dataSource={source}
        connectionStatus={connected ? "connected" : "disconnected"}
        height="min(78vh, 680px)"
      />
      <div className="mx-auto mt-4 flex max-w-3xl flex-wrap items-center gap-4 font-mono text-xs">
        <label className="flex items-center gap-2">
          Level {level}%
          <input type="range" min={0} max={100} value={level} onChange={(e) => setLevel(Number(e.target.value))} />
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={connected} onChange={(e) => setConnected(e.target.checked)} /> connected
        </label>
        <select
          value={source}
          onChange={(e) => setSource(e.target.value as GasDataSource)}
          className="rounded border border-white/20 bg-transparent px-2 py-1"
        >
          {SOURCES.map((s) => (
            <option key={s} value={s} className="text-black">
              {s}
            </option>
          ))}
        </select>
        <span className="text-[#8d9791]">Dev preview only: values here are slider positions, not sensor readings.</span>
      </div>
    </div>
  )
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>{Streamlit.embedded ? <FromStreamlit /> : <DevPreview />}</React.StrictMode>,
)
