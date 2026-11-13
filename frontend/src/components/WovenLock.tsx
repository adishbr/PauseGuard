import { useEffect, useRef } from 'react'
import { Icon } from './Icon.tsx'
import { THEME_CHANGE_EVENT } from '../services/theme.ts'

const darkColors = ['#70f2dd', '#8699ff', '#d7aaff', '#ffe0bc']
const lightColors = ['#0d9488', '#4338ca', '#7e22ce', '#c2410c']

interface LockData {
  count: number
  baseX: Float32Array
  baseY: Float32Array
  baseZ: Float32Array
  dispX: Float32Array
  dispY: Float32Array
  dispZ: Float32Array
  velX: Float32Array
  velY: Float32Array
  velZ: Float32Array
  threadIdx: Uint8Array
  layerIdx: Uint8Array
  shimmerPhase: Float32Array
}

function buildLockGeometry(): LockData {
  type RawPoint = { x: number; y: number; z: number; layer: number }
  const rawPoints: RawPoint[] = []

  // 1. Shackle: Sweep circular cross-section along arch and down legs
  for (let step = 0; step <= 104; step += 1) {
    const distance = (step / 104) * (Math.PI * 0.56 + 0.72)
    const angle = Math.min(Math.PI, Math.max(0, (distance - 0.36) / 0.56))
    const leg = Math.max(0.36 - distance, distance - 0.36 - Math.PI * 0.56, 0)
    for (let strand = 0; strand < 16; strand += 1) {
      const twist = (strand * Math.PI) / 8 + distance * 3.4
      const radius = 0.56 + 0.115 * Math.cos(twist)
      rawPoints.push({
        x: radius * Math.cos(angle),
        y: 0.47 + radius * Math.sin(angle) - leg,
        z: 0.115 * Math.sin(twist),
        layer: 1, // shackle layer
      })
    }
  }

  // 2. Lock Body: Front and back faces with keyhole void
  for (const z of [-0.26, 0.26]) {
    const layer = z < 0 ? 0 : 2
    for (let row = 0; row <= 34; row += 1) {
      const y = -0.93 + row * 0.036
      for (let col = 0; col <= 44; col += 1) {
        const x = -0.792 + col * 0.036 + (row % 2) * 0.018
        const corner = Math.hypot(Math.max(Math.abs(x) - 0.63, 0), Math.max(Math.abs(y + 0.318) - 0.45, 0))
        const keyhole =
          Math.hypot(x, y + 0.23) < 0.12 ||
          (y < -0.23 && y > -0.61 && Math.abs(x) < 0.055 + (-y - 0.23) * 0.13)
        if (corner <= 0.16 && !keyhole) {
          rawPoints.push({ x, y, z, layer })
        }
      }
    }
  }

  // 3. Lock Body: Rounded sides connecting front and back
  for (let step = 0; step < 152; step += 1) {
    const angle = (step / 152) * Math.PI * 2
    const x = Math.cos(angle)
    const y = Math.sin(angle)
    const scale = 1 / Math.max(Math.abs(x) / 0.63, Math.abs(y) / 0.45)
    for (let strand = 0; strand <= 12; strand += 1) {
      rawPoints.push({
        x: x * (scale + 0.15),
        y: y * (scale + 0.15) - 0.318,
        z: -0.24 + strand * 0.04,
        layer: 1,
      })
    }
  }

  const count = rawPoints.length
  const data: LockData = {
    count,
    baseX: new Float32Array(count),
    baseY: new Float32Array(count),
    baseZ: new Float32Array(count),
    dispX: new Float32Array(count),
    dispY: new Float32Array(count),
    dispZ: new Float32Array(count),
    velX: new Float32Array(count),
    velY: new Float32Array(count),
    velZ: new Float32Array(count),
    threadIdx: new Uint8Array(count),
    layerIdx: new Uint8Array(count),
    shimmerPhase: new Float32Array(count),
  }

  for (let i = 0; i < count; i += 1) {
    const p = rawPoints[i]
    data.baseX[i] = p.x
    data.baseY[i] = p.y
    data.baseZ[i] = p.z
    data.layerIdx[i] = p.layer

    const tone = Math.sin(p.x * 79.2 + p.y * 61.9 + p.z * 48.4) * 4271.3
    data.threadIdx[i] = Math.floor((tone - Math.floor(tone)) * 4) % 4
    data.shimmerPhase[i] = p.x * 9.0 + p.y * 6.0 + p.z * 14.0
  }

  return data
}

export function WovenLock() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return

    const scene = canvas.closest('section') || canvas.parentElement
    const lock = buildLockGeometry()
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)')

    let animId = 0
    let lastTime = 0
    let isVisible = false

    // Camera tilt
    let targetTiltX = 0
    let targetTiltY = 0
    let currentTiltX = 0
    let currentTiltY = 0

    // Pointer state in canvas pixel coordinates
    let pointerCanvasX = -9999
    let pointerCanvasY = -9999
    let prevPointerCanvasX = -9999
    let prevPointerCanvasY = -9999
    let isPointerInside = false
    let isPointerDown = false

    // Theme detection
    function isLightTheme(): boolean {
      return document.documentElement.getAttribute('data-theme') === 'light'
    }

    function onPointerMove(e: PointerEvent) {
      if (motion.matches || !canvas) return
      const rect = canvas.getBoundingClientRect()
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5)

      const px = (e.clientX - rect.left) * ratio
      const py = (e.clientY - rect.top) * ratio

      prevPointerCanvasX = pointerCanvasX === -9999 ? px : pointerCanvasX
      prevPointerCanvasY = pointerCanvasY === -9999 ? py : pointerCanvasY
      pointerCanvasX = px
      pointerCanvasY = py
      isPointerInside = true

      // Tilt normalization (-1 to +1)
      targetTiltX = ((e.clientX - rect.left) / rect.width) * 2 - 1
      targetTiltY = ((e.clientY - rect.top) / rect.height) * 2 - 1
    }

    function onPointerDown(e: PointerEvent) {
      isPointerDown = true
      onPointerMove(e)
    }

    function onPointerUp() {
      isPointerDown = false
    }

    function onPointerLeave() {
      isPointerInside = false
      isPointerDown = false
      targetTiltX = 0
      targetTiltY = 0
      pointerCanvasX = -9999
      pointerCanvasY = -9999
    }

    function render(now: number) {
      animId = 0
      if (!canvas || !ctx || !isVisible || document.hidden) return

      // Throttle to ~30-60 FPS
      if (motion.matches || now - lastTime >= 16) {
        const { clientWidth, clientHeight } = canvas
        const ratio = Math.min(window.devicePixelRatio || 1, 1.5)
        const width = Math.round(clientWidth * ratio)
        const height = Math.round(clientHeight * ratio)

        if (!width || !height) return

        if (canvas.width !== width || canvas.height !== height) {
          canvas.width = width
          canvas.height = height
        }

        const time = motion.matches ? 0 : now * 0.001
        const light = isLightTheme()
        const palette = light ? lightColors : darkColors

        // Smooth camera tilt damping
        currentTiltX += (targetTiltX - currentTiltX) * 0.08
        currentTiltY += (targetTiltY - currentTiltY) * 0.08

        const yaw = -0.30 + Math.sin(time * 0.55) * 0.15 + currentTiltX * 0.28
        const pitch = 0.13 + currentTiltY * 0.20
        const cosYaw = Math.cos(yaw)
        const sinYaw = Math.sin(yaw)
        const cosPitch = Math.cos(pitch)
        const sinPitch = Math.sin(pitch)

        const scale = Math.min(width, height) * 0.34
        const centerX = width * 0.50
        const centerY = height * 0.52

        ctx.clearRect(0, 0, width, height)

        // Draw cursor light aura if pointer is inside
        if (isPointerInside && pointerCanvasX > 0 && pointerCanvasY > 0) {
          const auraRadius = isPointerDown ? 160 * ratio : 120 * ratio
          const aura = ctx.createRadialGradient(
            pointerCanvasX,
            pointerCanvasY,
            0,
            pointerCanvasX,
            pointerCanvasY,
            auraRadius,
          )
          if (light) {
            aura.addColorStop(0, 'rgba(109, 40, 217, 0.24)')
            aura.addColorStop(0.5, 'rgba(139, 92, 246, 0.10)')
            aura.addColorStop(1, 'transparent')
          } else {
            aura.addColorStop(0, 'rgba(112, 242, 221, 0.22)')
            aura.addColorStop(0.5, 'rgba(134, 153, 255, 0.10)')
            aura.addColorStop(1, 'transparent')
          }
          ctx.fillStyle = aura
          ctx.beginPath()
          ctx.arc(pointerCanvasX, pointerCanvasY, auraRadius, 0, Math.PI * 2)
          ctx.fill()
        }

        // Pointer velocity for drag / swipe interaction
        const pointerVelX = pointerCanvasX - prevPointerCanvasX
        const pointerVelY = pointerCanvasY - prevPointerCanvasY
        prevPointerCanvasX = pointerCanvasX
        prevPointerCanvasY = pointerCanvasY

        const interactionRadius = (isPointerDown ? 140 : 105) * ratio
        const springK = 0.075
        const damping = 0.86
        const forceMultiplier = isPointerDown ? 6.5 : 4.0

        const count = lock.count
        const {
          baseX,
          baseY,
          baseZ,
          dispX,
          dispY,
          dispZ,
          velX,
          velY,
          velZ,
          threadIdx,
          layerIdx,
          shimmerPhase,
        } = lock

        // Particle Physics update & render
        for (let i = 0; i < count; i += 1) {
          const bx = baseX[i]
          const by = baseY[i]
          const bz = baseZ[i]

          // Strand idle wave
          const wave = Math.sin(by * 5.0 + bz * 7.0 - time * 1.35) * 0.022

          // Total 3D position with interactive displacement
          const px = bx + dispX[i]
          const py = by + dispY[i]
          const pz = bz + dispZ[i]

          // 3D rotation & projection
          const depth = pz * cosYaw - px * sinYaw
          const projectedX = px * cosYaw + pz * sinYaw + wave
          const projectedY = py * cosPitch - depth * sinPitch
          const perspective = 3.8 / (3.8 - depth)

          const screenX = centerX + projectedX * scale * perspective
          const screenY = centerY - projectedY * scale * perspective

          // Pointer interaction physics in screen space
          if (isPointerInside) {
            const dx = screenX - pointerCanvasX
            const dy = screenY - pointerCanvasY
            const dist = Math.hypot(dx, dy)

            if (dist < interactionRadius && dist > 0.001) {
              const normDist = dist / interactionRadius
              const force = Math.pow(1 - normDist, 1.8) * forceMultiplier

              // Repulsion vector mapped back to 3D space
              const pushX = (dx / dist) * force * 0.02
              const pushY = -(dy / dist) * force * 0.02
              const pushZ = force * 0.015

              velX[i] += pushX
              velY[i] += pushY
              velZ[i] += pushZ

              // Drag velocity transfer
              if (Math.abs(pointerVelX) > 0.5 || Math.abs(pointerVelY) > 0.5) {
                velX[i] += pointerVelX * 0.001 * (1 - normDist)
                velY[i] += -pointerVelY * 0.001 * (1 - normDist)
              }
            }
          }

          // Spring-damper integration
          velX[i] += -dispX[i] * springK
          velY[i] += -dispY[i] * springK
          velZ[i] += -dispZ[i] * springK

          velX[i] *= damping
          velY[i] *= damping
          velZ[i] *= damping

          dispX[i] += velX[i]
          dispY[i] += velY[i]
          dispZ[i] += velZ[i]

          // Shimmer and sizing
          const shimmer = Math.sin(shimmerPhase[i] - time * 2.6)
          const baseSize = (1.15 + 0.5 * (1 + shimmer)) * ratio * perspective
          const proximityBoost = Math.hypot(dispX[i], dispY[i]) * 18.0
          const finalSize = Math.max(1, baseSize + proximityBoost)

          // Alpha blending by layer and theme
          const layer = layerIdx[i]
          let alpha = layer === 0 ? 0.28 : 0.62 + shimmer * 0.3
          if (light) {
            alpha = layer === 0 ? 0.35 : 0.75 + shimmer * 0.25
          }

          ctx.fillStyle = palette[threadIdx[i]]
          ctx.globalAlpha = alpha
          ctx.fillRect(screenX, screenY, finalSize, finalSize)
        }

        // Orbital accent ring particles
        ctx.fillStyle = palette[3]
        const sweep = Math.sin(time * 0.62) * 0.69
        for (let i = 0; i < 54; i += 1) {
          const angle = (i * Math.PI * 2) / 54 + sweep
          const rx = Math.cos(angle) * scale * 1.27
          const ry = Math.sin(angle) * scale * 0.45
          const ringAlpha = 0.15 + 0.4 * Math.pow((1 + Math.cos(angle + time)) / 2, 4)
          ctx.globalAlpha = light ? ringAlpha * 0.85 : ringAlpha
          ctx.fillRect(
            centerX + rx * 0.96 + ry * 0.28,
            centerY + ry - rx * 0.28,
            ratio * 1.2,
            ratio * 1.2,
          )
        }

        ctx.globalAlpha = 1
        if (!canvas.dataset.ready) canvas.dataset.ready = 'true'
        lastTime = now
      }

      if (!motion.matches) {
        animId = requestAnimationFrame(render)
      }
    }

    function scheduleFrame() {
      if (!animId && isVisible && !document.hidden) {
        animId = requestAnimationFrame(render)
      }
    }

    const observer = new IntersectionObserver(([entry]) => {
      isVisible = entry.isIntersecting
      scheduleFrame()
    })
    const resizeObserver = new ResizeObserver(scheduleFrame)

    observer.observe(canvas)
    resizeObserver.observe(canvas)

    motion.addEventListener('change', scheduleFrame)
    document.addEventListener('visibilitychange', scheduleFrame)
    window.addEventListener(THEME_CHANGE_EVENT, scheduleFrame)

    scene?.addEventListener('pointermove', onPointerMove as EventListener)
    scene?.addEventListener('pointerdown', onPointerDown as EventListener)
    window.addEventListener('pointerup', onPointerUp)
    scene?.addEventListener('pointerleave', onPointerLeave)

    return () => {
      cancelAnimationFrame(animId)
      observer.disconnect()
      resizeObserver.disconnect()
      motion.removeEventListener('change', scheduleFrame)
      document.removeEventListener('visibilitychange', scheduleFrame)
      window.removeEventListener(THEME_CHANGE_EVENT, scheduleFrame)
      scene?.removeEventListener('pointermove', onPointerMove as EventListener)
      scene?.removeEventListener('pointerdown', onPointerDown as EventListener)
      window.removeEventListener('pointerup', onPointerUp)
      scene?.removeEventListener('pointerleave', onPointerLeave)
    }
  }, [])

  return (
    <div className="woven-lock" aria-hidden="true">
      <span className="woven-lock-fallback">
        <Icon name="lock" size={136} />
      </span>
      <canvas ref={canvasRef} />
    </div>
  )
}
