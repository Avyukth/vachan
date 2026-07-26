import { describe, expect, test } from 'bun:test';

import { decodeBase64Audio, parseLiveVoiceFrame } from './live';

describe('live voice frames', () => {
	test('accepts one bounded WAV response with honest stage timings', () => {
		const frame = parseLiveVoiceFrame({
			type: 'agent_audio',
			call_id: 'call-live-001',
			audio_base64: 'UklGRg==',
			content_type: 'audio/wav',
			speech_text: 'एक सुरक्षित उत्तर।',
			timings: {
				stt_ms: 320,
				llm_ms: 410,
				tts_ms: 520,
				total_ms: 1260
			}
		});

		expect(frame?.type).toBe('agent_audio');
		if (frame?.type !== 'agent_audio') throw new Error('expected an agent audio frame');
		expect(frame.call_id).toBe('call-live-001');
		expect(frame.timings?.total_ms).toBe(1260);
	});

	test('accepts the fixed opening frame before measured caller turns', () => {
		const frame = parseLiveVoiceFrame({
			type: 'agent_turn',
			kind: 'opening',
			call_id: 'call-live-001',
			audio_base64: 'UklGRg==',
			content_type: 'audio/wav',
			speech_text: 'सुरक्षित शुरुआत।'
		});

		expect(frame?.type).toBe('agent_audio');
		if (frame?.type !== 'agent_audio') throw new Error('expected an agent audio frame');
		expect(frame.kind).toBe('opening');
		expect(frame.timings).toBeNull();
	});

	test('rejects malformed or internally impossible timing payloads', () => {
		expect(
			parseLiveVoiceFrame({
				type: 'agent_audio',
				call_id: 'call-live-001',
				audio_base64: 'UklGRg==',
				content_type: 'audio/wav',
				speech_text: 'safe',
				timings: { stt_ms: 400, llm_ms: 400, tts_ms: 400, total_ms: 1000 }
			})
		).toBeNull();
		expect(
			parseLiveVoiceFrame({
				type: 'agent_audio',
				call_id: '',
				audio_base64: 'UklGRg==',
				content_type: 'audio/wav',
				speech_text: 'safe',
				timings: { stt_ms: 0, llm_ms: 0, tts_ms: 0, total_ms: 0 }
			})
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
