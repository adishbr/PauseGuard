import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import {
  BAR,
  DEPTH,
  FLOOR_Y,
  RIBBON_LINES,
  VIEW_H,
  VIEW_W,
  lineOpacity,
  ribbonFrame,
} from "./ribbon-geometry";

const STATIC_FRAME = ribbonFrame(0);
const MOTION_QUERY =
  "(min-width: 1024px) and (hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)";

function stop(offset: number, color: string, opacity = 1) {
  return <stop offset={offset} style={{ stopColor: `var(${color})`, stopOpacity: opacity }} />;
}

/** Extruded capsule outline: the parallelogram of the end-cap centres, stroked round by the radius. */
const HULL_D = (() => {
  const { w, h, rx, y } = BAR;
  const cx = w / 2;
  const top = y + rx;
  const bottom = y + h - rx;
  return `M${cx} ${top}L${cx + DEPTH.dx} ${top + DEPTH.dy}L${cx + DEPTH.dx} ${bottom + DEPTH.dy}L${cx} ${bottom}Z`;
})();

function GlassBar({ x }: { x: number }) {
  const { w, h, rx, y } = BAR;
  return (
    <g transform={`translate(${x} 0)`}>
      {/* solid glass body behind the front face */}
      <rect
        x={-10}
        y={y + DEPTH.dy - 10}
        width={w + DEPTH.dx + 20}
        height={h - DEPTH.dy + 20}
        fill="url(#pg-bar-depth)"
        mask="url(#pg-hull-mask)"
      />
      <rect
        x={DEPTH.dx}
        y={y + DEPTH.dy}
        width={w}
        height={h}
        rx={rx}
        fill="none"
        stroke="url(#pg-bar-backrim)"
        strokeWidth={1.2}
      />
      {/* front face */}
      <rect x={0} y={y} width={w} height={h} rx={rx} fill="url(#pg-bar-front)" />
      <rect x={0} y={y} width={w} height={h} rx={rx} fill="url(#pg-bar-sheen)" />
      <rect x={0} y={y} width={w} height={h} rx={rx} fill="url(#pg-bar-reflect)" />
      <rect
        x={0}
        y={y}
        width={w}
        height={h}
        rx={rx}
        fill="none"
        stroke="url(#pg-bar-rim)"
        strokeWidth={1.6}
      />
      <rect
        x={6}
        y={y + 6}
        width={w - 12}
        height={h - 12}
        rx={rx - 6}
        fill="none"
        stroke="var(--art-core)"
        strokeOpacity={0.12}
      />
      {/* specular highlights */}
      <rect x={17} y={y + 40} width={11} height={h * 0.58} rx={5.5} fill="url(#pg-spec)" />
      <rect x={34} y={y + 70} width={4} height={h * 0.32} rx={2} fill="url(#pg-spec)" opacity={0.6} />
      <ellipse cx={w * 0.45} cy={y + 20} rx={30} ry={5} fill="var(--art-core)" opacity={0.28} />
      <ellipse cx={w * 0.62} cy={y + h - 26} rx={34} ry={7} fill="var(--art-violet)" opacity={0.35} />
    </g>
  );
}

function FrontFace({ x }: { x: number }) {
  return (
    <rect x={x} y={BAR.y} width={BAR.w} height={BAR.h} rx={BAR.rx} fill="url(#pg-bar-front)" />
  );
}

export function PauseArtwork({ className }: { className?: string }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Array<SVGPathElement | null>>([]);
  const glowRefs = useRef<Array<SVGPathElement | null>>([]);
  const bodyRef = useRef<SVGPathElement>(null);
  const pulseRef = useRef<SVGPathElement>(null);
  const leftRef = useRef<SVGGElement>(null);
  const rightRef = useRef<SVGGElement>(null);
  const [animated, setAnimated] = useState(false);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(MOTION_QUERY);
    const sync = () => setAnimated(media.matches);
    sync();
    media.addEventListener?.("change", sync);
    return () => media.removeEventListener?.("change", sync);
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!animated || !host) return;

    const target = { x: 0, y: 0 };
    const cur = { x: 0, y: 0 };
    const start = performance.now();
    let raf = 0;
    let last = 0;
    let visible = true;

    const apply = (frame: ReturnType<typeof ribbonFrame>) => {
      frame.lines.forEach((d, k) => {
        lineRefs.current[k]?.setAttribute("d", d);
      });
      glowRefs.current[0]?.setAttribute("d", frame.lines[0]!);
      glowRefs.current[1]?.setAttribute("d", frame.lines[RIBBON_LINES - 1]!);
      bodyRef.current?.setAttribute("d", frame.body);
      pulseRef.current?.setAttribute("d", frame.pulse);
    };

    const tick = (now: number) => {
      raf = 0;
      if (!visible || document.hidden) return;
      raf = requestAnimationFrame(tick);
      if (now - last < 33) return; // ~30fps keeps it light
      last = now;
      cur.x += (target.x - cur.x) * 0.07;
      cur.y += (target.y - cur.y) * 0.07;
      apply(ribbonFrame((now - start) / 1000, cur.x, cur.y));
      if (stageRef.current) {
        stageRef.current.style.transform = `perspective(1600px) rotateY(${(cur.x * 5).toFixed(2)}deg) rotateX(${(-cur.y * 3.5).toFixed(2)}deg)`;
      }
      leftRef.current?.setAttribute("transform", `translate(${(-cur.x * 5).toFixed(2)} ${(-cur.y * 3).toFixed(2)})`);
      rightRef.current?.setAttribute("transform", `translate(${(cur.x * 5).toFixed(2)} ${(cur.y * 3).toFixed(2)})`);
    };

    const resume = () => {
      if (!raf && visible && !document.hidden) raf = requestAnimationFrame(tick);
    };

    const onMove = (e: PointerEvent) => {
      const r = host.getBoundingClientRect();
      target.x = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / (r.width / 1.2)));
      target.y = Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / (r.height / 1.2)));
    };

    const io =
      typeof IntersectionObserver === "function"
        ? new IntersectionObserver(([entry]) => {
            visible = entry?.isIntersecting ?? true;
            resume();
          })
        : null;
    io?.observe(host);
    window.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("visibilitychange", resume);
    resume();

    return () => {
      cancelAnimationFrame(raf);
      io?.disconnect();
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("visibilitychange", resume);
      apply(STATIC_FRAME);
      if (stageRef.current) stageRef.current.style.transform = "";
      leftRef.current?.removeAttribute("transform");
      rightRef.current?.removeAttribute("transform");
    };
  }, [animated]);

  const floatA = animated ? "animate-float-slow" : undefined;
  const floatB = animated ? "animate-float-slower" : undefined;

  return (
    <div ref={hostRef} className={cn("relative aspect-[800/760]", className)} aria-hidden="true">
      <div className="canvas-glow absolute inset-[-8%] blur-2xl" />
      <div ref={stageRef} className="relative size-full will-change-transform [transform-style:preserve-3d]">
        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          className="size-full overflow-visible"
          focusable="false"
        >
          <defs>
            <linearGradient id="pg-bar-front" x1="0" y1="0" x2="1" y2="0">
              {stop(0, "--art-cyan", 0.4)}
              {stop(0.16, "--art-glass", 0.28)}
              {stop(0.58, "--art-glass-deep", 0.32)}
              {stop(1, "--art-violet", 0.36)}
            </linearGradient>
            <linearGradient id="pg-bar-sheen" x1="0" y1="0" x2="0" y2="1">
              {stop(0, "--art-core", 0.26)}
              {stop(0.22, "--art-core", 0)}
              {stop(0.7, "--art-violet", 0)}
              {stop(1, "--art-violet", 0.34)}
            </linearGradient>
            <radialGradient id="pg-bar-reflect" cx="0.7" cy="0.85" r="0.6">
              {stop(0, "--art-violet", 0.4)}
              {stop(1, "--art-violet", 0)}
            </radialGradient>
            <linearGradient id="pg-bar-rim" x1="0" y1="0" x2="1" y2="1">
              {stop(0, "--art-cyan", 1)}
              {stop(0.4, "--art-core", 0.55)}
              {stop(0.72, "--art-violet", 0.75)}
              {stop(1, "--art-violet", 0.25)}
            </linearGradient>
            <linearGradient id="pg-bar-backrim" x1="0" y1="0" x2="0" y2="1">
              {stop(0, "--art-cyan", 0.45)}
              {stop(1, "--art-violet", 0.25)}
            </linearGradient>
            <linearGradient id="pg-bar-depth" x1="0" y1="0" x2="1" y2="0.15">
              {stop(0, "--art-glass-deep", 0.55)}
              {stop(0.6, "--art-violet-deep", 0.5)}
              {stop(1, "--art-cyan-deep", 0.42)}
            </linearGradient>
            <linearGradient id="pg-spec" x1="0" y1="0" x2="0" y2="1">
              {stop(0, "--art-core", 0.85)}
              {stop(0.6, "--art-core", 0.15)}
              {stop(1, "--art-core", 0)}
            </linearGradient>
            <linearGradient id="pg-ribbon" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2={VIEW_W} y2="0">
              {stop(0, "--art-violet", 0)}
              {stop(0.12, "--art-violet", 1)}
              {stop(0.36, "--art-cyan", 1)}
              {stop(0.5, "--art-core", 1)}
              {stop(0.66, "--art-cyan", 1)}
              {stop(0.88, "--art-violet", 1)}
              {stop(1, "--art-violet", 0)}
            </linearGradient>
            <linearGradient id="pg-ribbon-body" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2={VIEW_W} y2="0">
              {stop(0, "--art-violet", 0)}
              {stop(0.3, "--art-cyan", 0.12)}
              {stop(0.5, "--art-core", 0.16)}
              {stop(0.7, "--art-violet", 0.12)}
              {stop(1, "--art-violet", 0)}
            </linearGradient>
            <radialGradient id="pg-floor-shadow" cx="0.5" cy="0.5" r="0.5">
              {stop(0, "--art-shadow", 0.7)}
              {stop(1, "--art-shadow", 0)}
            </radialGradient>
            <radialGradient id="pg-floor-light" cx="0.5" cy="0.5" r="0.5">
              {stop(0, "--art-cyan", 0.45)}
              {stop(1, "--art-cyan", 0)}
            </radialGradient>
            <linearGradient id="pg-floor-line" x1="0" y1="0" x2="1" y2="0">
              {stop(0, "--art-floor", 0)}
              {stop(0.5, "--art-floor", 0.45)}
              {stop(1, "--art-floor", 0)}
            </linearGradient>
            <linearGradient
              id="pg-fade"
              gradientUnits="userSpaceOnUse"
              x1="0"
              y1={BAR.y + BAR.h}
              x2="0"
              y2={BAR.y + BAR.h - 170}
            >
              <stop offset="0" stopColor="#fff" stopOpacity="0.9" />
              <stop offset="1" stopColor="#fff" stopOpacity="0" />
            </linearGradient>
            <mask id="pg-hull-mask" maskUnits="userSpaceOnUse" x="-40" y="0" width="240" height={VIEW_H}>
              <path d={HULL_D} fill="#fff" stroke="#fff" strokeWidth={BAR.rx * 2} strokeLinejoin="round" />
            </mask>
            <mask id="pg-reflection-mask" maskUnits="userSpaceOnUse" x="0" y="0" width={VIEW_W} height={VIEW_H}>
              <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#pg-fade)" />
            </mask>
          </defs>

          {/* floor */}
          <ellipse cx="400" cy={FLOOR_Y} rx="330" ry="34" fill="url(#pg-floor-shadow)" />
          <ellipse cx="400" cy={FLOOR_Y + 2} rx="360" ry="40" fill="none" stroke="url(#pg-floor-line)" strokeWidth="1" />
          <ellipse cx={BAR.leftX + BAR.w / 2 + 8} cy={FLOOR_Y - 2} rx="96" ry="11" fill="url(#pg-floor-light)" />
          <ellipse cx={BAR.rightX + BAR.w / 2 + 8} cy={FLOOR_Y - 2} rx="96" ry="11" fill="url(#pg-floor-light)" />

          {/* reflection */}
          <g transform={`translate(0 ${FLOOR_Y * 2 - 18}) scale(1 -1)`} opacity="0.22">
            <g mask="url(#pg-reflection-mask)">
              <FrontFace x={BAR.leftX} />
              <FrontFace x={BAR.rightX} />
            </g>
          </g>

          {/* right bar sits behind the ribbon */}
          <g ref={rightRef}>
            <g className={floatB}>
              <GlassBar x={BAR.rightX} />
            </g>
          </g>

          {/* ribbon of light */}
          <g>
            <path ref={bodyRef} d={STATIC_FRAME.body} fill="url(#pg-ribbon-body)" fillRule="evenodd" />
            {[0, RIBBON_LINES - 1].map((k, i) => (
              <path
                key={`g${k}`}
                ref={(el) => {
                  glowRefs.current[i] = el;
                }}
                d={STATIC_FRAME.lines[k]}
                fill="none"
                stroke="url(#pg-ribbon)"
                strokeWidth={7}
                strokeOpacity={0.14}
                strokeLinecap="round"
              />
            ))}
            {STATIC_FRAME.lines.map((d, k) => (
              <path
                key={k}
                ref={(el) => {
                  lineRefs.current[k] = el;
                }}
                d={d}
                fill="none"
                stroke="url(#pg-ribbon)"
                strokeWidth={k === 0 || k === RIBBON_LINES - 1 ? 1.6 : 0.9}
                strokeOpacity={lineOpacity(k)}
              />
            ))}
            {animated && (
            <path
              ref={pulseRef}
              d={STATIC_FRAME.pulse}
              fill="none"
              stroke="var(--art-core)"
              strokeWidth={1.6}
              strokeLinecap="round"
              strokeDasharray="110 1090"
              strokeOpacity={0.65}
              className="animate-shimmer"
            />
            )}
          </g>

          {/* left bar sits in front: the ribbon glows through its glass */}
          <g ref={leftRef}>
            <g className={floatA}>
              <GlassBar x={BAR.leftX} />
            </g>
          </g>

          {/* dust motes */}
          {[
            [140, 210, 1.6],
            [660, 170, 1.2],
            [710, 420, 1.8],
            [90, 380, 1.1],
            [600, 560, 1.3],
            [380, 96, 1.4],
          ].map(([cx, cy, r], i) => (
            <circle key={i} cx={cx} cy={cy} r={r} fill="var(--art-core)" opacity={0.5} />
          ))}
        </svg>
      </div>
    </div>
  );
}
