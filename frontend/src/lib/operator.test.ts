import { describe, expect, test } from 'bun:test';

import { buildOperatorView } from './operator';
import { PROTOCOL_VERSION, type EventType, type ServerEvent } from './protocol';

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
});
