import { expect, test, type Page } from '@playwright/test';

const ACTIVE_CALL_STORAGE_KEY = 'vachan.activeCallId';
const RESPONSIVE_CALL_ID = 'call-responsive-e2e';

async function installResponsiveFixtures(page: Page): Promise<void> {
	await page.addInitScript(
		({ key, callId }) => sessionStorage.setItem(key, callId),
		{ key: ACTIVE_CALL_STORAGE_KEY, callId: RESPONSIVE_CALL_ID }
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
	await page.route(`**/api/evidence/${RESPONSIVE_CALL_ID}`, (route) =>
		route.fulfill({
			status: 503,
			contentType: 'application/json',
			body: '{"detail":"injected responsive-test evidence outage"}'
		})
	);
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
	await expect
		.poll(() =>
			page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
		)
		.toBe(true);
}

// Bare `bun test` recursively discovers `*.spec.ts`; only register these
// cases when the file is loaded by Playwright's Node-based runner.
if (!('Bun' in globalThis)) {
	test('operator workspace stays single-column throughout the 48-68rem band', async ({
		page
	}) => {
		await installResponsiveFixtures(page);

		for (const width of [768, 900, 1088]) {
			await page.setViewportSize({ width, height: 800 });
			await page.goto('/', { waitUntil: 'domcontentloaded' });

			const columnCount = await page.locator('.workspace').evaluate((element) => {
				const columns = getComputedStyle(element).gridTemplateColumns.trim();
				return columns ? columns.split(/\s+/).length : 0;
			});
			expect(columnCount, `workspace columns at ${width}px`).toBe(1);
			await expectNoHorizontalOverflow(page);
		}
	});

	test('mock-data badge persists without blocking emergency controls', async ({ page }) => {
		await installResponsiveFixtures(page);

		for (const width of [390, 900]) {
			await page.setViewportSize({ width, height: 844 });
			await page.goto('/', { waitUntil: 'domcontentloaded' });

			const badge = page.getByText('DEMO / MOCK DATA', { exact: true });
			await expect(badge).toBeVisible();
			await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
			const viewportHeight = page.viewportSize()?.height ?? 0;
			await expect
				.poll(async () => {
					const box = await badge.boundingBox();
					return box !== null && box.y >= 0 && box.y + box.height <= viewportHeight;
				})
				.toBe(true);

			const liveConsole = page.locator('.operator-console').filter({
				hasText: 'LIVE · PERSISTED LEDGER'
			});
			for (const name of ['End call', 'Break-glass takeover']) {
				const control = liveConsole.getByRole('button', { name });
				await expect(control).toBeEnabled();
				await control.scrollIntoViewIfNeeded();
				const isReachable = await control.evaluate((element) => {
					const box = element.getBoundingClientRect();
					const centerX = box.left + box.width / 2;
					const centerY = box.top + box.height / 2;
					const hit = document.elementFromPoint(centerX, centerY);
					return (
						box.left >= 0 &&
						box.right <= window.innerWidth &&
						centerY >= 0 &&
						centerY <= window.innerHeight &&
						hit !== null &&
						(element === hit || element.contains(hit))
					);
				});
				expect(isReachable, `${name} reachable at ${width}px`).toBe(true);
			}

			await expectNoHorizontalOverflow(page);
		}
	});
}
