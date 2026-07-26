import { describe, expect, test } from 'bun:test';

import {
	INITIAL_SIMULATED_CALLER_DISCLOSURE,
	advanceSimulatedCallerDisclosure,
	clearSimulatedCallerDisclosure,
	persistSimulatedCallerDisclosure,
	restoreSimulatedCallerDisclosure,
	type SimulatedCallerDisclosureStorage,
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

function memoryStorage(): SimulatedCallerDisclosureStorage {
	const values = new Map<string, string>();
	return {
		getItem: (key) => values.get(key) ?? null,
		setItem: (key, value) => values.set(key, value),
		removeItem: (key) => values.delete(key)
	};
}

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

	test('the used bit survives a same-call component remount without storing caller content', () => {
		const storage = memoryStorage();
		const firstInstance = advanceSimulatedCallerDisclosure(
			INITIAL_SIMULATED_CALLER_DISCLOSURE,
			'first_frame'
		);
		persistSimulatedCallerDisclosure(storage, 'call-reload', firstInstance);

		const remountedInstance = restoreSimulatedCallerDisclosure(storage, 'call-reload');

		expect(remountedInstance.latched).toBe(true);
		expect(restoreSimulatedCallerDisclosure(storage, 'another-call').latched).toBe(false);
	});

	test('terminal/reset and genuinely different-call boundaries clear the old call bit', () => {
		const storage = memoryStorage();
		persistSimulatedCallerDisclosure(storage, 'old-call', { latched: true });

		clearSimulatedCallerDisclosure(storage, 'old-call');

		expect(restoreSimulatedCallerDisclosure(storage, 'old-call').latched).toBe(false);
	});

	test('blank call IDs never read or write browser storage', () => {
		let reads = 0;
		let writes = 0;
		const storage: SimulatedCallerDisclosureStorage = {
			getItem: () => {
				reads += 1;
				return 'used';
			},
			setItem: () => {
				writes += 1;
			},
			removeItem: () => {
				writes += 1;
			}
		};

		persistSimulatedCallerDisclosure(storage, '  ', { latched: true });
		clearSimulatedCallerDisclosure(storage, '');

		expect(restoreSimulatedCallerDisclosure(storage, ' ').latched).toBe(false);
		expect(reads).toBe(0);
		expect(writes).toBe(0);
	});
});
