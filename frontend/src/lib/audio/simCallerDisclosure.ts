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

export const INITIAL_SIMULATED_CALLER_DISCLOSURE: SimulatedCallerDisclosure = {
	latched: false
};

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
