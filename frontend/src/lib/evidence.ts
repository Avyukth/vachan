import {
	API_ROUTES,
	PROTOCOL_VERSION,
	type EvidenceResponse,
	type EventType,
	type ServerEvent
} from '$lib/protocol';

export const PERSISTED_LEDGER_SOURCE = 'persisted_ledger' as const;

const eventTypes = new Set<EventType>([
	'state_change',
	'utterance',
	'tool_decision',
	'guard_block',
	'disposition',
	'diagnostic',
	'error'
]);

export type EvidenceConnectionState = 'connecting' | 'live' | 'degraded' | 'complete';

export interface EvidenceCallbacks {
	readonly onSnapshot: (events: readonly ServerEvent[]) => void;
	readonly onState: (state: EvidenceConnectionState) => void;
}

export interface EvidenceTransport {
	readonly fetch: typeof globalThis.fetch;
	readonly createWebSocket: (url: URL) => WebSocket;
	readonly locationHref: string;
	readonly secure: boolean;
	readonly setTimer: (callback: () => void, delayMs: number) => ReturnType<typeof setTimeout>;
	readonly clearTimer: (timer: ReturnType<typeof setTimeout>) => void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isEventType(value: unknown): value is EventType {
	return typeof value === 'string' && eventTypes.has(value as EventType);
}

export function parsePersistedEvidenceEvent(value: unknown, callId: string): ServerEvent | null {
	if (!isRecord(value) || !isRecord(value.payload)) return null;
	if (value.api_version !== PROTOCOL_VERSION) return null;
	if (!isEventType(value.type)) return null;
	if (value.call_id !== callId) return null;
	if (!Number.isInteger(value.seq) || (value.seq as number) <= 0) return null;
	if (typeof value.ts !== 'string' || Number.isNaN(Date.parse(value.ts))) return null;
	if (value.payload.source !== PERSISTED_LEDGER_SOURCE) return null;
	return value as unknown as ServerEvent;
}

function sameEvent(left: ServerEvent, right: ServerEvent): boolean {
	return JSON.stringify(left) === JSON.stringify(right);
}

export function mergePersistedEvidence(
	current: readonly ServerEvent[],
	incoming: readonly unknown[],
	callId: string
): readonly ServerEvent[] {
	const bySequence = new Map<number, ServerEvent>();
	for (const event of current) {
		const parsed = parsePersistedEvidenceEvent(event, callId);
		if (parsed === null) throw new Error('Existing evidence failed the persisted-ledger contract.');
		bySequence.set(parsed.seq, parsed);
	}

	for (const value of incoming) {
		const event = parsePersistedEvidenceEvent(value, callId);
		if (event === null) throw new Error('Evidence failed the v0 call/source contract.');
		const existing = bySequence.get(event.seq);
		if (existing && !sameEvent(existing, event)) {
			throw new Error(`Evidence sequence ${event.seq} changed across recovery.`);
		}
		bySequence.set(event.seq, event);
	}

	const merged = [...bySequence.values()].sort((left, right) => left.seq - right.seq);
	for (let index = 1; index < merged.length; index += 1) {
		if (merged[index]!.seq <= merged[index - 1]!.seq) {
			throw new Error('Evidence sequence is not strictly monotonic.');
		}
	}
	const dispositions = merged.filter((event) => event.type === 'disposition');
	if (dispositions.length > 1) {
		throw new Error('Evidence contains more than one terminal disposition.');
	}
	if (dispositions.length === 1 && merged.at(-1)?.type !== 'disposition') {
		throw new Error('Evidence continued after its terminal disposition.');
	}
	return merged;
}

function websocketUrl(path: string, transport: EvidenceTransport): URL {
	const url = new URL(path, transport.locationHref);
	url.protocol = transport.secure ? 'wss:' : 'ws:';
	return url;
}

function defaultTransport(): EvidenceTransport {
	return {
		fetch: globalThis.fetch.bind(globalThis),
		createWebSocket: (url) => new WebSocket(url),
		locationHref: window.location.href,
		secure: window.location.protocol === 'https:',
		setTimer: (callback, delayMs) => setTimeout(callback, delayMs),
		clearTimer: (timer) => clearTimeout(timer)
	};
}

export async function connectLiveEvidence(
	callId: string,
	callbacks: EvidenceCallbacks,
	transport: EvidenceTransport = defaultTransport()
): Promise<() => void> {
	let stopped = false;
	let socket: WebSocket | undefined;
	let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
	let events: readonly ServerEvent[] = [];

	const emit = (state: EvidenceConnectionState): void => {
		if (!stopped) callbacks.onState(state);
	};
	const publish = (incoming: readonly unknown[]): void => {
		events = mergePersistedEvidence(events, incoming, callId);
		callbacks.onSnapshot(events);
	};
	const recover = async (): Promise<void> => {
		const response = await transport.fetch(API_ROUTES.evidence(callId));
		if (!response.ok) throw new Error(`Evidence recovery failed with HTTP ${response.status}.`);
		const body = (await response.json()) as EvidenceResponse;
		if (body.api_version !== PROTOCOL_VERSION || body.call_id !== callId || !Array.isArray(body.events)) {
			throw new Error('Evidence recovery failed the v0 call contract.');
		}
		publish(body.events);
	};

	const connect = async (): Promise<void> => {
		if (stopped) return;
		emit(events.length === 0 ? 'connecting' : 'degraded');
		try {
			await recover();
			if (events.at(-1)?.type === 'disposition') {
				emit('complete');
				return;
			}
			const afterSequence = events.at(-1)?.seq ?? 0;
			socket = transport.createWebSocket(
				websocketUrl(API_ROUTES.evidenceWebSocket(callId, afterSequence), transport)
			);
			socket.addEventListener('open', () => emit('live'));
			socket.addEventListener('message', (message) => {
				try {
					publish([JSON.parse(String(message.data))]);
					if (events.at(-1)?.type === 'disposition') emit('complete');
				} catch {
					emit('degraded');
					socket?.close(1008, 'Invalid persisted evidence');
				}
			});
			socket.addEventListener('error', () => emit('degraded'));
			socket.addEventListener('close', () => {
				if (stopped || events.at(-1)?.type === 'disposition') return;
				emit('degraded');
				reconnectTimer = transport.setTimer(() => void connect(), 250);
			});
		} catch {
			emit('degraded');
			reconnectTimer = transport.setTimer(() => void connect(), 250);
		}
	};

	await connect();
	return () => {
		stopped = true;
		if (reconnectTimer !== undefined) transport.clearTimer(reconnectTimer);
		socket?.close(1000, 'Operator console closed');
	};
}
