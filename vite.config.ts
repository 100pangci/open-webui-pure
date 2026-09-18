import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const backendTarget = process.env.WEBUI_BACKEND_URL || 'http://localhost:8080';

export default defineConfig({
	plugins: [sveltekit()],
	define: {
		APP_VERSION: JSON.stringify(process.env.npm_package_version),
		APP_BUILD_HASH: JSON.stringify(process.env.APP_BUILD_HASH || 'dev-build')
	},
	build: {
		sourcemap: false
	},
	server: {
		proxy: {
			'/api': {
				target: backendTarget,
				changeOrigin: true,
				ws: true
			},
			'/openai': {
				target: backendTarget,
				changeOrigin: true
			},
			'/oauth': {
				target: backendTarget,
				changeOrigin: true
			},
			'/ws': {
				target: backendTarget,
				changeOrigin: true,
				ws: true
			}
		}
	},
	worker: {
		format: 'es'
	},
	esbuild: {
		pure: process.env.ENV === 'dev' ? [] : ['console.log', 'console.debug', 'console.error']
	}
});
