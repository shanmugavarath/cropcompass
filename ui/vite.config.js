import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      // Include the fonts directory in the precache manifest
      includeAssets: ['sapling.svg', 'fonts/**/*'],
      manifest: {
        name: 'CropCompass',
        short_name: 'CropCompass',
        description: 'Multilingual crop advisory for Indian smallholder farmers',
        theme_color: '#3A7D44',
        background_color: '#F7F3EE',
        display: 'standalone',
        start_url: '/chat',
        icons: [
          {
            src: 'sapling.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'any maskable',
          },
        ],
      },
      workbox: {
        // Cache the app shell (HTML, JS, CSS) with stale-while-revalidate
        globPatterns: ['**/*.{js,css,html,svg,woff2}'],
        runtimeCaching: [
          {
            // Cache API advisory/forecast responses for offline access to last result
            urlPattern: /\/api\/(forecast|profile)\//,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'cropcompass-api',
              expiration: { maxEntries: 20, maxAgeSeconds: 60 * 60 * 24 }, // 24h
            },
          },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
})
