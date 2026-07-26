import { describe, expect, test } from 'bun:test';

import {
	CALLER_FIXTURES,
	assertCallerFixture,
	decodeSimulatedCallerSocketMessage,
	floatToPcm16
} from './simCaller';
import { SIM_CALLER_ENV, SIM_CALLER_LABEL, simulatedCallerEnabled } from './simCallerGate';

/** Returns the thrown message, or null when nothing was thrown. */
function thrownMessage(run: () => unknown): string | null {
	try {
		run();
		return null;
	} catch (error: unknown) {
		return error instanceof Error ? error.message : String(error);
	}
}

describe('simulated-caller gate', () => {
	test('is unavailable unless the explicit flag is set', () => {
		expect(simulatedCallerEnabled({})).toBe(false);
		// DEV alone must not enable it: the venue laptop runs a preview build.
		expect(simulatedCallerEnabled({ DEV: 'true' })).toBe(false);
		expect(simulatedCallerEnabled({ [SIM_CALLER_ENV]: '0' })).toBe(false);
		expect(simulatedCallerEnabled({ [SIM_CALLER_ENV]: 'true' })).toBe(false);
		expect(simulatedCallerEnabled({ [SIM_CALLER_ENV]: '1' })).toBe(true);
	});

	test('states plainly that the audio is prerecorded', () => {
		expect(SIM_CALLER_LABEL).toContain('SIMULATED CALLER');
		expect(SIM_CALLER_LABEL).toContain('PRERECORDED');
	});
});

describe('agent clips are ineligible by construction', () => {
	test('refuses any fixture that would speak as Vachan', () => {
		expect(
			thrownMessage(() => assertCallerFixture('/fixtures/01_agent_blind-greeting.wav'))
		).toContain('never Vachan');
		expect(
			thrownMessage(() =>
				assertCallerFixture('/demo_video/hi-IN/08_agent_dual-format-readback.wav')
			)
		).toContain('never Vachan');
	});

	test('accepts every catalogued caller fixture', () => {
		for (const fixture of CALLER_FIXTURES) {
			expect(thrownMessage(() => assertCallerFixture(fixture.url))).toBe(null);
		}
	});

	test('ships only caller-side fixtures, each tagged with its path kind', () => {
		expect(CALLER_FIXTURES.length).toBe(8);
		for (const fixture of CALLER_FIXTURES) {
			expect(fixture.url.includes('_agent_')).toBe(false);
			expect(['HAPPY', 'NON-HAPPY', 'BLOCKER'].includes(fixture.pathKind)).toBe(true);
		}
	});

	test('happy caller is ordered as four separately flushed utterances', () => {
		const happy = CALLER_FIXTURES.filter((fixture) => fixture.pathKind === 'HAPPY');

		expect(happy.map((fixture) => fixture.id)).toEqual([
			'happy_1_claim',
			'happy_2_birthdate',
			'happy_3_reference',
			'happy_4_promise'
		]);
		expect(happy.map((fixture) => fixture.url)).toEqual([
			'/fixtures/audio_turn_happy_1_claim.wav',
			'/fixtures/audio_turn_happy_2_birthdate.wav',
			'/fixtures/audio_turn_happy_3_reference.wav',
			'/fixtures/audio_turn_happy_4_promise.wav'
		]);
	});
});

describe('floatToPcm16', () => {
	test('maps the full range without wrapping at the extremes', () => {
		const pcm = floatToPcm16(new Float32Array([0, 1, -1, 0.5, -0.5]));
		expect(pcm[0]).toBe(0);
		expect(pcm[1]).toBe(32767);
		expect(pcm[2]).toBe(-32768);
		expect(pcm[3]).toBe(16384);
		expect(pcm[4]).toBe(-16384);
	});

	test('clamps out-of-range input rather than overflowing', () => {
		const pcm = floatToPcm16(new Float32Array([9, -9]));
		expect(pcm[0]).toBe(32767);
		expect(pcm[1]).toBe(-32768);
	});

	test('preserves sample count so utterance duration is unchanged', () => {
		expect(floatToPcm16(new Float32Array(1600)).length).toBe(1600);
	});
});

describe('local socket diagnostics', () => {
	test('malformed data remains a local error instead of forging a server frame', () => {
		const decoded = decodeSimulatedCallerSocketMessage('{not-json');
		expect(decoded.localError).toContain('unparseable');
		expect(decoded.serverEvent).toBe(undefined);
		expect(JSON.stringify(decoded).includes('transport_error')).toBe(false);
	});

	test('valid server JSON is forwarded unchanged for yy6 validation', () => {
		const frame = { api_version: 'v0', type: 'ready', call_id: 'call-1' };
		const decoded = decodeSimulatedCallerSocketMessage(JSON.stringify(frame));
		expect(decoded.serverEvent).toEqual(frame);
		expect(decoded.localError).toBe(undefined);
	});
});
