/**
 * Browser playback boundary for Bulbul WAV audio.
 *
 * Call `unlock()` directly from the Start/audio-check click. Every new `play`
 * supersedes pending decode and current playback; End and Takeover call
 * `stop()` to silence the agent synchronously.
 */

export type PlaybackResult = 'completed' | 'cancelled';

interface ActivePlayback {
	readonly source: AudioBufferSourceNode;
	readonly settle: (result: PlaybackResult) => void;
}

export class AgentAudioPlayback {
	private context: AudioContext | undefined;
	private active: ActivePlayback | undefined;
	private generation = 0;
	private closed = false;

	get isUnlocked(): boolean {
		return this.context?.state === 'running';
	}

	async unlock(): Promise<void> {
		if (this.closed) throw new Error('Audio playback has been closed.');
		this.context ??= new AudioContext({ latencyHint: 'interactive' });
		await this.context.resume();

		// Starting an inaudible buffer inside the user gesture unlocks playback
		// on browsers that otherwise defer the first real response.
		const silent = this.context.createBuffer(1, 1, this.context.sampleRate);
		const source = this.context.createBufferSource();
		source.buffer = silent;
		source.connect(this.context.destination);
		source.start();
	}

	async play(audio: ArrayBuffer): Promise<PlaybackResult> {
		if (!this.isUnlocked || this.context === undefined) {
			throw new Error('Audio must be unlocked from a user gesture before playback.');
		}
		if (audio.byteLength === 0) throw new Error('Cannot play an empty audio response.');

		this.stop();
		const requestedGeneration = this.generation;
		const decoded = await this.context.decodeAudioData(audio.slice(0));
		if (requestedGeneration !== this.generation || this.closed) return 'cancelled';

		const source = this.context.createBufferSource();
		source.buffer = decoded;
		source.connect(this.context.destination);

		return await new Promise<PlaybackResult>((resolve) => {
			let settled = false;
			const settle = (result: PlaybackResult): void => {
				if (settled) return;
				settled = true;
				source.disconnect();
				if (this.active?.source === source) this.active = undefined;
				resolve(result);
			};

			this.active = { source, settle };
			source.addEventListener('ended', () => settle('completed'), { once: true });
			source.start();
		});
	}

	stop(): void {
		this.generation += 1;
		const active = this.active;
		this.active = undefined;
		if (active === undefined) return;

		try {
			active.source.stop();
		} catch {
			// A source that ended between the state check and stop is already silent.
		}
		active.settle('cancelled');
	}

	async close(): Promise<void> {
		if (this.closed) return;
		this.closed = true;
		this.stop();
		await this.context?.close();
		this.context = undefined;
	}
}

export async function fetchAudioCheck(signal?: AbortSignal): Promise<ArrayBuffer> {
	const response = await fetch('/api/audio/check', {
		method: 'POST',
		headers: { accept: 'audio/wav' },
		signal
	});
	if (!response.ok) {
		throw new Error(
			response.status === 504
				? 'Bulbul timed out. Check the network, then retry.'
				: `Bulbul audio check failed (HTTP ${response.status}).`
		);
	}
	if (!response.headers.get('content-type')?.startsWith('audio/wav')) {
		throw new Error('Bulbul returned an unexpected audio format.');
	}
	return await response.arrayBuffer();
}
