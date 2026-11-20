/// <reference types="vitest" />
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig, normalizePath} from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': normalizePath(path.resolve(import.meta.dirname, 'src')),
      },
    },
    build: {
      outDir: normalizePath(path.resolve(import.meta.dirname, '../web/static')),
      emptyOutDir: true,
      rolldownOptions: {
        output: {
          entryFileNames: 'assets/[name].js',
          chunkFileNames: 'assets/[name].js',
          assetFileNames: (assetInfo) => {
            const name = typeof assetInfo === 'string' ? assetInfo : (assetInfo.name || '');
            if (/\.(woff2?|ttf|otf|eot)$/i.test(name)) {
              return 'assets/fonts/[name].[ext]';
            }
            return 'assets/[name].[ext]';
          },
        },
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
    },
    server: {
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/health': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  };
});
