import { env } from '$env/dynamic/private';
import { error } from '@sveltejs/kit';

import { audioSpikeEnabled } from '$lib/audio/spikeGate';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = () => {
	if (!audioSpikeEnabled(env)) {
		error(404, 'Not found');
	}

	return {};
};
