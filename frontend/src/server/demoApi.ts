/**
 * Server-only adapter that runs the original PauseGuard mock middleware
 * (mocks/payment-api.ts, unchanged) behind TanStack Start's request middleware.
 * It serves the same /api/v2 and demo-account paths the original Vite plugin did,
 * in memory, for this preview. With VITE_USE_REAL_BACKEND=true or PAUSEGUARD_MODE=backend
 * the mock is skipped and /api/v2 is forwarded to PAUSEGUARD_BACKEND_URL instead.
 */
import { createMockApi } from "../../mocks/payment-api.ts";
import { demoAccountPath } from "../types/account.ts";

type MockHandler = ReturnType<typeof createMockApi>;
let handler: MockHandler | undefined;

function isLoopback(hostname: string) {
  return (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "::1" ||
    hostname === "[::1]"
  );
}

export async function handleDemoApi(request: Request): Promise<Response | undefined> {
  const url = new URL(request.url);
  const path = url.pathname;
  const api = path.startsWith("/api/v2/");
  const demo = path.startsWith(`${demoAccountPath}/`);
  if (!api && !demo) return undefined;

  const realBackend =
    process.env["VITE_USE_REAL_BACKEND"] === "true" || process.env["PAUSEGUARD_MODE"] === "backend";
  if (realBackend) {
    if (!api) return undefined;
    // Same boundary as the original proxy: demo auth endpoints stay loopback-only.
    if (path.startsWith("/api/v2/demo/") && !isLoopback(url.hostname)) {
      return Response.json(
        { detail: "Demo endpoints are only available on loopback." },
        { status: 403 },
      );
    }
    const target =
      (process.env["PAUSEGUARD_BACKEND_URL"] || "http://127.0.0.1:8000") + path + url.search;
    return fetch(new Request(target, request));
  }

  handler ??= createMockApi();
  const bytes =
    request.method === "GET" || request.method === "HEAD"
      ? new Uint8Array()
      : new Uint8Array(await request.arrayBuffer());
  const headers: Record<string, string> = {};
  request.headers.forEach((value, key) => {
    headers[key] = value;
  });

  const incoming = {
    url: path + url.search,
    method: request.method,
    headers,
    async *[Symbol.asyncIterator]() {
      if (bytes.length) yield bytes;
    },
  };

  return new Promise<Response>((resolve) => {
    const out = new Headers();
    let status = 200;
    const outgoing = {
      setHeader(name: string, value: string | number) {
        out.set(name, String(value));
      },
      writeHead(code: number, extra?: Record<string, string | number>) {
        status = code;
        for (const [name, value] of Object.entries(extra ?? {})) out.set(name, String(value));
        return outgoing;
      },
      end(chunk?: string) {
        resolve(
          new Response(status === 204 || status === 304 ? null : (chunk ?? null), {
            status,
            headers: out,
          }),
        );
      },
    };
    handler!(incoming as never, outgoing as never, () =>
      resolve(
        Response.json({ detail: "Not found in the PauseGuard demo service." }, { status: 404 }),
      ),
    );
  });
}
