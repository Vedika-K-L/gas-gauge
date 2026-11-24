/**
 * Minimal Streamlit custom-component bridge (component API v1), written by hand so the
 * build needs no extra npm package.
 *
 *   iframe -> Streamlit : streamlit:componentReady, streamlit:setFrameHeight
 *   Streamlit -> iframe : streamlit:render { args }
 *
 * The 3D view is display-only, so it never sends a component value back (that would
 * trigger a Python rerun on every click).
 */
import * as React from "react"

export type StreamlitArgs = Record<string, unknown>

const inStreamlit = typeof window !== "undefined" && window.parent !== window

function post(type: string, data: Record<string, unknown> = {}) {
  window.parent.postMessage({ isStreamlitMessage: true, type, ...data }, "*")
}

export const Streamlit = {
  embedded: inStreamlit,
  ready: () => post("streamlit:componentReady", { apiVersion: 1 }),
  setFrameHeight: (height: number) => post("streamlit:setFrameHeight", { height }),
}

/** Latest args sent by Python, or null until the first render message arrives. */
export function useStreamlitArgs(): StreamlitArgs | null {
  const [args, setArgs] = React.useState<StreamlitArgs | null>(null)
  React.useEffect(() => {
    if (!inStreamlit) return
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; args?: StreamlitArgs } | null
      if (data && data.type === "streamlit:render") setArgs(data.args ?? {})
    }
    window.addEventListener("message", onMessage)
    Streamlit.ready()
    return () => window.removeEventListener("message", onMessage)
  }, [])
  return args
}
