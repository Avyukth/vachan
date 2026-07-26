import { PROTOCOL_VERSION } from '$lib/protocol';

export interface TurnTimings {
	readonly stt_ms: number;
	readonly llm_ms: number;
	readonly tts_ms: number;
	readonly total_ms: number;
}

export interface LiveReadyFrame {
	readonly api_version: typeof PROTOCOL_VERSION;
	readonly type: 'ready';
	readonly call_id: string;
	readonly sample_rate: number;
	readonly encoding: 'pcm_s16le';
}

export interface LiveAgentAudioFrame {
	readonly api_version: typeof PROTOCOL_VERSION;
	readonly type: 'agent_audio';
	readonly source: 'transient_media';
	readonly call_id: string;
	readonly media_seq: number;
	readonly ts: string;
	readonly kind: 'opening' | 'turn' | 'recovery';
	readonly final_media: boolean;
	readonly audio_base64: string;
	readonly content_type: 'audio/wav';
	readonly speech_text: string;
	readonly timings: TurnTimings | null;
}

export interface LiveTransportErrorFrame {
	readonly api_version: typeof PROTOCOL_VERSION;
	readonly type: 'transport_error';
	readonly call_id: string;
	readonly detail: string;
}

export type LiveVoiceFrame = LiveReadyFrame | LiveAgentAudioFrame | LiveTransportErrorFrame;

export interface LiveVoiceFramePolicy {
	readonly expectedCallId: string;
	readonly afterMediaSeq?: number;
	readonly acceptAudio?: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonNegativeInteger(value: unknown): value is number {
	return Number.isInteger(value) && (value as number) >= 0;
}

function isPositiveInteger(value: unknown): value is number {
	return Number.isInteger(value) && (value as number) > 0;
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
	const allowedKeys = new Set(allowed);
	return Object.keys(value).every((key) => allowedKeys.has(key));
}

function isTimezoneAwareTimestamp(value: unknown): value is string {
	if (typeof value !== 'string') return false;
	const match =
		/^(?<year>\d{4})-(?<month>\d{2})-(?<day>\d{2})T(?<hour>\d{2}):(?<minute>\d{2}):(?<second>\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/u.exec(
			value
		);
	if (!match?.groups || Number.isNaN(Date.parse(value))) return false;

	const year = Number(match.groups.year);
	const month = Number(match.groups.month);
	const day = Number(match.groups.day);
	const hour = Number(match.groups.hour);
	const minute = Number(match.groups.minute);
	const second = Number(match.groups.second);
	if (year < 1 || hour > 23 || minute > 59 || second > 59) return false;

	const calendarProbe = new Date(Date.UTC(year, month - 1, day));
	return (
		calendarProbe.getUTCFullYear() === year &&
		calendarProbe.getUTCMonth() === month - 1 &&
		calendarProbe.getUTCDate() === day
	);
}

function isExpectedCall(value: unknown, policy: LiveVoiceFramePolicy): value is string {
	return (
		typeof value === 'string' &&
		value.trim().length > 0 &&
		value === policy.expectedCallId
	);
}

function parseTimings(value: unknown): TurnTimings | null {
	if (
		!isRecord(value) ||
		!hasOnlyKeys(value, ['stt_ms', 'llm_ms', 'tts_ms', 'total_ms'])
	) {
		return null;
	}
	const { stt_ms, llm_ms, tts_ms, total_ms } = value;
	if (
		!isNonNegativeInteger(stt_ms) ||
		!isNonNegativeInteger(llm_ms) ||
		!isNonNegativeInteger(tts_ms) ||
		!isNonNegativeInteger(total_ms) ||
		total_ms < stt_ms + llm_ms + tts_ms
	) {
		return null;
	}
	return { stt_ms, llm_ms, tts_ms, total_ms };
}

export function parseLiveVoiceFrame(
	value: unknown,
	policy: LiveVoiceFramePolicy
): LiveVoiceFrame | null {
	if (
		!isRecord(value) ||
		value.api_version !== PROTOCOL_VERSION ||
		!policy.expectedCallId.trim() ||
		!isExpectedCall(value.call_id, policy)
	) {
		return null;
	}

	if (
		value.type === 'ready' &&
		hasOnlyKeys(value, ['api_version', 'type', 'call_id', 'sample_rate', 'encoding']) &&
		isPositiveInteger(value.sample_rate) &&
		value.encoding === 'pcm_s16le'
	) {
		return {
			api_version: PROTOCOL_VERSION,
			type: 'ready',
			call_id: value.call_id,
			sample_rate: value.sample_rate,
			encoding: value.encoding
		};
	}

	if (
		value.type === 'transport_error' &&
		hasOnlyKeys(value, ['api_version', 'type', 'call_id', 'detail']) &&
		typeof value.detail === 'string' &&
		value.detail.trim().length > 0
	) {
		return {
			api_version: PROTOCOL_VERSION,
			type: 'transport_error',
			call_id: value.call_id,
			detail: value.detail
		};
	}

	if (
		value.type !== 'agent_audio' ||
		!hasOnlyKeys(value, [
			'api_version',
			'type',
			'source',
			'call_id',
			'media_seq',
			'ts',
			'kind',
			'final_media',
			'audio_base64',
			'content_type',
			'speech_text',
			'timings'
		]) ||
		value.source !== 'transient_media' ||
		policy.acceptAudio === false ||
		!isPositiveInteger(value.media_seq) ||
		value.media_seq <= (policy.afterMediaSeq ?? 0) ||
		!isTimezoneAwareTimestamp(value.ts) ||
		(value.kind !== 'opening' && value.kind !== 'turn' && value.kind !== 'recovery') ||
		typeof value.final_media !== 'boolean' ||
		typeof value.audio_base64 !== 'string' ||
		value.audio_base64.length === 0 ||
		value.content_type !== 'audio/wav' ||
		typeof value.speech_text !== 'string' ||
		value.speech_text.trim().length === 0
	) {
		return null;
	}
	const timings =
		value.timings === undefined || value.timings === null ? null : parseTimings(value.timings);
	if (value.timings !== undefined && value.timings !== null && timings === null) return null;
	return {
		api_version: PROTOCOL_VERSION,
		type: 'agent_audio',
		source: 'transient_media',
		call_id: value.call_id,
		media_seq: value.media_seq,
		ts: value.ts,
		kind: value.kind,
		final_media: value.final_media,
		audio_base64: value.audio_base64,
		content_type: value.content_type,
		speech_text: value.speech_text,
		timings
	};
}

export function decodeBase64Audio(encoded: string): ArrayBuffer {
	if (!encoded) throw new Error('Agent audio payload is empty.');
	let binary: string;
	try {
		binary = atob(encoded);
	} catch {
		throw new Error('Agent audio payload is not valid base64.');
	}
	if (binary.length === 0) throw new Error('Agent audio payload decoded to an empty buffer.');

	const bytes = new Uint8Array(binary.length);
	for (let index = 0; index < binary.length; index += 1) {
		bytes[index] = binary.charCodeAt(index);
	}
	return bytes.buffer;
}
