import type { EventType, JsonValue, ServerEvent } from '$lib/protocol';

export type OperatorConnectionState = 'idle' | 'connecting' | 'live' | 'degraded' | 'complete';
export type EvidenceTone = 'neutral' | 'held' | 'blocked' | 'promise';

export interface ToolDecisionView {
	readonly tool: string;
	readonly allowed: boolean;
	readonly reason: string;
}

export interface EvidenceRow {
	readonly seq: number;
	readonly ts: string;
	readonly type: EventType;
	readonly label: string;
	readonly detail: string;
	readonly tone: EvidenceTone;
}

export interface OperatorAlert {
	readonly title: string;
	readonly detail: string;
}

export interface OperatorActionState {
	readonly endDisabled: boolean;
	readonly takeoverDisabled: boolean;
}

export interface OperatorView {
	readonly events: readonly ServerEvent[];
	readonly callState: string;
	readonly identityState: string;
	readonly identityJourney: readonly string[];
	readonly promiseState: string;
	readonly dialogueStep: string;
	readonly latestUtterance: string;
	readonly latestSpeaker: string;
	readonly latestToolDecision: ToolDecisionView | null;
	readonly evidence: readonly EvidenceRow[];
	readonly disposition: string | null;
	readonly alert: OperatorAlert | null;
	readonly complete: boolean;
}

function payloadString(event: ServerEvent | undefined, key: string): string | undefined {
	const value: JsonValue | undefined = event?.payload[key];
	return typeof value === 'string' ? value : undefined;
}

function payloadBoolean(event: ServerEvent | undefined, key: string): boolean | undefined {
	const value: JsonValue | undefined = event?.payload[key];
	return typeof value === 'boolean' ? value : undefined;
}

function latestEvent(events: readonly ServerEvent[], type: EventType): ServerEvent | undefined {
	return events.findLast((event) => event.type === type);
}

function latestMachineState(events: readonly ServerEvent[], machine: string): string {
	const transition = events.findLast(
		(event) => event.type === 'state_change' && event.payload.machine === machine
	);
	return payloadString(transition, 'after') ?? '—';
}

function authoritativeEvents(events: readonly ServerEvent[]): readonly ServerEvent[] {
	const accepted: ServerEvent[] = [];
	let lastSequence = 0;

	for (const event of events) {
		if (event.payload.source !== 'persisted_ledger' && event.payload.source !== 'recorded_replay') {
			continue;
		}
		if (event.seq <= lastSequence) continue;
		accepted.push(event);
		lastSequence = event.seq;
		if (event.type === 'disposition') break;
	}

	return accepted;
}

function identityJourney(events: readonly ServerEvent[]): readonly string[] {
	const transitions = events.filter(
		(event) => event.type === 'state_change' && event.payload.machine === 'identity'
	);
	if (transitions.length === 0) return [];

	const journey = [payloadString(transitions[0], 'before') ?? 'UNVERIFIED'];
	for (const transition of transitions) {
		const state = payloadString(transition, 'after');
		if (state && state !== journey.at(-1)) journey.push(state);
	}
	return journey;
}

export function operatorActionState({
	complete,
	hasEnd,
	hasTakeover,
	takeoverActive,
	endReason
}: {
	readonly complete: boolean;
	readonly hasEnd: boolean;
	readonly hasTakeover: boolean;
	readonly takeoverActive: boolean;
	readonly endReason: string;
}): OperatorActionState {
	const terminal = complete || (!hasEnd && !hasTakeover);
	return {
		endDisabled: terminal || !hasEnd || (takeoverActive && !endReason.trim()),
		takeoverDisabled: terminal || !hasTakeover || takeoverActive
	};
}

function evidenceDetail(event: ServerEvent): string {
	if (event.type === 'state_change') {
		const machine = payloadString(event, 'machine') ?? 'state';
		const before = payloadString(event, 'before') ?? '—';
		const after = payloadString(event, 'after') ?? '—';
		return `${machine.toUpperCase()} · ${before} → ${after}`;
	}
	if (event.type === 'utterance') {
		return payloadString(event, 'text') ?? 'Reviewed utterance delivered';
	}
	if (event.type === 'tool_decision') {
		const tool = payloadString(event, 'tool') ?? 'unknown tool';
		const decision = payloadBoolean(event, 'allowed') ? 'ALLOWED' : 'DENIED';
		const reason = payloadString(event, 'reason');
		return [tool, decision, reason].filter(Boolean).join(' · ');
	}
	if (event.type === 'guard_block') {
		return (
			payloadString(event, 'reason') ??
			payloadString(event, 'category') ??
			'Draft discarded before speech'
		);
	}
	if (event.type === 'disposition') {
		return payloadString(event, 'disposition') ?? 'Call ended';
	}
	if (event.type === 'diagnostic') {
		return payloadString(event, 'reason') ?? 'Runtime diagnostic recorded';
	}
	return payloadString(event, 'reason') ?? 'Technical event';
}

function evidenceTone(event: ServerEvent): EvidenceTone {
	if (
		event.type === 'guard_block' ||
		event.type === 'error' ||
		(event.type === 'tool_decision' && payloadBoolean(event, 'allowed') === false)
	) {
		return 'blocked';
	}
	if (
		event.type === 'state_change' &&
		event.payload.machine === 'identity' &&
		event.payload.after === 'CONFIRMED'
	) {
		return 'held';
	}
	if (
		(event.type === 'state_change' && event.payload.machine === 'promise') ||
		(event.type === 'disposition' && event.payload.disposition === 'PROMISE_CONFIRMED')
	) {
		return 'promise';
	}
	return 'neutral';
}

function dialogueStep(
	callState: string,
	identityState: string,
	promiseState: string,
	disposition: string | null
): string {
	if (disposition) return 'OUTCOME RECORDED';
	if (promiseState !== '—' && promiseState !== 'NONE') return `PROMISE · ${promiseState}`;
	if (identityState !== '—' && identityState !== 'UNVERIFIED') {
		return `IDENTITY · ${identityState}`;
	}
	return callState === '—' ? 'WAITING FOR LEDGER' : `CALL · ${callState}`;
}

export function buildOperatorView(
	inputEvents: readonly ServerEvent[],
	connectionState: OperatorConnectionState
): OperatorView {
	const events = authoritativeEvents(inputEvents);
	const dispositionEvent = latestEvent(events, 'disposition');
	const disposition = payloadString(dispositionEvent, 'disposition') ?? null;
	const complete = disposition !== null;
	const utterance = latestEvent(events, 'utterance');
	const toolDecision = latestEvent(events, 'tool_decision');
	const callState = latestMachineState(events, 'call');
	const identityState = latestMachineState(events, 'identity');
	const promiseState = latestMachineState(events, 'promise');
	const allowed = payloadBoolean(toolDecision, 'allowed');

	return {
		events,
		callState,
		identityState,
		identityJourney: identityJourney(events),
		promiseState,
		dialogueStep: dialogueStep(callState, identityState, promiseState, disposition),
		latestUtterance: payloadString(utterance, 'text') ?? 'Waiting for an evidence-ledger event.',
		latestSpeaker: payloadString(utterance, 'speaker') ?? 'agent',
		latestToolDecision: toolDecision
			? {
					tool: payloadString(toolDecision, 'tool') ?? 'unknown',
					allowed: allowed === true,
					reason: payloadString(toolDecision, 'reason') ?? 'No reason recorded'
				}
			: null,
		evidence: events.map((event) => ({
			seq: event.seq,
			ts: event.ts,
			type: event.type,
			label: event.type.replaceAll('_', ' ').toUpperCase(),
			detail: evidenceDetail(event),
			tone: evidenceTone(event)
		})),
		disposition,
		alert:
			connectionState === 'degraded' && !complete
				? {
						title: 'EVENT STREAM DEGRADED',
						detail: 'The ledger connection dropped. Do not infer call state from a frozen screen.'
					}
				: null,
		complete
	};
}
