export type SimulatedCallerDisclosureEvent =
	| 'armed_without_audio'
	| 'first_frame'
	| 'stopped'
	| 'completed'
	| 'failed'
	| 'disarmed'
	| 'takeover_requested'
	| 'end_requested'
	| 'terminal_disposition'
	| 'demo_reset'
	| 'new_call';

export interface SimulatedCallerDisclosure {
	readonly latched: boolean;
}

export interface SimulatedCallerDisclosureStorage {
	getItem(key: string): string | null;
	setItem(key: string, value: string): void;
	removeItem(key: string): void;
}

export const INITIAL_SIMULATED_CALLER_DISCLOSURE: SimulatedCallerDisclosure = {
	latched: false
};

const STORAGE_KEY_PREFIX = 'vachan.simulatedCallerDisclosure.';
const STORAGE_LATCHED_VALUE = 'used';

function disclosureStorageKey(callId: string): string | undefined {
	const normalizedCallId = callId.trim();
	if (!normalizedCallId) return undefined;
	return `${STORAGE_KEY_PREFIX}${normalizedCallId}`;
}

/**
 * Restore only the fact that prerecorded caller audio was used. No fixture name,
 * transcript, PCM, or other caller content belongs in browser storage.
 */
export function restoreSimulatedCallerDisclosure(
	storage: SimulatedCallerDisclosureStorage,
	callId: string
): SimulatedCallerDisclosure {
	const key = disclosureStorageKey(callId);
	return {
		latched: key !== undefined && storage.getItem(key) === STORAGE_LATCHED_VALUE
	};
}

export function persistSimulatedCallerDisclosure(
	storage: SimulatedCallerDisclosureStorage,
	callId: string,
	disclosure: SimulatedCallerDisclosure
): void {
	const key = disclosureStorageKey(callId);
	if (key === undefined) return;
	if (disclosure.latched) storage.setItem(key, STORAGE_LATCHED_VALUE);
	else storage.removeItem(key);
}

export function clearSimulatedCallerDisclosure(
	storage: SimulatedCallerDisclosureStorage,
	callId: string
): void {
	const key = disclosureStorageKey(callId);
	if (key !== undefined) storage.removeItem(key);
}

/**
 * Disclosure becomes irreversible for the lifetime of a call as soon as the first
 * prerecorded PCM frame is attempted. Local controls and failures cannot conceal
 * that fact; only a durable terminal boundary or an explicit new lifecycle clears it.
 */
export function advanceSimulatedCallerDisclosure(
	state: SimulatedCallerDisclosure,
	event: SimulatedCallerDisclosureEvent
): SimulatedCallerDisclosure {
	if (event === 'first_frame') return { latched: true };
	if (event === 'terminal_disposition' || event === 'demo_reset' || event === 'new_call') {
		return INITIAL_SIMULATED_CALLER_DISCLOSURE;
	}
	return state;
}
