export interface TurnTimings {
	readonly stt_ms: number;
	readonly llm_ms: number;
	readonly tts_ms: number;
	readonly total_ms: number;
}

export interface LiveReadyFrame {
	readonly type: 'ready';
	readonly sample_rate: number;
	readonly encoding: 'pcm_s16le';
}

export interface LiveAgentAudioFrame {
	readonly type: 'agent_audio';
	readonly kind: string;
	readonly call_id: string;
	readonly audio_base64: string;
	readonly content_type: 'audio/wav';
	readonly speech_text: string;
	readonly timings: TurnTimings | null;
}

export interface LiveTransportErrorFrame {
	readonly type: 'transport_error';
	readonly detail: string;
}

export type LiveVoiceFrame = LiveReadyFrame | LiveAgentAudioFrame | LiveTransportErrorFrame;

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonNegativeFinite(value: unknown): value is number {
	return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function parseTimings(value: unknown): TurnTimings | null {
	if (!isRecord(value)) return null;
	const { stt_ms, llm_ms, tts_ms, total_ms } = value;
	if (
		!isNonNegativeFinite(stt_ms) ||
		!isNonNegativeFinite(llm_ms) ||
		!isNonNegativeFinite(tts_ms) ||
		!isNonNegativeFinite(total_ms) ||
		total_ms < stt_ms + llm_ms + tts_ms
	) {
		return null;
	}
	return { stt_ms, llm_ms, tts_ms, total_ms };
}

export function parseLiveVoiceFrame(value: unknown): LiveVoiceFrame | null {
	if (!isRecord(value)) return null;

	if (
		value.type === 'ready' &&
		isNonNegativeFinite(value.sample_rate) &&
		value.sample_rate > 0 &&
		value.encoding === 'pcm_s16le'
	) {
		return {
			type: 'ready',
			sample_rate: value.sample_rate,
			encoding: value.encoding
		};
	}

	if (
		value.type === 'transport_error' &&
		typeof value.detail === 'string' &&
		value.detail.trim().length > 0
	) {
		return { type: 'transport_error', detail: value.detail };
	}

	if (
		(value.type !== 'agent_audio' && value.type !== 'agent_turn') ||
		typeof value.call_id !== 'string' ||
		value.call_id.trim().length === 0 ||
		typeof value.audio_base64 !== 'string' ||
		value.audio_base64.length === 0 ||
		value.content_type !== 'audio/wav' ||
		typeof value.speech_text !== 'string' ||
		value.speech_text.trim().length === 0
	) {
		return null;
	}
	const timings = value.timings === undefined ? null : parseTimings(value.timings);
	if (value.timings !== undefined && timings === null) return null;
	return {
		type: 'agent_audio',
		kind: typeof value.kind === 'string' && value.kind ? value.kind : 'turn',
		call_id: value.call_id,
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
