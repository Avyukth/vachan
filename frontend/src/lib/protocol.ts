/**
 * TypeScript mirror of backend/app/protocol.py's frozen v0 wire contract.
 *
 * Server events always mirror evidence-ledger rows. UI code may present these
 * values, but must never synthesize domain state or dispositions locally.
 */

export const PROTOCOL_VERSION = 'v0' as const;
export type ProtocolVersion = typeof PROTOCOL_VERSION;

export const API_ROUTES = {
	cases: '/api/cases',
	preflight: '/api/preflight',
	callStart: '/api/call/start',
	callEnd: '/api/call/end',
	takeover: '/api/takeover',
	reset: '/api/reset',
	utterance: '/api/utterance',
	evidence: (callId: string) => `/api/evidence/${encodeURIComponent(callId)}`,
	evidenceWebSocket: (callId: string, afterSeq: number) =>
		`/ws/evidence/${encodeURIComponent(callId)}?after_seq=${afterSeq}`,
	callWebSocket: (callId: string) => `/ws/call/${encodeURIComponent(callId)}`
} as const;

export interface ProtocolMessage {
	readonly api_version: ProtocolVersion;
}

export type PreflightResult = 'READY' | 'BLOCKED_POLICY' | 'BLOCKED_TECHNICAL';

export type EventType =
	| 'state_change'
	| 'utterance'
	| 'tool_decision'
	| 'guard_block'
	| 'disposition'
	| 'error';

export type TransportMode = 'streaming_pcm16_ws' | 'turn_based_rest';

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | readonly JsonValue[] | { readonly [key: string]: JsonValue };

export interface CaseSummary extends ProtocolMessage {
	readonly case_id: string;
	readonly borrower_display_name: string;
	readonly eligible: boolean;
	readonly contact_cap_remaining: number;
	readonly mock_data: true;
}

export interface CasesResponse extends ProtocolMessage {
	readonly cases: readonly CaseSummary[];
}

export interface PreflightRequest extends ProtocolMessage {
	readonly case_id: string;
}

export interface PreflightCheck extends ProtocolMessage {
	readonly name: string;
	readonly pass: boolean;
	readonly detail: string;
}

export interface PreflightResponse extends ProtocolMessage {
	readonly result: PreflightResult;
	readonly checks: readonly PreflightCheck[];
}

export interface StartCallRequest extends ProtocolMessage {
	readonly case_id: string;
}

export interface StartCallResponse extends ProtocolMessage {
	readonly call_id: string;
}

export interface EndCallRequest extends ProtocolMessage {
	readonly call_id: string;
	readonly reason: string;
}

export interface TakeoverRequest extends ProtocolMessage {
	readonly call_id: string;
}

export interface ResetResponse extends ProtocolMessage {
	readonly reset: true;
	readonly seeded_case_count: number;
}

export interface UtteranceMetadata extends ProtocolMessage {
	readonly call_id: string;
	readonly content_type: string;
}

export interface ServerEvent extends ProtocolMessage {
	readonly type: EventType;
	readonly call_id: string;
	readonly seq: number;
	/** ISO-8601 timestamp with an explicit timezone offset. */
	readonly ts: string;
	readonly payload: Readonly<Record<string, JsonValue>>;
}

export interface EvidenceResponse extends ProtocolMessage {
	readonly call_id: string;
	readonly events: readonly ServerEvent[];
}

export const UTTERANCE_AUDIO_FORM_FIELD = 'audio' as const;
export const UTTERANCE_CONTENT_TYPES = ['audio/wav', 'audio/webm', 'audio/ogg'] as const;
