// Temporary local-test config (not committed): Library routes go to a local
// branch server on :8091, everything else to the live fauxnos000.
import base from './vite.config.js'
export default {
  ...base,
  server: {
    proxy: {
      '/api/library': 'http://127.0.0.1:8091',
      '/library-art': 'http://127.0.0.1:8091',
      '/api': 'http://192.168.4.36:8080',
    },
  },
}
