import { spawn } from 'node:child_process'

const origin = process.env.PAUSEGUARD_TEST_ORIGIN || 'http://127.0.0.1:5173'

async function isPauseGuardServer(url) {
  try {
    const res = await fetch(`${url}/payer`, { signal: AbortSignal.timeout(1500) })
    if (!res.ok) return false
    const html = await res.text()
    return html.includes('PauseGuard') || html.includes('pauseguard')
  } catch {
    return false
  }
}

async function isPortOccupied(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(1500) })
    return res.status !== 0
  } catch {
    return false
  }
}

async function waitForServer(url, timeoutMs = 25000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (await isPauseGuardServer(url)) return true
    await new Promise((r) => setTimeout(r, 500))
  }
  return false
}

async function main() {
  let serverProcess = null

  const alreadyPauseGuard = await isPauseGuardServer(origin)
  if (alreadyPauseGuard) {
    console.log(`PauseGuard Vite server is already running and verified at ${origin}.`)
  } else {
    // Check if port is taken by an unrelated server
    const occupied = await isPortOccupied(origin)
    if (occupied) {
      console.error(
        `Safety error: Port at ${origin} is occupied by an external, non-PauseGuard service.\n` +
        `The test runner will NEVER terminate external processes.\n` +
        `Please stop the external service or configure PAUSEGUARD_TEST_ORIGIN.`
      )
      process.exit(1)
    }

    console.log(`Starting PauseGuard Vite server at ${origin}...`)
    serverProcess = spawn('npx.cmd', ['vite', '--host', '127.0.0.1', '--port', '5173', '--strictPort'], {
      cwd: process.cwd(),
      shell: true,
      stdio: 'pipe',
    })

    serverProcess.stdout.on('data', (d) => {
      const msg = d.toString()
      if (msg.includes('Local:') || msg.includes('ready')) {
        console.log(`[vite] ${msg.trim()}`)
      }
    })
    serverProcess.stderr.on('data', (d) => {
      console.error(`[vite err] ${d.toString().trim()}`)
    })

    const ready = await waitForServer(origin)
    if (!ready) {
      console.error('Failed to reach PauseGuard Vite server within timeout.')
      if (serverProcess) {
        try { process.kill(serverProcess.pid) } catch {}
        try { spawn('taskkill', ['/pid', String(serverProcess.pid), '/f', '/t'], { stdio: 'ignore' }) } catch {}
      }
      process.exit(1)
    }
    console.log('PauseGuard Vite server is healthy and responding.')
  }

  // Pass remaining CLI arguments or default to browser.test.mjs
  const userArgs = process.argv.slice(2)
  const args = userArgs.length > 0 ? userArgs : ['tests/browser.test.mjs']

  console.log(`Executing: node --test ${args.join(' ')}`)
  const testProc = spawn('node', ['--test', ...args], {
    cwd: process.cwd(),
    stdio: 'inherit',
    env: { ...process.env, PAUSEGUARD_TEST_ORIGIN: origin },
  })

  testProc.on('exit', (code) => {
    // Only kill the child process spawned by this runner instance
    if (serverProcess && serverProcess.pid) {
      console.log('Stopping spawned Vite server...')
      try {
        spawn('taskkill', ['/pid', String(serverProcess.pid), '/f', '/t'], { stdio: 'ignore' })
      } catch {}
    }
    process.exit(code ?? 0)
  })
}

main().catch((err) => {
  console.error('Fatal test runner error:', err)
  process.exit(1)
})
