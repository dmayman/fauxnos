import { defineConfig } from 'vite'
import { execSync } from 'node:child_process'
import react from '@vitejs/plugin-react'

/* The git branch of the checkout that's building/serving this UI.
 * Captured at config-eval time (dev-server start or `vite build`) from
 * the working tree's HEAD — so with concurrent sessions in separate
 * worktrees (../fauxnos-worktrees/<branch>), the dev-only footer can show
 * which checkout produced the UI you're looking at. Empty string if not
 * a git checkout; the footer hides itself when it's blank. Only consumed
 * under import.meta.env.DEV, so the production bundle never surfaces it. */
function gitBranch() {
  try {
    return execSync('git rev-parse --abbrev-ref HEAD', { encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

export default defineConfig({
  plugins: [react()],
  base: '/static/',
  define: {
    'import.meta.env.VITE_GIT_BRANCH': JSON.stringify(gitBranch()),
  },
  build: {
    outDir: '../web',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://fauxnos000.local:8080',
    },
  },
})
