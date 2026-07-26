import { describe, expect, test } from 'bun:test';

import { AUDIO_SPIKE_ENV, audioSpikeEnabled } from './spikeGate';

declare const Bun: {
	file(path: URL): { text(): Promise<string> };
};

const serverGateSource = await Bun.file(
	new URL('../../routes/audio-spike/+page.server.ts', import.meta.url)
).text();

describe('development audio-spike gate', () => {
	test('requires the exact explicit opt-in value', () => {
		expect(audioSpikeEnabled({})).toBe(false);
		expect(audioSpikeEnabled({ [AUDIO_SPIKE_ENV]: '' })).toBe(false);
		expect(audioSpikeEnabled({ [AUDIO_SPIKE_ENV]: 'true' })).toBe(false);
		expect(audioSpikeEnabled({ [AUDIO_SPIKE_ENV]: '1' })).toBe(true);
	});

	test('keeps the route server-only and unavailable by default', () => {
		expect(serverGateSource).toContain("'$env/dynamic/private'");
		expect(serverGateSource).toContain('error(404');
		expect(serverGateSource).toContain('audioSpikeEnabled(env)');
	});
});
