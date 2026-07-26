import { expect, test } from '@playwright/test';

interface ReplayExpectation {
	readonly fixture: 'happy' | 'third_party' | 'takeover';
	readonly option: string;
	readonly disposition: string;
	readonly eventCount: number;
	readonly identity: string;
	readonly toolDecision: string;
	readonly evidenceDetail: string;
	readonly promise?: string;
}

const replayExpectations: readonly ReplayExpectation[] = [
	{
		fixture: 'happy',
		option: 'Happy path',
		disposition: 'PROMISE_CONFIRMED',
		eventCount: 13,
		identity: 'CONFIRMED',
		toolDecision: 'read_mock_account · DENIED',
		evidenceDetail: 'Draft discarded before TTS',
		promise: 'COMMITTED'
	},
	{
		fixture: 'third_party',
		option: 'Third party',
		disposition: 'CALLBACK_THIRD_PARTY',
		eventCount: 6,
		identity: 'THIRD_PARTY',
		toolDecision: 'read_mock_account · DENIED',
		evidenceDetail: 'Third-party speaker; account tools remain locked.'
	},
	{
		fixture: 'takeover',
		option: 'Takeover',
		disposition: 'ENDED_OPERATOR',
		eventCount: 6,
		identity: 'NO IDENTITY EVIDENCE',
		toolDecision: 'all_agent_tools · DENIED',
		evidenceDetail: 'Pending model and TTS work cancelled'
	}
];

// Bare `bun test` recursively discovers `*.spec.ts`; only register this
// browser suite when the file is loaded by Playwright's Node-based runner.
if (!('Bun' in globalThis)) {
	for (const expectation of replayExpectations) {
		test(`DEV replay renders the governed ${expectation.fixture} fixture`, async ({ page }) => {
			await page.goto('/', { waitUntil: 'networkidle' });

			const replayHarness = page.locator('.replay-harness');
			await expect(replayHarness).toContainText('REPLAY — recorded sequence');
			await replayHarness.getByLabel('FIXTURE').selectOption(expectation.fixture);
			await expect(replayHarness.getByLabel('FIXTURE')).toHaveValue(expectation.fixture);
			await expect(replayHarness.getByLabel('FIXTURE')).toContainText(expectation.option);
			await replayHarness.getByRole('button', { name: 'Run recorded replay' }).click();

			const replayConsole = replayHarness.locator('.operator-console');
			await expect(
				replayConsole.getByText('REPLAY — recorded sequence', { exact: true })
			).toBeVisible();
			await expect(
				replayConsole.locator('.evidence-card small').filter({ hasText: expectation.toolDecision })
			).toBeVisible();
			await expect(replayConsole.getByText(expectation.evidenceDetail, { exact: false })).toBeVisible();
			await expect(
				replayConsole.locator('.identity-ribbon').getByText(expectation.identity, { exact: true })
			).toBeVisible();
			if (expectation.promise) {
				await expect(replayConsole.locator('.watch-card dd.promise')).toHaveText(
					expectation.promise
				);
			}
			await expect(replayConsole.locator('.outcome-panel')).toContainText(expectation.disposition);
			await expect(
				replayHarness.getByText('Recorded sequence finished with a disposition.')
			).toBeVisible();
			await expect(replayConsole.locator('.evidence-card li')).toHaveCount(expectation.eventCount);
		});
	}
}
