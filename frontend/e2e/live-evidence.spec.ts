import { expect, test } from '@playwright/test';

const CALL_ID = 'call-browser-e2e';

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

	test('real operator controls render persisted live evidence and reconnect without duplicates', async ({
		page
	}) => {
	const consoleErrors: string[] = [];
	const networkLog: string[] = [];
	page.on('console', (message) => {
		if (message.type() === 'error') consoleErrors.push(message.text());
	});
	page.on('request', (request) => {
		if (request.url().includes('/api/evidence') || request.url().includes('/ws/evidence')) {
			networkLog.push(`${request.method()} ${request.url()}`);
		}
	});
	await page.goto('/', { waitUntil: 'networkidle' });
	await expect(page.getByRole('combobox', { name: 'Mock case' })).toHaveValue('case-rakesh-001');

	await page.getByRole('button', { name: 'Request mic' }).click();
	await expect(page.getByText('Permission granted. The setup check released the microphone.')).toBeVisible();
	await page.getByRole('button', { name: 'Play Bulbul check' }).click();
	await page.getByRole('button', { name: 'I hear Bulbul' }).click();
	await page.getByRole('button', { name: 'Run policy preflight' }).click();
	await expect(page.getByText('All checks passed. Start is enabled for this mock case.')).toBeVisible();

	const startedAt = Date.now();
	await page.getByRole('button', { name: 'Start mock call' }).click();
	const liveConsole = page.locator('.operator-console').filter({ hasText: 'LIVE · PERSISTED LEDGER' });
	const identityRibbon = liveConsole.locator('.identity-ribbon');
	await expect(identityRibbon.getByText('UNVERIFIED', { exact: true })).toBeVisible();
	await expect(identityRibbon.getByText('VERIFYING', { exact: true })).toBeVisible();
	await expect(identityRibbon.getByText('CONFIRMED', { exact: true })).toBeVisible();
	await expect(liveConsole.getByText('read_mock_account · DENIED', { exact: true })).toBeVisible();
	expect(Date.now() - startedAt).toBeLessThan(1_000);
	await expect(liveConsole.locator('.evidence-card li')).toHaveCount(4);

	await page.reload();
	const restoredConsole = page.locator('.operator-console').filter({
		hasText: 'LIVE · PERSISTED LEDGER'
	});
	await expect(
		restoredConsole.locator('.identity-ribbon').getByText('CONFIRMED', { exact: true })
	).toBeVisible();
	await expect(restoredConsole.locator('.evidence-card li')).toHaveCount(4);
	expect(consoleErrors).toEqual([]);
	expect(networkLog.some((line) => line.includes(`/api/evidence/${CALL_ID}`))).toBe(true);
	await page.screenshot({ path: '/tmp/vachan-jg9-live-ledger.png', fullPage: true });
	});

	test('evidence recovery failure is visible and never relabeled as live state', async ({ page }) => {
		await page.addInitScript(
			({ key, callId }) => sessionStorage.setItem(key, callId),
			{ key: 'vachan.activeCallId', callId: CALL_ID }
		);
		await page.route('**/api/cases', (route) =>
			route.fulfill({ contentType: 'application/json', body: '{"api_version":"v0","cases":[]}' })
		);
		await page.route(`**/api/evidence/${CALL_ID}`, (route) =>
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
		await expect(liveConsole.getByRole('alert')).toContainText('EVENT STREAM DEGRADED');
		await expect(liveConsole.locator('.evidence-card li')).toHaveCount(0);
		await expect(page.getByText('REPLAY — recorded sequence').first()).toBeVisible();
		await page.screenshot({ path: '/tmp/vachan-jg9-degraded.png', fullPage: true });
	});
}
