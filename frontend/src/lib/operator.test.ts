import { describe, expect, test } from 'bun:test';

import { buildOperatorView, operatorActionState } from './operator';
import { PROTOCOL_VERSION, type EventType, type ServerEvent } from './protocol';

declare const Bun: {
	file(path: URL): { text(): Promise<string> };
};

const operatorConsoleSource = await Bun.file(
	new URL('./components/OperatorConsole.svelte', import.meta.url)
).text();
const operatorPageSource = await Bun.file(new URL('../routes/+page.svelte', import.meta.url)).text();
const appCssSource = await Bun.file(new URL('../app.css', import.meta.url)).text();

function event(
	seq: number,
	type: EventType,
	payload: ServerEvent['payload']
): ServerEvent {
	return {
		api_version: PROTOCOL_VERSION,
		type,
		call_id: 'call-demo',
		seq,
		ts: `2026-07-26T12:00:${String(seq).padStart(2, '0')}+05:30`,
		payload: { source: 'persisted_ledger', ...payload }
	};
}

describe('ledger-derived operator view', () => {
	test('renders the complete identity journey in ledger order', () => {
		const view = buildOperatorView(
			[
				event(1, 'state_change', { machine: 'call', before: 'READY', after: 'ACTIVE' }),
				event(2, 'state_change', {
					machine: 'identity',
					before: 'UNVERIFIED',
					after: 'VERIFYING'
				}),
				event(3, 'state_change', {
					machine: 'identity',
					before: 'VERIFYING',
					after: 'CONFIRMED'
				})
			],
			'live'
		);

		expect(view.identityJourney).toEqual(['UNVERIFIED', 'VERIFYING', 'CONFIRMED']);
		expect(view.identityState).toBe('CONFIRMED');
		expect(view.callState).toBe('ACTIVE');
	});

	test('surfaces denied tools and guard blocks as ordered evidence', () => {
		const view = buildOperatorView(
			[
				event(1, 'tool_decision', {
					tool: 'read_mock_account',
					allowed: false,
					reason: 'identity_state=UNVERIFIED'
				}),
				event(2, 'guard_block', {
					category: 'account_disclosure',
					reason: 'Draft discarded before TTS'
				})
			],
			'live'
		);

		expect(view.latestToolDecision).toEqual({
			tool: 'read_mock_account',
			allowed: false,
			reason: 'identity_state=UNVERIFIED'
		});
		expect(view.evidence.map((row) => row.tone)).toEqual(['blocked', 'blocked']);
		expect(view.evidence[0]?.detail).toContain('DENIED');
	});

	test('records one outcome and ignores stale events after disposition', () => {
		const view = buildOperatorView(
			[
				event(1, 'utterance', { speaker: 'agent', text: 'Reviewed line' }),
				event(2, 'disposition', { disposition: 'CALLBACK_THIRD_PARTY' }),
				event(3, 'utterance', { speaker: 'agent', text: 'stale callback' }),
				event(4, 'disposition', { disposition: 'PROMISE_CONFIRMED' })
			],
			'complete'
		);

		expect(view.disposition).toBe('CALLBACK_THIRD_PARTY');
		expect(view.events).toHaveLength(2);
		expect(view.latestUtterance).toBe('Reviewed line');
		expect(view.complete).toBe(true);
	});

	test('shows exactly one actionable alert when the event stream drops', () => {
		const view = buildOperatorView([], 'degraded');

		expect(view.alert).toEqual({
			title: 'EVENT STREAM DEGRADED',
			detail: 'The ledger connection dropped. Do not infer call state from a frozen screen.'
		});
	});

	test('does not invent UNVERIFIED before an identity event is persisted', () => {
		const unknown = buildOperatorView(
			[event(1, 'state_change', { machine: 'call', before: 'READY', after: 'ACTIVE' })],
			'live'
		);
		const unverified = buildOperatorView(
			[
				event(1, 'state_change', {
					machine: 'identity',
					before: 'UNVERIFIED',
					after: 'VERIFYING'
				})
			],
			'live'
		);

		expect(unknown.identityState).toBe('—');
		expect(unknown.identityJourney).toEqual([]);
		expect(unverified.identityJourney).toEqual(['UNVERIFIED', 'VERIFYING']);
		expect(operatorConsoleSource).toContain('NO IDENTITY EVIDENCE');
	});

	test('keeps emergency actions independent of evidence transport state', () => {
		for (const connectionState of ['connecting', 'live', 'degraded'] as const) {
			const view = buildOperatorView([], connectionState);
			expect(
				operatorActionState({
					complete: view.complete,
					hasEnd: true,
					hasTakeover: true,
					takeoverActive: false,
					endReason: ''
				})
			).toEqual({
				endDisabled: false,
				takeoverDisabled: false
			});
		}
	});

	test('keeps lifecycle-specific emergency action preconditions', () => {
		expect(
			operatorActionState({
				complete: false,
				hasEnd: true,
				hasTakeover: true,
				takeoverActive: true,
				endReason: ''
			})
		).toEqual({
			endDisabled: true,
			takeoverDisabled: true
		});
		expect(
			operatorActionState({
				complete: false,
				hasEnd: true,
				hasTakeover: true,
				takeoverActive: true,
				endReason: 'Operator completed the conversation'
			})
		).toEqual({
			endDisabled: false,
			takeoverDisabled: true
		});
	});

	test('does not show a stale connection alert after a terminal disposition', () => {
		const view = buildOperatorView(
			[event(1, 'disposition', { disposition: 'ENDED_TECHNICAL' })],
			'degraded'
		);

		expect(view.alert).toBeNull();
		expect(view.dialogueStep).toBe('OUTCOME RECORDED');
	});

	test('ignores optimistic UI events without a persisted or replay source marker', () => {
		const optimistic = {
			...event(1, 'state_change', {
				machine: 'identity',
				before: 'UNVERIFIED',
				after: 'CONFIRMED'
			}),
			payload: {
				machine: 'identity',
				before: 'UNVERIFIED',
				after: 'CONFIRMED'
			}
		};
		const view = buildOperatorView([optimistic], 'live');

		expect(view.events).toEqual([]);
		expect(view.identityState).toBe('—');
	});

	test('announces WATCH changes and terminal disposition with the required urgency', () => {
		expect(operatorConsoleSource).toContain('aria-label="Identity state journey"');
		expect(operatorConsoleSource).toContain('aria-live="polite"');
		expect(operatorConsoleSource).toContain(
			"class:promise={view.disposition === 'PROMISE_CONFIRMED'}"
		);
		expect(operatorConsoleSource).toContain('aria-live="assertive"');
		expect(operatorConsoleSource).toContain("class:demoted={state === 'THIRD_PARTY'}");
	});

	test('keeps safety states projector-readable and first on narrow screens', () => {
		expect(
			/\.identity-ribbon\s*\{[^}]*font-size:\s*1\.25rem;/s.test(operatorConsoleSource)
		).toBe(true);
		expect(
			/\.outcome-panel strong\s*\{[^}]*font-size:\s*1\.75rem;/s.test(operatorConsoleSource)
		).toBe(true);
		expect(
			/@media \(max-width: 44rem\)[\s\S]*?\.watch-card\s*\{\s*order:\s*1;[\s\S]*?\.evidence-card\s*\{[^}]*order:\s*2;[\s\S]*?\.call-card\s*\{\s*order:\s*3;/s.test(
				operatorConsoleSource
			)
		).toBe(true);
	});

	test('spends amber only on the committed promise moment', () => {
		expect(operatorConsoleSource).toContain(
			"class:promise={view.promiseState === 'COMMITTED'}"
		);
		expect(operatorConsoleSource).toContain(
			"class:promise={row.tone === 'promise' && row.detail.includes('COMMITTED')}"
		);
		expect(
			operatorConsoleSource.includes(
				"class:promise={view.promiseState !== '—' && view.promiseState !== 'NONE'}"
			)
		).toBe(false);
	});

	test('defaults to the stable happy-path case instead of API ordering', () => {
		expect(operatorPageSource).toContain("const HAPPY_PATH_CASE_ID = 'case-rakesh-001'");
		expect(operatorPageSource).toContain(
			'cases.find((demoCase) => demoCase.case_id === HAPPY_PATH_CASE_ID)?.case_id'
		);
	});

	test('keeps selects and phone reset controls touch-safe', () => {
		expect(/select\s*\{[^}]*min-height:\s*44px;/s.test(appCssSource)).toBe(true);
		expect(
			/@media \(max-width: 48rem\)[\s\S]*?\.reset-confirmation > div\s*\{[^}]*grid-template-columns:\s*1fr;/s.test(
				appCssSource
			)
		).toBe(true);
		expect(
			/@media \(max-width: 48rem\)[\s\S]*?\.intro-panel h2\s*\{[^}]*max-width:\s*18ch;/s.test(
				appCssSource
			)
		).toBe(true);
	});
});
