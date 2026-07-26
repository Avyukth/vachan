import { expect, type Page, test } from '@playwright/test';

type AudioProbe = {
	controlAt: number | null;
	events: Array<{ kind: 'start' | 'stop'; at: number; duration: number }>;
};

type ProbedWindow = Window & { __vachanAudioProbe: AudioProbe };

const CALL_ID = 'call-audio-stop-e2e';

function silentWav(seconds = 3): Buffer {
	const sampleRate = 16_000;
	const samples = sampleRate * seconds;
	const pcmBytes = samples * 2;
	const wav = Buffer.alloc(44 + pcmBytes);
	wav.write('RIFF', 0);
	wav.writeUInt32LE(36 + pcmBytes, 4);
	wav.write('WAVEfmt ', 8);
	wav.writeUInt32LE(16, 16);
	wav.writeUInt16LE(1, 20);
	wav.writeUInt16LE(1, 22);
	wav.writeUInt32LE(sampleRate, 24);
	wav.writeUInt32LE(sampleRate * 2, 28);
	wav.writeUInt16LE(2, 32);
	wav.writeUInt16LE(16, 34);
	wav.write('data', 36);
	wav.writeUInt32LE(pcmBytes, 40);
	return wav;
}

async function installAudioProbe(page: Page): Promise<void> {
	await page.addInitScript({
		content: `
			window.__vachanAudioProbe = { controlAt: null, events: [] };
			(() => {
				const prototype = AudioContext.prototype;
				const originalCreateBufferSource = prototype.createBufferSource;
				prototype.createBufferSource = function () {
					const source = originalCreateBufferSource.call(this);
					const originalStart = source.start.bind(source);
					const originalStop = source.stop.bind(source);
					source.start = function (...args) {
						window.__vachanAudioProbe.events.push({
							kind: 'start',
							at: performance.now(),
							duration: source.buffer?.duration ?? 0
						});
						return originalStart(...args);
					};
					source.stop = function (...args) {
						window.__vachanAudioProbe.events.push({
							kind: 'stop',
							at: performance.now(),
							duration: source.buffer?.duration ?? 0
						});
						return originalStop(...args);
					};
					return source;
				};
			})();
		`
	});
}

async function restoreActiveCallWithLongAudio(page: Page): Promise<ReturnType<Page['locator']>> {
	await page.addInitScript(
		({ key, callId }) => sessionStorage.setItem(key, callId),
		{ key: 'vachan.activeCallId', callId: CALL_ID }
	);
	await page.route('**/api/cases', (route) =>
		route.fulfill({
			contentType: 'application/json',
			body: JSON.stringify({
				api_version: 'v0',
				cases: [
					{
						api_version: 'v0',
						case_id: 'case-rakesh-001',
						borrower_display_name: 'Rakesh Yadav',
						eligible: true,
						contact_cap_remaining: 40,
						mock_data: true
					}
				]
			})
		})
	);
	await page.route(`**/api/evidence/${CALL_ID}`, (route) =>
		route.fulfill({
			status: 503,
			contentType: 'application/json',
			body: '{"detail":"injected evidence outage"}'
		})
	);
	await page.route('**/api/audio/check', (route) =>
		route.fulfill({ contentType: 'audio/wav', body: silentWav() })
	);
	await page.goto('/');
	const liveConsole = page.locator('.operator-console').filter({
		hasText: 'LIVE · PERSISTED LEDGER'
	});
	await expect(liveConsole).toBeVisible();
	await expect(liveConsole.getByRole('button', { name: 'End call' })).toBeEnabled();
	await page.getByRole('button', { name: 'Play Bulbul check' }).click();
	await expect(
		page.getByText('Listen through wired headphones. Open speakers are unsafe.')
	).toBeVisible();
	await page.waitForFunction(() =>
		(window as ProbedWindow).__vachanAudioProbe.events.some(
			(event) => event.kind === 'start' && event.duration > 2
		)
	);
	return liveConsole;
}

async function measureStopFromClick(
	page: Page,
	buttonName: 'End call' | 'Break-glass takeover'
): Promise<number> {
	const liveConsole = await restoreActiveCallWithLongAudio(page);
	const button = liveConsole.getByRole('button', { name: buttonName });
	await button.evaluate((element) => {
		element.addEventListener(
			'click',
			() => {
				(window as ProbedWindow).__vachanAudioProbe.controlAt = performance.now();
			},
			{ capture: true, once: true }
		);
	});
	await button.click();
	await page.waitForFunction(() => {
		const probe = (window as ProbedWindow).__vachanAudioProbe;
		return (
			probe.controlAt !== null &&
			probe.events.some(
				(event) =>
					event.kind === 'stop' && event.duration > 2 && event.at >= (probe.controlAt ?? Infinity)
			)
		);
	});
	return await page.evaluate(() => {
		const probe = (window as ProbedWindow).__vachanAudioProbe;
		const stop = [...probe.events]
			.reverse()
			.find(
				(event) =>
					event.kind === 'stop' && event.duration > 2 && event.at >= (probe.controlAt ?? Infinity)
			);
		if (probe.controlAt === null || stop === undefined) throw new Error('missing audio stop proof');
		return stop.at - probe.controlAt;
	});
}

// Bare `bun test` recursively discovers `*.spec.ts`; only register these
// cases when the file is loaded by Playwright's Node-based runner.
if (!('Bun' in globalThis)) {
	for (const control of ['End call', 'Break-glass takeover'] as const) {
		test(`${control} stops a real browser AudioBuffer before delayed HTTP work`, async ({ page }) => {
			await installAudioProbe(page);
			const apiPath = control === 'End call' ? '**/api/call/end' : '**/api/takeover';
			let completeHttp: (status: number) => void = () => undefined;
			const httpCompleted = new Promise<number>((resolve) => {
				completeHttp = resolve;
			});
			await page.route(apiPath, async (route) => {
				await new Promise((resolve) => setTimeout(resolve, 500));
				await route.fulfill({
					contentType: 'application/json',
					body: JSON.stringify({ api_version: 'v0', status: 'accepted' })
				});
				completeHttp(200);
			});

			const stopLatencyMs = await measureStopFromClick(page, control);
			expect(stopLatencyMs).toBeGreaterThanOrEqual(0);
			expect(stopLatencyMs).toBeLessThan(200);
			expect(await httpCompleted).toBe(200);
			if (control === 'Break-glass takeover') {
				await expect(page.getByText('OPERATOR TAKEOVER — AGENT SILENCED')).toBeVisible();
			}
		});
	}
}
