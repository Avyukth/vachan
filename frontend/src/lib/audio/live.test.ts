import { describe, expect, test } from 'bun:test';

import { decodeBase64Audio, parseLiveVoiceFrame } from './live';

describe('live voice frames', () => {
	test('accepts one bounded WAV response with honest stage timings', () => {
		const frame = parseLiveVoiceFrame({
			api_version: 'v0',
			type: 'agent_audio',
			source: 'transient_media',
			call_id: 'call-live-001',
			media_seq: 2,
			ts: '2026-07-26T12:00:01+05:30',
			kind: 'turn',
			final_media: false,
			audio_base64: 'UklGRg==',
			content_type: 'audio/wav',
			speech_text: 'एक सुरक्षित उत्तर।',
			timings: {
				stt_ms: 320,
				llm_ms: 410,
				tts_ms: 520,
				total_ms: 1260
			}
		}, { expectedCallId: 'call-live-001', afterMediaSeq: 1 });

		expect(frame?.type).toBe('agent_audio');
		if (frame?.type !== 'agent_audio') throw new Error('expected an agent audio frame');
		expect(frame.call_id).toBe('call-live-001');
		expect(frame.media_seq).toBe(2);
		expect(frame.source).toBe('transient_media');
		expect(frame.timings?.total_ms).toBe(1260);
	});

	test('accepts the fixed opening frame before measured caller turns', () => {
		const frame = parseLiveVoiceFrame({
			api_version: 'v0',
			type: 'agent_audio',
			source: 'transient_media',
			kind: 'opening',
			call_id: 'call-live-001',
			media_seq: 1,
			ts: '2026-07-26T12:00:00Z',
			final_media: false,
			audio_base64: 'UklGRg==',
			content_type: 'audio/wav',
			speech_text: 'सुरक्षित शुरुआत।'
		}, { expectedCallId: 'call-live-001' });

		expect(frame?.type).toBe('agent_audio');
		if (frame?.type !== 'agent_audio') throw new Error('expected an agent audio frame');
		expect(frame.kind).toBe('opening');
		expect(frame.timings).toBeNull();
	});

	test('rejects malformed or internally impossible timing payloads', () => {
		expect(
			parseLiveVoiceFrame({
				api_version: 'v0',
				type: 'agent_audio',
				source: 'transient_media',
				call_id: 'call-live-001',
				media_seq: 1,
				ts: '2026-07-26T12:00:00Z',
				kind: 'turn',
				final_media: false,
				audio_base64: 'UklGRg==',
				content_type: 'audio/wav',
				speech_text: 'safe',
				timings: { stt_ms: 400, llm_ms: 400, tts_ms: 400, total_ms: 1000 }
			}, { expectedCallId: 'call-live-001' })
		).toBeNull();
		expect(
			parseLiveVoiceFrame({
				api_version: 'v0',
				type: 'agent_audio',
				call_id: '',
				source: 'transient_media',
				media_seq: 1,
				ts: '2026-07-26T12:00:00Z',
				kind: 'turn',
				final_media: false,
				audio_base64: 'UklGRg==',
				content_type: 'audio/wav',
				speech_text: 'safe',
				timings: { stt_ms: 0, llm_ms: 0, tts_ms: 0, total_ms: 0 }
			}, { expectedCallId: 'call-live-001' })
		).toBeNull();
		expect(
			parseLiveVoiceFrame({
				api_version: 'v0',
				type: 'agent_audio',
				source: 'transient_media',
				call_id: 'call-live-001',
				media_seq: 1,
				ts: '2026-07-26T12:00:00Z',
				kind: 'turn',
				final_media: false,
				audio_base64: 'UklGRg==',
				content_type: 'audio/wav',
				speech_text: 'safe',
				timings: { stt_ms: 0.5, llm_ms: 0, tts_ms: 0, total_ms: 0.5 }
			}, { expectedCallId: 'call-live-001' })
		).toBeNull();
	});

	test('rejects legacy, wrong-call, stale, and post-terminal audio', () => {
		const frame = {
			api_version: 'v0',
			type: 'agent_audio',
			source: 'transient_media',
			call_id: 'call-live-001',
			media_seq: 2,
			ts: '2026-07-26T12:00:01Z',
			kind: 'turn',
			final_media: false,
			audio_base64: 'UklGRg==',
			content_type: 'audio/wav',
			speech_text: 'safe'
		};

		expect(
			parseLiveVoiceFrame({ ...frame, type: 'agent_turn' }, { expectedCallId: 'call-live-001' })
		).toBeNull();
		expect(parseLiveVoiceFrame(frame, { expectedCallId: 'call-other' })).toBeNull();
		expect(
			parseLiveVoiceFrame(frame, { expectedCallId: 'call-live-001', afterMediaSeq: 2 })
		).toBeNull();
		expect(
			parseLiveVoiceFrame(frame, { expectedCallId: 'call-live-001', acceptAudio: false })
		).toBeNull();
	});

	test('accepts only versioned call-correlated control frames', () => {
		expect(
			parseLiveVoiceFrame(
				{
					api_version: 'v0',
					type: 'ready',
					call_id: 'call-live-001',
					sample_rate: 16_000,
					encoding: 'pcm_s16le'
				},
				{ expectedCallId: 'call-live-001' }
			)
		).toEqual({
			api_version: 'v0',
			type: 'ready',
			call_id: 'call-live-001',
			sample_rate: 16_000,
			encoding: 'pcm_s16le'
		});
		expect(
			parseLiveVoiceFrame(
				{
					api_version: 'v0',
					type: 'transport_error',
					call_id: 'call-live-001',
					detail: 'closed safely'
				},
				{ expectedCallId: 'call-live-001' }
			)
		).toEqual({
			api_version: 'v0',
			type: 'transport_error',
			call_id: 'call-live-001',
			detail: 'closed safely'
		});
		expect(
			parseLiveVoiceFrame(
				{
					type: 'ready',
					call_id: 'call-live-001',
					sample_rate: 16_000,
					encoding: 'pcm_s16le'
				},
				{ expectedCallId: 'call-live-001' }
			)
		).toBeNull();
	});

	test('decodes the base64 audio without treating it as text', () => {
		const decoded = new Uint8Array(decodeBase64Audio('UklGRg=='));
		expect(Array.from(decoded)).toEqual([82, 73, 70, 70]);
	});

	test('rejects empty audio', () => {
		let message = '';
		try {
			decodeBase64Audio('');
		} catch (error) {
			message = error instanceof Error ? error.message : 'unexpected error';
		}
		expect(message).toBe('Agent audio payload is empty.');
	});
});
