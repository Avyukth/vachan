<script lang="ts">
	import { startPcm16Capture, type PcmCaptureSession } from '$lib/audio/pcm16';

	type SpikeState = 'idle' | 'connecting' | 'streaming' | 'finishing' | 'finished' | 'failed';

	let spikeState = $state<SpikeState>('idle');
	let detail = $state('Use wired headphones, then start from this user gesture.');
	let transcript = $state('');
	let processingLatency = $state<number | null>(null);
	let sourceSampleRate = $state<number | null>(null);
	let session: PcmCaptureSession | null = null;

	function handleEvent(message: unknown): void {
		if (!message || typeof message !== 'object') return;
		const event = message as {
			type?: string;
			detail?: string;
			payload?: {
				type?: string;
				data?: { transcript?: string; metrics?: { processing_latency?: number } };
			};
		};
		if (event.type === 'ready') {
			spikeState = 'streaming';
			detail = 'Streaming mono PCM16 at 16 kHz to the backend relay.';
		} else if (event.type === 'sarvam_stream' && event.payload?.type === 'data') {
			transcript = [transcript, event.payload.data?.transcript].filter(Boolean).join(' ');
			processingLatency = event.payload.data?.metrics?.processing_latency ?? null;
		} else if (event.type === 'error') {
			spikeState = 'failed';
			detail = event.detail ?? 'Streaming failed closed.';
		}
	}

	async function start(): Promise<void> {
		spikeState = 'connecting';
		detail = 'Requesting microphone and opening the PCM relay.';
		try {
			session = await startPcm16Capture(handleEvent);
			sourceSampleRate = session.sourceSampleRate;
		} catch (error) {
			spikeState = 'failed';
			detail = error instanceof Error ? error.message : 'Audio capture could not start.';
		}
	}

	async function finish(): Promise<void> {
		if (!session) return;
		spikeState = 'finishing';
		detail = 'Microphone stopped; flushing the final Saaras segment.';
		await session.finishInput();
		spikeState = 'finished';
		detail = 'Input finished. Final transcript events may still arrive on the open socket.';
	}
</script>

<svelte:head>
	<title>Vachan PCM Transport Spike</title>
</svelte:head>

<main class="spike-shell">
	<header>
		<div>
			<p class="eyebrow">TRANSPORT SPIKE · NOT THE OPERATOR FLOW</p>
			<h1>PCM16 → Saaras v3</h1>
		</div>
		<p class="demo-badge">DEMO / MOCK DATA</p>
	</header>

	<section class="spike-grid">
		<article>
			<p class="section-label">CAPTURE</p>
			<h2>Browser AudioWorklet</h2>
			<p>{detail}</p>
			<dl>
				<div><dt>STATE</dt><dd>{spikeState.toUpperCase()}</dd></div>
				<div><dt>SOURCE RATE</dt><dd>{sourceSampleRate ?? '—'} Hz</dd></div>
				<div><dt>WIRE FORMAT</dt><dd>MONO PCM16 · 16,000 Hz</dd></div>
			</dl>
			<div class="actions">
				<button
					type="button"
					onclick={start}
					disabled={spikeState !== 'idle' && spikeState !== 'failed'}
				>
					Start live spike
				</button>
				<button type="button" onclick={finish} disabled={spikeState !== 'streaming'}>
					Finish input
				</button>
			</div>
		</article>

		<article>
			<p class="section-label">ROUND TRIP</p>
			<h2>Finalized transcript</h2>
			<blockquote lang="hi">{transcript || 'Speak after the relay reports STREAMING.'}</blockquote>
			<dl>
				<div><dt>PROCESSING LATENCY</dt><dd>{processingLatency ?? '—'} s</dd></div>
			</dl>
		</article>
	</section>
</main>

<style>
	.spike-shell {
		width: min(100% - 2rem, 70rem);
		margin: 0 auto;
		padding-bottom: 4rem;
	}

	header {
		min-height: 6rem;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		border-bottom: 1px solid var(--color-seam);
	}

	h1,
	h2 {
		margin-top: 0.4rem;
	}

	.spike-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 1rem;
		padding-top: 3rem;
	}

	article {
		border: 1px solid var(--color-seam);
		border-radius: 1rem;
		padding: 1.25rem;
		background: var(--color-panel);
	}

	article > p:not(.section-label),
	blockquote {
		margin: 1rem 0;
		color: var(--color-muted);
		line-height: 1.6;
	}

	blockquote {
		min-height: 8rem;
		border-left: 3px solid var(--color-held);
		padding-left: 1rem;
		color: var(--color-text);
	}

	dl > div {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
		border-top: 1px solid var(--color-seam);
		padding: 0.75rem 0;
		font-family: var(--font-mono);
		font-size: 0.75rem;
	}

	dd {
		margin: 0;
		text-align: right;
	}

	.actions {
		display: flex;
		gap: 0.75rem;
		margin-top: 1rem;
	}

	.actions button {
		flex: 1;
	}

	.actions button:last-child {
		border-color: var(--color-seam);
		background: transparent;
		color: var(--color-text);
	}

	@media (max-width: 44rem) {
		.spike-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
