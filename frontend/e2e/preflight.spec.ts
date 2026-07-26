import { expect, test } from '@playwright/test';

if (!('Bun' in globalThis)) {
	test('permission revocation reaches backend and names the microphone block', async ({
		context,
		page
	}) => {
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
		await page.goto('/', { waitUntil: 'networkidle' });
		await page.getByRole('button', { name: 'Request mic' }).click();
		await expect(
			page.getByText('Permission granted. The setup check released the microphone.')
		).toBeVisible();

		await context.clearPermissions();
		let microphoneHeader = '';
		await page.route('**/api/preflight', async (route) => {
			microphoneHeader = route.request().headers()['x-vachan-microphone'] ?? '';
			await route.fulfill({
				contentType: 'application/json',
				body: JSON.stringify({
					api_version: 'v0',
					result: 'BLOCKED_TECHNICAL',
					checks: [
						{
							api_version: 'v0',
							name: 'microphone',
							pass: false,
							detail: 'Grant microphone permission in browser settings, then rerun preflight.'
						}
					]
				})
			});
		});

		await page.getByRole('button', { name: 'Run policy preflight' }).click();

		expect(microphoneHeader).not.toBe('granted');
		await expect(page.getByText('BLOCKED_TECHNICAL', { exact: true })).toBeVisible();
		await expect(page.getByText('microphone', { exact: true })).toBeVisible();
		await expect(
			page.getByText('Grant microphone permission in browser settings, then rerun preflight.')
		).toBeVisible();
		await expect(page.getByRole('button', { name: 'Start mock call' })).toBeDisabled();
	});

	test('policy refusal is visually deliberate and keeps Start disabled with a reason', async ({
		page
	}) => {
		await page.route('**/api/cases', (route) =>
			route.fulfill({
				contentType: 'application/json',
				body: JSON.stringify({
					api_version: 'v0',
					cases: [
						{
							api_version: 'v0',
							case_id: 'case-capped-002',
							borrower_display_name: 'Farida Khan',
							eligible: true,
							contact_cap_remaining: 0,
							mock_data: true
						}
					]
				})
			})
		);
		await page.route('**/api/preflight', (route) =>
			route.fulfill({
				contentType: 'application/json',
				body: JSON.stringify({
					api_version: 'v0',
					result: 'BLOCKED_POLICY',
					checks: [
						{
							api_version: 'v0',
							name: 'contact_cap',
							pass: false,
							detail:
								'contact cap reached: 3/3 this week — mock policy. Priya cannot override this policy block.'
						},
						{
							api_version: 'v0',
							name: 'backend',
							pass: true,
							detail: 'Backend health check passed.'
						}
					]
				})
			})
		);
		await page.goto('/', { waitUntil: 'networkidle' });
		await page.getByRole('button', { name: 'Run policy preflight' }).click();

		const decision = page.locator('.preflight-decision.policy-block');
		await expect(decision).toContainText('contact cap reached: 3/3 this week');
		await expect(decision.locator('li').first()).toContainText('contact cap');
		const start = page.getByRole('button', { name: 'Start mock call' });
		await expect(start).toBeDisabled();
		await expect(start).toHaveAttribute('title', /Priya cannot override/);
		await expect(page.locator('.setup-actions .start-button')).toHaveCount(1);
		const amberButtons = await page.locator('button').evaluateAll((buttons) => {
			const probe = document.createElement('div');
			probe.style.background = getComputedStyle(document.documentElement)
				.getPropertyValue('--color-accent')
				.trim();
			document.body.append(probe);
			const accent = getComputedStyle(probe).backgroundColor;
			probe.remove();
			return buttons
				.filter((button) => getComputedStyle(button).backgroundColor === accent)
				.map((button) => button.textContent?.trim() ?? '');
		});
		expect(amberButtons).toEqual(['Start mock call']);
	});
}
