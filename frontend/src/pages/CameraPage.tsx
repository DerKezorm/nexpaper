/**
 * The camera: the edges of the page are found while the camera runs (OpenCV with jscanify in a worker of
 * its own, `public/scanner/worker.js`, loaded only here), the shutter fires by itself once the page holds still, the
 * corners can be pulled by hand, colour, greyscale or black and white, several pages make one document. The page is
 * straightened here (`lib/scan.ts`), the pages become one PDF, and the PDF goes up through the same queue as every other
 * upload (`source=camera`). Without a camera, or without leave to use it, the page says so and offers a file instead.
 */
import { Check, ChevronLeft, Contrast, FileUp, RotateCcw, Zap, ZapOff } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { applyLook, fitWithin, inset, makePdf, MAX_PROBE, MAX_SHOT, order, pageSize, plausible, scale, scanName, steady as stillEnough, tighten, warp, type Look, type PdfPage, type Quad } from '../lib/scan'
import { ACCEPT } from '../lib/formats'
import { useUploads } from '../state/uploads'

type Stage = 'starting' | 'live' | 'adjust' | 'none'
type Edges = 'loading' | 'ready' | 'failed'
/** The photo being looked at: shown from `url`; its pixels stay in a canvas of its own (`shotCanvas`). */
type Shot = { url: string; width: number; height: number }
type Kept = PdfPage & { thumb: string }

const GOLD = '#d9ad7c'
/** How often a frame goes to the edge finder while the camera runs. */
const PROBE_MS = 180
/** How much the ring fills with each frame in which the page held still: about a second and a half to the shutter. */
const STEP = 12
const LOOKS: Look[] = ['color', 'gray', 'bw']
const FILTER: Record<Look, string> = { color: 'none', gray: 'grayscale(1) contrast(1.1)', bw: 'grayscale(1) contrast(2.2) brightness(1.15)' }

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)))
}

function toBlob(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('encode'))), type, quality))
}

export default function CameraPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const uploads = useUploads()
  const video = useRef<HTMLVideoElement>(null)
  const stream = useRef<MediaStream | null>(null)
  const worker = useRef<Worker | null>(null)
  const pending = useRef(false)
  const previous = useRef<Quad | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const shotCanvas = useRef<HTMLCanvasElement | null>(null)
  const [stage, setStage] = useState<Stage>('starting')
  const [why, setWhy] = useState<'insecure' | 'none'>('none')
  const [edges, setEdges] = useState<Edges>('loading')
  const [live, setLive] = useState<Quad | null>(null)
  const [size, setSize] = useState<[number, number]>([0, 0])
  const [steadiness, setSteadiness] = useState(0)
  const [auto, setAuto] = useState(true)
  const [torch, setTorch] = useState<boolean | null>(null)
  const [flash, setFlash] = useState(false)
  const [look, setLook] = useState<Look>('color')
  const [shot, setShot] = useState<Shot | null>(null)
  const [corners, setCorners] = useState<Quad | null>(null)
  const [pages, setPages] = useState<Kept[]>([])
  const [working, setWorking] = useState(false)
  const [problem, setProblem] = useState(false)

  // The camera: the one at the back, as large as it offers up to about 8 megapixels.
  useEffect(() => {
    let alive = true
    const media = navigator.mediaDevices
    if (!window.isSecureContext || !media?.getUserMedia) {
      setWhy(window.isSecureContext ? 'none' : 'insecure')
      setStage('none')
      return
    }
    media
      .getUserMedia({ audio: false, video: { facingMode: { ideal: 'environment' }, width: { ideal: 3264 }, height: { ideal: 2448 } } })
      .then(async (found) => {
        if (!alive) {
          found.getTracks().forEach((track) => track.stop())
          return
        }
        stream.current = found
        const track = found.getVideoTracks()[0]
        const capabilities = (track?.getCapabilities?.() ?? {}) as { torch?: boolean }
        setTorch(capabilities.torch === true)
        const element = video.current
        if (!element) return
        element.srcObject = found
        await element.play().catch(() => undefined)
        setSize([element.videoWidth, element.videoHeight])
        setStage('live')
      })
      .catch(() => alive && setStage('none'))
    return () => {
      alive = false
      stream.current?.getTracks().forEach((track) => track.stop())
      stream.current = null
    }
  }, [])

  // The edge finder, in its worker.
  useEffect(() => {
    let found: Worker
    try {
      found = new Worker('/scanner/worker.js')
    } catch {
      setEdges('failed')
      return
    }
    worker.current = found
    found.onerror = () => setEdges('failed')
    found.onmessage = (event: MessageEvent<{ type: string; corners?: [number, number][] | null }>) => {
      const message = event.data
      if (message.type === 'ready') setEdges('ready')
      else if (message.type === 'failed') setEdges('failed')
      else if (message.type === 'found') {
        pending.current = false
        const element = video.current
        if (!element || !message.corners) {
          previous.current = null
          setLive(null)
          setSteadiness(0)
          return
        }
        const [probeW, probeH] = fitWithin(element.videoWidth, element.videoHeight, MAX_PROBE)
        const quad = order(message.corners)
        if (!plausible(quad, probeW, probeH)) {
          previous.current = null
          setLive(null)
          setSteadiness(0)
          return
        }
        const full = scale(quad, element.videoWidth / probeW, element.videoHeight / probeH)
        const still = stillEnough(previous.current, full, element.videoWidth, element.videoHeight)
        previous.current = full
        setLive(full)
        setSteadiness((value) => (still ? Math.min(100, value + STEP) : 0))
      }
    }
    found.postMessage({ type: 'load' })
    return () => {
      found.terminate()
      worker.current = null
    }
  }, [])
  useEffect(() => {
    if (edges === 'failed') setAuto(false)
  }, [edges])

  // While the camera runs: a small frame now and then to the edge finder.
  useEffect(() => {
    if (stage !== 'live' || edges !== 'ready') return
    const probe = document.createElement('canvas')
    const timer = window.setInterval(() => {
      const element = video.current
      const target = worker.current
      if (!element || !target || pending.current || element.videoWidth === 0) return
      const [width, height] = fitWithin(element.videoWidth, element.videoHeight, MAX_PROBE)
      probe.width = width
      probe.height = height
      const context = probe.getContext('2d', { willReadFrequently: true })
      if (!context) return
      context.drawImage(element, 0, 0, width, height)
      const pixels = context.getImageData(0, 0, width, height).data.buffer
      pending.current = true
      target.postMessage({ type: 'find', id: Date.now(), width, height, pixels }, [pixels])
    }, PROBE_MS)
    return () => {
      window.clearInterval(timer)
      pending.current = false
    }
  }, [stage, edges])

  const capture = useCallback(() => {
    const element = video.current
    if (!element || element.videoWidth === 0) return
    const [width, height] = fitWithin(element.videoWidth, element.videoHeight, MAX_SHOT)
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) return
    context.drawImage(element, 0, 0, width, height)
    const found = previous.current ? scale(previous.current, width / element.videoWidth, height / element.videoHeight) : inset(width, height)
    setCorners(found)
    setSteadiness(0)
    setStage('adjust')
    shotCanvas.current = canvas
    void toBlob(canvas, 'image/jpeg', 0.9).then((blob) => setShot({ url: URL.createObjectURL(blob), width, height }))
  }, [])

  // "Halt still": the ring fills, then the shutter fires on its own.
  useEffect(() => {
    if (auto && stage === 'live' && steadiness >= 100) capture()
  }, [auto, stage, steadiness, capture])

  const forgetShot = () => {
    if (shot) URL.revokeObjectURL(shot.url)
    // A photo of 8 megapixels holds 32 MB in a canvas: it goes as soon as it is not needed.
    if (shotCanvas.current) shotCanvas.current.width = 0
    shotCanvas.current = null
    setShot(null)
    setCorners(null)
    previous.current = null
    setLive(null)
  }

  const keep = async () => {
    const canvas = shotCanvas.current
    if (!shot || !corners || !canvas) return
    setWorking(true)
    setProblem(false)
    await nextFrame()
    try {
      const context = canvas.getContext('2d', { willReadFrequently: true })!
      const source = context.getImageData(0, 0, shot.width, shot.height)
      const [width, height] = pageSize(corners)
      const straight = applyLook(warp(source, tighten(corners), width, height), look)
      const page = document.createElement('canvas')
      page.width = width
      page.height = height
      page.getContext('2d')!.putImageData(new ImageData(straight.data as Uint8ClampedArray<ArrayBuffer>, width, height), 0, 0)
      const jpeg = new Uint8Array(await (await toBlob(page, 'image/jpeg', 0.85)).arrayBuffer())
      const [thumbW, thumbH] = fitWithin(width, height, 160)
      const small = document.createElement('canvas')
      small.width = thumbW
      small.height = thumbH
      small.getContext('2d')!.drawImage(page, 0, 0, thumbW, thumbH)
      const thumb = URL.createObjectURL(await toBlob(small, 'image/jpeg', 0.7))
      page.width = 0
      setPages((before) => [...before, { jpeg, width, height, thumb }])
      forgetShot()
      setStage('live')
    } catch {
      setProblem(true)
    } finally {
      setWorking(false)
    }
  }

  const done = () => {
    if (pages.length === 0) return
    const pdf = makePdf(pages)
    const scan = new File([pdf as Uint8Array<ArrayBuffer>], scanName(new Date()), { type: 'application/pdf' })
    uploads.add([scan], { source: 'camera' })
    pages.forEach((page) => URL.revokeObjectURL(page.thumb))
    navigate('/schnell', { replace: true, state: { notice: pages.length === 1 ? t('phone.camera.uploadedOne') : t('phone.camera.uploadedMany', { count: pages.length }) } })
  }

  const back = () => (window.history.length > 1 ? navigate(-1) : navigate('/schnell'))
  const switchFlash = () => {
    const track = stream.current?.getVideoTracks()[0]
    if (!track || !torch) return
    const next = !flash
    void track.applyConstraints({ advanced: [{ torch: next } as MediaTrackConstraintSet] }).then(() => setFlash(next), () => undefined)
  }

  const title =
    stage === 'adjust' ? t('phone.camera.check') : stage === 'starting' ? t('phone.camera.starting') : !auto || edges !== 'ready' ? t('phone.camera.found') : live ? t('phone.camera.steady') : t('phone.camera.searching')

  if (stage === 'none')
    return (
      <div className="fixed inset-0 flex flex-col bg-[#0d0b09] text-white" data-testid="camera-none">
        <header className="flex items-center px-3 pt-[max(0.75rem,env(safe-area-inset-top))] pb-2">
          <button type="button" onClick={back} className="rounded-full p-2 hover:bg-white/10" aria-label={t('phone.camera.back')}>
            <ChevronLeft size={24} aria-hidden />
          </button>
        </header>
        <div className="mx-auto flex max-w-sm flex-1 flex-col items-center justify-center px-6 text-center">
          <p className="font-display text-2xl font-semibold">{t('phone.camera.noCamera')}</p>
          <p className="mt-2 text-sm text-white/70">{why === 'insecure' ? t('phone.camera.insecure') : t('phone.camera.noCameraText')}</p>
          <button type="button" onClick={() => file.current?.click()} className="mt-6 flex h-12 items-center gap-2 rounded-full px-6 font-bold text-black" style={{ background: GOLD }}>
            <FileUp size={18} aria-hidden /> {t('phone.camera.chooseFile')}
          </button>
          <input
            ref={file}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            data-testid="camera-file"
            tabIndex={-1}
            aria-hidden
            onChange={(event) => {
              const chosen = Array.from(event.target.files ?? [])
              event.target.value = ''
              if (!chosen.length) return
              uploads.add(chosen)
              navigate('/schnell', { replace: true })
            }}
          />
        </div>
      </div>
    )

  return (
    <div className="fixed inset-0 flex flex-col bg-[#0d0b09] text-white" data-testid="camera" data-stage={stage} data-edges={edges}>
      <header className="flex items-center justify-between px-3 pt-[max(0.75rem,env(safe-area-inset-top))] pb-2">
        <button type="button" onClick={back} className="rounded-full p-2 hover:bg-white/10" aria-label={t('phone.camera.back')}>
          <ChevronLeft size={24} aria-hidden />
        </button>
        <p className="text-sm font-semibold" aria-live="polite">
          {title}
        </p>
        <div className="flex gap-1">
          <button type="button" onClick={switchFlash} disabled={!torch} className="rounded-full p-2 hover:bg-white/10 disabled:opacity-40" aria-label={flash ? t('phone.camera.flashOff') : t('phone.camera.flashOn')}>
            {flash ? <Zap size={20} aria-hidden /> : <ZapOff size={20} aria-hidden />}
          </button>
          <button type="button" onClick={() => setLook(LOOKS[(LOOKS.indexOf(look) + 1) % LOOKS.length])} className="rounded-full p-2 hover:bg-white/10" aria-label={t('phone.camera.look')}>
            <Contrast size={20} aria-hidden />
          </button>
        </div>
      </header>

      <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden">
        <video ref={video} playsInline muted className={`h-full w-full object-contain ${stage === 'adjust' ? 'hidden' : ''}`} style={{ filter: FILTER[look] }} data-testid="viewfinder" />
        {stage === 'live' && size[0] > 0 && live && <Outline quad={live} width={video.current?.videoWidth || size[0]} height={video.current?.videoHeight || size[1]} />}
        {stage === 'adjust' && shot && corners && (
          <Adjust shot={shot} corners={corners} onChange={setCorners} filter={FILTER[look]} label={(n) => t('phone.camera.corner', { n })} />
        )}
        {working && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50 text-sm font-semibold" role="status">
            {t('phone.camera.working')}
          </div>
        )}
      </div>

      <div className="px-4 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <div className="mb-3 flex items-center justify-center gap-2 text-xs">
          {LOOKS.map((option) => (
            <button key={option} type="button" aria-pressed={look === option} onClick={() => setLook(option)} className={`rounded-full px-3 py-1 font-semibold ${look === option ? 'bg-white text-black' : 'bg-white/10'}`}>
              {t(`phone.camera.${option}`)}
            </button>
          ))}
        </div>
        {stage !== 'adjust' ? (
          <div className="flex items-center justify-between">
            <div className="flex w-20 -space-x-6" aria-label={t('phone.camera.pages', { count: pages.length })} data-testid="camera-pages" data-count={pages.length}>
              {pages.slice(-3).map((page, index) => (
                <img key={page.thumb} src={page.thumb} alt="" className="w-10 rotate-[-4deg] rounded-[3px] bg-white shadow" style={{ zIndex: index }} />
              ))}
            </div>
            <button type="button" onClick={capture} disabled={stage !== 'live'} className="relative flex h-20 w-20 items-center justify-center rounded-full border-4 border-white disabled:opacity-50" aria-label={t('phone.camera.shutter')}>
              <svg viewBox="0 0 80 80" className="absolute inset-[-4px] h-20 w-20 -rotate-90" aria-hidden>
                <circle cx="40" cy="40" r="38" fill="none" stroke={GOLD} strokeWidth="4" strokeDasharray={`${(steadiness / 100) * 239} 239`} />
              </svg>
              <span className="h-14 w-14 rounded-full bg-white" />
            </button>
            <div className="flex w-20 flex-col items-end gap-1">
              <button
                type="button"
                onClick={() => setAuto(!auto)}
                disabled={edges === 'failed'}
                className={`rounded-full px-2.5 py-1 text-xs font-semibold disabled:opacity-40 ${auto ? 'text-black' : 'bg-white/10'}`}
                style={auto ? { background: GOLD } : undefined}
              >
                {auto ? t('phone.camera.autoOn') : t('phone.camera.autoOff')}
              </button>
              {pages.length > 0 && (
                <button type="button" onClick={done} className="mt-1 rounded-full bg-white px-3 py-1.5 text-sm font-bold text-black">
                  {t('phone.camera.finish', { count: pages.length })}
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center gap-3">
            <button
              type="button"
              disabled={working}
              onClick={() => {
                forgetShot()
                setStage('live')
              }}
              className="flex h-12 items-center gap-2 rounded-full bg-white/10 px-5 font-semibold"
            >
              <RotateCcw size={18} aria-hidden /> {t('phone.camera.again')}
            </button>
            <button type="button" disabled={working || !shot} onClick={() => void keep()} className="flex h-12 items-center gap-2 rounded-full px-6 font-bold text-black" style={{ background: GOLD }}>
              <Check size={18} aria-hidden /> {t('phone.camera.keep', { n: pages.length + 1 })}
            </button>
          </div>
        )}
        <p className="mt-3 text-center text-xs text-white/50">
          {problem ? t('phone.camera.failed') : stage === 'adjust' ? t('phone.camera.hintAdjust') : edges === 'failed' ? t('phone.camera.noEdges') : t('phone.camera.hintLive')}
        </p>
      </div>
    </div>
  )
}

/** The sheet the edge finder sees, drawn over the running camera in its pixels. */
function Outline({ quad, width, height }: { quad: Quad; width: number; height: number }) {
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden data-testid="outline">
      <polygon points={quad.map((point) => point.join(',')).join(' ')} fill="rgb(217 173 124 / 0.18)" stroke={GOLD} strokeWidth={Math.max(3, width / 160)} strokeLinejoin="round" />
    </svg>
  )
}

/** The photo with its four corners to pull, in the photo's own pixels. */
function Adjust({ shot, corners, onChange, filter, label }: { shot: Shot; corners: Quad; onChange: (quad: Quad) => void; filter: string; label: (n: number) => string }) {
  const svg = useRef<SVGSVGElement>(null)
  const [drag, setDrag] = useState<number | null>(null)
  const { width, height } = shot
  const local = (event: PointerEvent): [number, number] | null => {
    const box = svg.current
    const matrix = box?.getScreenCTM()
    if (!box || !matrix) return null
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
    return [Math.min(width, Math.max(0, point.x)), Math.min(height, Math.max(0, point.y))]
  }
  const move = (index: number, point: [number, number]) => onChange(corners.map((corner, at) => (at === index ? point : corner)) as Quad)
  const nudge = (index: number, event: KeyboardEvent) => {
    const step = Math.max(width, height) / 100
    const delta: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }
    const by = delta[event.key]
    if (!by) return
    event.preventDefault()
    const [x, y] = corners[index]
    move(index, [Math.min(width, Math.max(0, x + by[0])), Math.min(height, Math.max(0, y + by[1]))])
  }
  const poly = corners.map((corner) => corner.join(',')).join(' ')
  const radius = Math.max(width, height) / 40
  return (
    <div className="relative h-full w-full">
      <img src={shot.url} alt="" className="absolute inset-0 h-full w-full object-contain" style={{ filter }} />
      <svg
        ref={svg}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        className="absolute inset-0 h-full w-full touch-none"
        data-testid="corners"
        onPointerMove={(event) => {
          if (drag === null) return
          const point = local(event)
          if (point) move(drag, point)
        }}
        onPointerUp={() => setDrag(null)}
        onPointerCancel={() => setDrag(null)}
      >
        <path d={`M0 0H${width}V${height}H0Z M${poly.replace(/ /g, ' L')}Z`} fill="rgb(0 0 0 / 0.45)" fillRule="evenodd" />
        <polygon points={poly} fill="none" stroke={GOLD} strokeWidth={radius / 4} strokeLinejoin="round" />
        {corners.map(([x, y], index) => (
          <circle
            key={index}
            cx={x}
            cy={y}
            r={radius}
            fill="#fff"
            stroke={GOLD}
            strokeWidth={radius / 3}
            className="cursor-grab"
            role="button"
            tabIndex={0}
            aria-label={label(index + 1)}
            data-corner={index}
            onKeyDown={(event) => nudge(index, event)}
            onPointerDown={(event) => {
              ;(event.target as Element).setPointerCapture?.(event.pointerId)
              setDrag(index)
            }}
          />
        ))}
      </svg>
    </div>
  )
}
