// Pure geometry for the hero ribbon so SSR and client render identical paths.
export const VIEW_W = 800;
export const VIEW_H = 760;
export const RIBBON_LINES = 22;

export const BAR = { w: 118, h: 440, rx: 59, y: 128, leftX: 222, rightX: 460 } as const;
export const DEPTH = { dx: 22, dy: -18 } as const;
export const FLOOR_Y = 624;

const X0 = -60;
const X1 = 860;
const STEP = 14;

export interface RibbonFrame {
  lines: string[];
  body: string;
  pulse: string;
}

/**
 * t: seconds of animation, px/py: eased pointer offset in [-1, 1].
 * The ribbon passes behind the left bar, sags in the gap, and rises across the right bar.
 */
export function ribbonFrame(t: number, px = 0, py = 0): RibbonFrame {
  const pts: Array<Array<[number, number]>> = Array.from({ length: RIBBON_LINES }, () => []);
  for (let x = X0; x <= X1; x += STEP) {
    const u = (x - 400) / 400;
    const gap = Math.exp(-(((x - 400) / 125) ** 2));
    const base =
      372 - 92 * u + 62 * gap + 14 * Math.sin(x * 0.011 + t * 0.8) + py * 16 * Math.exp(-u * u);
    const half = 24 + 32 * Math.exp(-(((x - 400) / 175) ** 2));
    const theta = u * 2.55 + t * 0.42 + px * 0.45;
    const c = Math.cos(theta);
    const s = Math.sin(theta);
    for (let k = 0; k < RIBBON_LINES; k++) {
      const v = (k / (RIBBON_LINES - 1)) * 2 - 1;
      pts[k]!.push([x + v * half * s * 0.45, base + v * half * c]);
    }
  }
  const toPath = (p: Array<[number, number]>) =>
    p.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");
  const lines = pts.map(toPath);
  const first = pts[0]!;
  const last = pts[RIBBON_LINES - 1]!;
  const body =
    toPath(first) +
    [...last]
      .reverse()
      .map(([x, y]) => `L${x.toFixed(1)} ${y.toFixed(1)}`)
      .join("") +
    "Z";
  return { lines, body, pulse: lines[Math.floor(RIBBON_LINES / 2)]! };
}

/** Edge lines read brightest, like light caught on the rim of a ribbon. */
export function lineOpacity(k: number): number {
  const v = Math.abs((k / (RIBBON_LINES - 1)) * 2 - 1);
  return Number((0.14 + 0.66 * v ** 3).toFixed(3));
}
