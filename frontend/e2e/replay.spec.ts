import { expect, test } from '@playwright/test';

// Bare `bun test` recursively discovers `*.spec.ts`; only register this
// browser case when the file is loaded by Playwright's Node-based runner.
if (!('Bun' in globalThis)) {
	test('DEV replay drives the operator view through a committed promise', async ({ page }) => {
		await page.goto('/', { waitUntil: 'networkidle' });

		const replayHarness = page.locator('.replay-harness');
		await expect(replayHarness).toContainText('REPLAY — recorded sequence');
		await replayHarness.getByRole('button', { name: 'Run recorded replay' }).click();

		const replayConsole = replayHarness.locator('.operator-console');
		await expect(replayConsole.getByText('REPLAY — recorded sequence', { exact: true })).toBeVisible();
		await expect(
			replayConsole
				.locator('.evidence-card small')
				.filter({ hasText: 'read_mock_account · DENIED' })
		).toBeVisible();
		await expect(replayConsole.getByText('Draft discarded before TTS')).toBeVisible();
		await expect(
			replayConsole.locator('.identity-ribbon').getByText('CONFIRMED', { exact: true })
		).toBeVisible();
		await expect(replayConsole.locator('.watch-card dd.promise')).toHaveText('COMMITTED');
		await expect(replayConsole.locator('.outcome-panel')).toContainText('PROMISE_CONFIRMED');
		await expect(replayHarness.getByText('Recorded sequence finished with a disposition.')).toBeVisible();
		await expect(replayConsole.locator('.evidence-card li')).toHaveCount(13);
	});
}
