import { expect, test } from '@playwright/test';
import { writeFile } from 'node:fs/promises';

// Bare `bun test` recursively discovers `*.spec.ts`; only register these
// cases when the file is loaded by Playwright's Node-based runner.
if (!('Bun' in globalThis)) {
	test('mobile setup defaults to Rakesh with touch-safe controls and no overflow', async ({
		page
	}) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.route('**/api/cases', (route) =>
			route.fulfill({
				contentType: 'application/json',
				body: JSON.stringify({
					api_version: 'v0',
					cases: [
						{
							api_version: 'v0',
							case_id: 'case-capped-001',
							borrower_display_name: 'Meera Kulkarni',
							eligible: true,
							contact_cap_remaining: 10,
							mock_data: true
						},
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
		await page.goto('/', { waitUntil: 'networkidle' });

		const casePicker = page.getByRole('combobox', { name: 'Mock case' });
		await expect(casePicker).toHaveValue('case-rakesh-001');
		expect((await casePicker.boundingBox())?.height).toBeGreaterThanOrEqual(44);

		await page.getByRole('button', { name: 'Reset demo data' }).click();
		const resetButtons = page.locator('.reset-confirmation button');
		await expect(resetButtons).toHaveCount(2);
		const first = await resetButtons.nth(0).boundingBox();
		const second = await resetButtons.nth(1).boundingBox();
		expect(first?.width).toBeGreaterThanOrEqual(44);
		expect(second?.width).toBeGreaterThanOrEqual(44);
		expect(first?.y).toBeLessThan(second?.y ?? 0);
		expect(
			await page.evaluate(
				() => document.documentElement.scrollWidth === window.innerWidth
			)
		).toBe(true);
	});

	test('production operator flow persists evidence through reload, ending, and reset', async ({
		page
	}, testInfo) => {
		const consoleErrors: string[] = [];
		const consoleLog: string[] = [];
		const networkLog: string[] = [];
		page.on('console', (message) => {
			consoleLog.push(`${message.type().toUpperCase()} ${message.text()}`);
			if (message.type() === 'error') consoleErrors.push(message.text());
		});
		page.on('pageerror', (error) => {
			consoleLog.push(`PAGEERROR ${error.name}: ${error.message}`);
		});
		page.on('request', (request) => {
			const url = new URL(request.url());
			if (url.pathname.startsWith('/api/')) {
				networkLog.push(`REQUEST ${request.method()} ${url.pathname}`);
			}
		});
		page.on('response', (response) => {
			const url = new URL(response.url());
			if (url.pathname.startsWith('/api/')) {
				networkLog.push(`RESPONSE ${response.status()} ${url.pathname}`);
			}
		});
		page.on('websocket', (socket) => {
			const url = new URL(socket.url());
			networkLog.push(`WEBSOCKET ${url.pathname}`);
		});
		await page.goto('/', { waitUntil: 'networkidle' });
		await expect(page.getByRole('combobox', { name: 'Mock case' })).toHaveValue(
			'case-rakesh-001'
		);
		const replayProbe = await page.request.post('/api/dev/replay', {
			data: { api_version: 'v0', fixture: 'happy' }
		});
		expect(replayProbe.status()).toBe(404);

		await page.getByRole('button', { name: 'Request mic' }).click();
		await expect(
			page.getByText(
				'Permission granted. The setup check released the microphone.'
			)
		).toBeVisible();
		await page.getByRole('button', { name: 'Play Bulbul check' }).click();
		await page.getByRole('button', { name: 'I hear Bulbul' }).click();
		await page.getByRole('button', { name: 'Run policy preflight' }).click();
		await expect(
			page.getByText('All checks passed. Start is enabled for this mock case.')
		).toBeVisible();

		const startedAt = Date.now();
		await page.getByRole('button', { name: 'Start mock call' }).click();
		const liveConsole = page
			.locator('.operator-console')
			.filter({ hasText: 'LIVE · PERSISTED LEDGER' });
		const identityRibbon = liveConsole.locator('.identity-ribbon');
		await expect(
			identityRibbon.getByText('UNVERIFIED', { exact: true })
		).toBeVisible();
		await expect(
			identityRibbon.getByText('VERIFYING', { exact: true })
		).toBeVisible();
		await expect(
			identityRibbon.getByText('CONFIRMED', { exact: true })
		).toBeVisible();
		await expect(
			liveConsole.getByText(
				/create_promise_candidate · DENIED · invalid_action_facts=ambiguous_date/
			)
		).toBeVisible();
		expect(Date.now() - startedAt).toBeLessThan(1_000);
		const callId = await page.evaluate(() =>
			sessionStorage.getItem('vachan.activeCallId')
		);
		expect(callId).toMatch(/^call-/);
		const evidenceCount = await liveConsole
			.locator('.evidence-card li')
			.count();
		expect(evidenceCount).toBeGreaterThanOrEqual(7);
		const activeEvidence = await page.request.get(`/api/evidence/${callId}`);
		expect(activeEvidence.ok()).toBe(true);
		const activeBody = (await activeEvidence.json()) as {
			events: Array<{ type: string; payload: Record<string, unknown> }>;
		};
		const persistedSafeOutput = activeBody.events
			.filter((event) => event.type === 'utterance')
			.at(-1)?.payload.text;
		expect(typeof persistedSafeOutput).toBe('string');
		expect(persistedSafeOutput).not.toBe('Turn timing evidence recorded.');
		await expect(liveConsole.locator('.call-card blockquote')).toHaveText(
			persistedSafeOutput as string
		);

		await page.reload();
		const restoredConsole = page.locator('.operator-console').filter({
			hasText: 'LIVE · PERSISTED LEDGER'
		});
		await expect(
			restoredConsole
				.locator('.identity-ribbon')
				.getByText('CONFIRMED', { exact: true })
		).toBeVisible();
		await expect(restoredConsole.locator('.evidence-card li')).toHaveCount(
			evidenceCount
		);
		await expect(restoredConsole.locator('.call-card blockquote')).toHaveText(
			persistedSafeOutput as string
		);
		expect(consoleErrors).toEqual([]);

		const evidenceRecovery = `**/api/evidence/${callId}`;
		await page.route(evidenceRecovery, (route) =>
			route.fulfill({
				status: 503,
				contentType: 'application/json',
				body: '{"detail":"injected active-call evidence outage"}'
			})
		);
		await page.reload();
		const degradedConsole = page.locator('.operator-console').filter({
			hasText: 'LIVE · PERSISTED LEDGER'
		});
		await expect(degradedConsole.getByRole('alert')).toContainText(
			'EVENT STREAM DEGRADED'
		);
		await expect(
			degradedConsole.getByRole('button', { name: 'End call' })
		).toBeEnabled();
		await expect(
			degradedConsole.getByRole('button', { name: 'Break-glass takeover' })
		).toBeDisabled();
		await degradedConsole.getByRole('button', { name: 'End call' }).click();
		await page.unroute(evidenceRecovery);
		await expect(degradedConsole.locator('.outcome-panel')).toContainText(
			'ENDED_OPERATOR'
		);

		const completedEvidence = await page.request.get(`/api/evidence/${callId}`);
		expect(completedEvidence.ok()).toBe(true);
		const completedBody = (await completedEvidence.json()) as {
			events: Array<{ type: string; payload: Record<string, unknown> }>;
		};
		const dispositions = completedBody.events.filter(
			(event) => event.type === 'disposition'
		);
		expect(dispositions).toHaveLength(1);
		expect(dispositions[0]?.payload.disposition).toBe('ENDED_OPERATOR');
		expect(completedBody.events.at(-1)?.type).toBe('disposition');

		await page.getByRole('button', { name: 'Reset demo data' }).click();
		await page.getByRole('button', { name: 'Confirm demo reset' }).click();
		await expect(
			page.getByText(/Reset complete\. 3 governed mock cases/)
		).toBeVisible();
		await expect(page.getByRole('combobox', { name: 'Mock case' })).toHaveValue(
			'case-rakesh-001'
		);

		expect(consoleErrors.length).toBeGreaterThan(0);
		expect(
			consoleErrors.every((message) =>
				message.includes('the server responded with a status of 503')
			)
		).toBe(true);
		for (const boundary of [
			'/api/preflight',
			'/api/call/start',
			'/ws/call/',
			'/api/evidence/',
			'/ws/evidence/',
			'/api/call/end',
			'/api/reset'
		]) {
			expect(
				networkLog.some((line) => line.includes(boundary)),
				networkLog.join('\n')
			).toBe(true);
		}
		const artifactHeader = `RUN ${new Date().toISOString()}\n`;
		const consoleArtifact = `${artifactHeader}${consoleLog.join('\n') || 'NO BROWSER CONSOLE MESSAGES'}\n`;
		const networkArtifact = `${artifactHeader}${networkLog.join('\n')}\n`;
		await Promise.all([
			writeFile('/tmp/vachan-jg9-browser-console.log', consoleArtifact, 'utf8'),
			writeFile('/tmp/vachan-jg9-browser-network.log', networkArtifact, 'utf8')
		]);
		await testInfo.attach('browser-console', {
			body: consoleArtifact,
			contentType: 'text/plain'
		});
		await testInfo.attach('browser-network', {
			body: networkArtifact,
			contentType: 'text/plain'
		});
		await page.screenshot({
			path: '/tmp/vachan-jg9-live-ledger.png',
			fullPage: true
		});
	});

	test('evidence recovery failure is visible and never relabeled as live state', async ({
		page
	}) => {
		const missingCallId = 'call-injected-evidence-outage';
		await page.addInitScript(
			({ key, callId }) => sessionStorage.setItem(key, callId),
			{ key: 'vachan.activeCallId', callId: missingCallId }
		);
		await page.route('**/api/cases', (route) =>
			route.fulfill({
				contentType: 'application/json',
				body: '{"api_version":"v0","cases":[]}'
			})
		);
		await page.route(`**/api/evidence/${missingCallId}`, (route) =>
			route.fulfill({
				status: 503,
				contentType: 'application/json',
				body: '{"detail":"injected evidence outage"}'
			})
		);
		await page.goto('/');

		const liveConsole = page.locator('.operator-console').filter({
			hasText: 'LIVE · PERSISTED LEDGER'
		});
		await expect(liveConsole.getByRole('alert')).toContainText(
			'EVENT STREAM DEGRADED'
		);
		await expect(liveConsole.locator('.evidence-card li')).toHaveCount(0);
		await expect(
			page.getByText('REPLAY — recorded sequence').first()
		).toBeVisible();
		await page.screenshot({
			path: '/tmp/vachan-jg9-degraded.png',
			fullPage: true
		});
	});
}
