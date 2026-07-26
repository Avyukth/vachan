import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: './e2e',
	testMatch: 'audio-stop.spec.ts',
	fullyParallel: false,
	retries: 0,
	workers: 1,
	reporter: 'line',
	outputDir: '/tmp/vachan-audio-stop-playwright-results',
	use: {
		baseURL: 'http://127.0.0.1:3021',
		trace: 'retain-on-failure',
		screenshot: 'only-on-failure',
		video: 'off',
		viewport: { width: 1440, height: 1000 },
		launchOptions: {
			args: ['--autoplay-policy=no-user-gesture-required']
		}
	},
	webServer: {
		command: 'bun run build && bun run preview --host 127.0.0.1 --port 3021',
		url: 'http://127.0.0.1:3021',
		reuseExistingServer: false,
		timeout: 30_000
	}
});
