import { describe, expect, test } from 'bun:test';

import {
	INITIAL_SIMULATED_CALLER_DISCLOSURE,
	advanceSimulatedCallerDisclosure,
	type SimulatedCallerDisclosureEvent
} from './simCallerDisclosure';

const NON_TERMINAL_EVENTS: readonly SimulatedCallerDisclosureEvent[] = [
	'stopped',
	'completed',
	'failed',
	'disarmed',
	'takeover_requested',
	'end_requested'
];

describe('simulated-caller disclosure lifecycle', () => {
	test('arming without sending audio does not claim prerecorded input was used', () => {
		expect(
			advanceSimulatedCallerDisclosure(
				INITIAL_SIMULATED_CALLER_DISCLOSURE,
				'armed_without_audio'
			).latched
		).toBe(false);
	});

	test('the first attempted PCM frame latches disclosure', () => {
		expect(
			advanceSimulatedCallerDisclosure(INITIAL_SIMULATED_CALLER_DISCLOSURE, 'first_frame')
				.latched
		).toBe(true);
	});

	test('stop, completion, errors, disarm, takeover, and end cannot conceal prior use', () => {
		for (const event of NON_TERMINAL_EVENTS) {
			const latched = advanceSimulatedCallerDisclosure(
				INITIAL_SIMULATED_CALLER_DISCLOSURE,
				'first_frame'
			);
			expect(advanceSimulatedCallerDisclosure(latched, event).latched).toBe(true);
		}
	});

	test('terminal disposition, reset, and a new call start clean lifecycles', () => {
		for (const event of ['terminal_disposition', 'demo_reset', 'new_call'] as const) {
			const latched = advanceSimulatedCallerDisclosure(
				INITIAL_SIMULATED_CALLER_DISCLOSURE,
				'first_frame'
			);
			expect(advanceSimulatedCallerDisclosure(latched, event).latched).toBe(false);
		}
	});
});
