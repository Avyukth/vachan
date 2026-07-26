import adapter from '@sveltejs/adapter-auto';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	const environment = loadEnv(mode, '.', '');
	const backendOrigin = environment.VACHAN_BACKEND_ORIGIN || 'http://localhost:8000';
	const backendWebSocketOrigin = backendOrigin.replace(/^http/, 'ws');

	return {
		plugins: [
			sveltekit({
				compilerOptions: {
					// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
					runes: ({ filename }) =>
						filename.split(/[/\\]/).includes('node_modules') ? undefined : true
				},

				// adapter-auto only supports some environments, see https://svelte.dev/docs/kit/adapter-auto for a list.
				// If your environment is not supported, or you settled on a specific environment, switch out the adapter.
				// See https://svelte.dev/docs/kit/adapters for more information about adapters.
				adapter: adapter()
			})
		],
		server: {
			port: 3000,
			strictPort: true,
			allowedHosts: ['sarvam.pathshala.dev'],
			proxy: {
				'/api': {
					target: backendOrigin,
					changeOrigin: true,
					rewrite: (path) => (path === '/api/healthz' ? '/healthz' : path)
				},
				'/ws': {
					target: backendWebSocketOrigin,
					ws: true
				}
			}
		}
	};
});
