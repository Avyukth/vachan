export const AUDIO_SPIKE_ENV = 'VACHAN_ENABLE_AUDIO_SPIKE';

export function audioSpikeEnabled(environment: Record<string, string | undefined>): boolean {
	return environment[AUDIO_SPIKE_ENV] === '1';
}
