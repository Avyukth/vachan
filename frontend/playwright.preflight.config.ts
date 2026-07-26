import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: './e2e',
	fullyParallel: false,
	retries: 0,
	workers: 1,
	reporter: 'line',
	outputDir: '/tmp/vachan-preflight-playwright-results',
	use: {
		baseURL: 'http://127.0.0.1:3024',
		trace: 'retain-on-failure',
		screenshot: 'only-on-failure',
		video: 'off',
		viewport: { width: 1440, height: 1000 },
		permissions: ['microphone'],
		launchOptions: {
			args: [
				'--autoplay-policy=no-user-gesture-required',
				'--use-fake-device-for-media-stream',
				'--use-fake-ui-for-media-stream'
			]
		}
	},
	webServer: [
		{
			command:
				'uv --directory ../backend run uvicorn tests.evidence_e2e_server:app --host 127.0.0.1 --port 8024',
			url: 'http://127.0.0.1:8024/api/cases',
			reuseExistingServer: false,
			timeout: 30_000
		},
		{
			command:
				'VACHAN_BACKEND_ORIGIN=http://127.0.0.1:8024 bun run dev --host 127.0.0.1 --port 3024',
			url: 'http://127.0.0.1:3024',
			reuseExistingServer: false,
			timeout: 30_000
		}
	]
});
