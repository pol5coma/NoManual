import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Pinned so this project always answers on the same origin. Without
    // strictPort, Vite silently moves to the next free port when another
    // project already holds this one, and the API then rejects the preflight
    // for an origin it was never told about.
    port: 5174,
    strictPort: true,
  },
})
