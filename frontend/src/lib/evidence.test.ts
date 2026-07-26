import { describe, expect, test } from 'bun:test';

import {
	mergePersistedEvidence,
	parsePersistedEvidenceEvent,
	PERSISTED_LEDGER_SOURCE
} from './evidence';
import { PROTOCOL_VERSION, type EventType, type ServerEvent } from './protocol';

function event(
	seq: number,
	type: EventType = 'state_change',
	overrides: Partial<ServerEvent> = {}
): ServerEvent {
	return {
		api_version: PROTOCOL_VERSION,
		type,
		call_id: 'call-live',
		seq,
		ts: `2026-07-26T12:00:${String(seq).padStart(2, '0')}+05:30`,
		payload: {
			source: PERSISTED_LEDGER_SOURCE,
			ledger_type: 'STATE_TRANSITION',
			machine: 'identity',
			before: 'UNVERIFIED',
			after: 'VERIFYING'
		},
		...overrides
	};
}

describe('persisted evidence contract', () => {
	test('parses only the frozen version, requested call, and live source', () => {
		expect(parsePersistedEvidenceEvent(event(1), 'call-live') === null).toBe(false);
		expect(
			parsePersistedEvidenceEvent(
				event(1, 'state_change', { payload: { source: 'recorded_replay' } }),
				'call-live'
			)
		).toBeNull();
		expect(
			parsePersistedEvidenceEvent(event(1, 'state_change', { call_id: 'other-call' }), 'call-live')
		).toBeNull();
		expect(
			parsePersistedEvidenceEvent(
				{ ...event(1), api_version: 'v1' },
				'call-live'
			)
		).toBeNull();
	});

	test('deduplicates reconnect replay and preserves monotonic order', () => {
		const recovered = mergePersistedEvidence([event(1), event(2)], [event(2), event(3)], 'call-live');
		expect(recovered.map((item) => item.seq)).toEqual([1, 2, 3]);
	});

	test('fails closed when a persisted sequence changes across recovery', () => {
		let message = '';
		try {
			mergePersistedEvidence(
				[event(1)],
				[event(1, 'state_change', { payload: { source: PERSISTED_LEDGER_SOURCE, reason: 'changed' } })],
				'call-live'
			);
		} catch (error) {
			message = error instanceof Error ? error.message : String(error);
		}
		expect(message).toContain('changed across recovery');
	});

	test('accepts exactly one final disposition and rejects events after it', () => {
		const terminal = event(2, 'disposition', {
			payload: {
				source: PERSISTED_LEDGER_SOURCE,
				ledger_type: 'DISPOSITION_SET',
				disposition: 'ENDED_OPERATOR'
			}
		});
		expect(mergePersistedEvidence([event(1)], [terminal], 'call-live').at(-1)?.type).toBe(
			'disposition'
		);
		let message = '';
		try {
			mergePersistedEvidence([event(1), terminal], [event(3)], 'call-live');
		} catch (error) {
			message = error instanceof Error ? error.message : String(error);
		}
		expect(message).toContain('continued after');
	});
});
