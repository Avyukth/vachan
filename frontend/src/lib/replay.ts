import { PROTOCOL_VERSION, type EventType, type ServerEvent } from '$lib/protocol';

export type ReplayFixture = 'happy' | 'third_party' | 'takeover';

interface ReplayStartResponse {
	readonly api_version: typeof PROTOCOL_VERSION;
	readonly replay: true;
	readonly replay_label: 'REPLAY — recorded sequence';
	readonly call_id: string;
	readonly websocket_path: string;
}

export interface ReplayCallbacks {
	readonly onOpen: (label: string) => void;
	readonly onEvent: (event: ServerEvent) => void;
	readonly onComplete: () => void;
	readonly onError: (message: string) => void;
}

const eventTypes = new Set<EventType>([
	'state_change',
	'utterance',
	'tool_decision',
	'guard_block',
	'disposition',
	'error'
]);

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseReplayEvent(value: unknown): ServerEvent | null {
	if (!isRecord(value) || !isRecord(value.payload)) return null;
	if (value.api_version !== PROTOCOL_VERSION) return null;
	if (typeof value.type !== 'string' || !eventTypes.has(value.type as EventType)) return null;
	if (typeof value.call_id !== 'string' || value.call_id.length === 0) return null;
	if (!Number.isInteger(value.seq) || (value.seq as number) <= 0) return null;
	if (typeof value.ts !== 'string' || Number.isNaN(Date.parse(value.ts))) return null;
	if (value.payload.source !== 'recorded_replay') return null;
	if (value.payload.replay_label !== 'REPLAY — recorded sequence') return null;
	return value as unknown as ServerEvent;
}

function websocketUrl(path: string): URL {
	const url = new URL(path, window.location.href);
	url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	return url;
}

export async function connectReplay(
	fixture: ReplayFixture,
	callbacks: ReplayCallbacks
): Promise<() => void> {
	const response = await fetch('/api/dev/replay', {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ api_version: PROTOCOL_VERSION, fixture })
	});

	if (!response.ok) {
		const detail =
			response.status === 404
				? 'Replay is disabled. Start the backend with DEV_REPLAY=1.'
				: `Replay could not start (HTTP ${response.status}).`;
		throw new Error(detail);
	}

	const start = (await response.json()) as ReplayStartResponse;
	if (
		start.api_version !== PROTOCOL_VERSION ||
		start.replay !== true ||
		start.replay_label !== 'REPLAY — recorded sequence'
	) {
		throw new Error('Replay start response failed the honesty/version contract.');
	}

	const socket = new WebSocket(websocketUrl(start.websocket_path));
	let lastSequence = 0;
	let completed = false;

	socket.addEventListener('open', () => callbacks.onOpen(start.replay_label));
	socket.addEventListener('message', (message) => {
		let parsed: unknown;
		try {
			parsed = JSON.parse(String(message.data));
		} catch {
			callbacks.onError('Replay emitted malformed JSON.');
			socket.close(1008, 'Malformed replay event');
			return;
		}

		const event = parseReplayEvent(parsed);
		if (event === null || event.call_id !== start.call_id || event.seq !== lastSequence + 1) {
			callbacks.onError('Replay event failed the v0 sequence or source contract.');
			socket.close(1008, 'Invalid replay event');
			return;
		}

		lastSequence = event.seq;
		completed ||= event.type === 'disposition';
		callbacks.onEvent(event);
	});
	socket.addEventListener('error', () => callbacks.onError('Replay WebSocket failed.'));
	socket.addEventListener('close', (closeEvent) => {
		if (completed && closeEvent.code === 1000) {
			callbacks.onComplete();
		} else if (closeEvent.code !== 1000) {
			callbacks.onError('Replay ended before a disposition event.');
		}
	});

	return () => socket.close(1000, 'Replay panel closed');
}
