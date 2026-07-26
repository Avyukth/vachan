<script lang="ts">
	import { onDestroy } from 'svelte';

	import { AgentAudioPlayback, fetchAudioCheck } from '$lib/audio';
	import { connectReplay, type ReplayFixture } from '$lib/replay';
	import type { EventType, JsonValue, ServerEvent } from '$lib/protocol';

	type MicrophoneState = 'idle' | 'requesting' | 'ready' | 'blocked' | 'unsupported';
	type AudioOutputState =
		| 'idle'
		| 'requesting'
		| 'playing'
		| 'confirming'
		| 'ready'
		| 'blocked';
	type ReplayState = 'idle' | 'connecting' | 'playing' | 'complete' | 'error';

	let microphoneState = $state<MicrophoneState>('idle');
	let microphoneDetail = $state('Permission has not been requested on this browser.');
	let audioOutputState = $state<AudioOutputState>('idle');
	let audioOutputDetail = $state('Bulbul playback has not been checked through headphones.');
	let replayFixture = $state<ReplayFixture>('happy');
	let replayState = $state<ReplayState>('idle');
	let replayDetail = $state('Backend replay is available only with DEV_REPLAY=1.');
	let replayLabel = $state('');
	let replayEvents = $state<ServerEvent[]>([]);
	let stopReplay: (() => void) | undefined;
	let audioCheckAbort: AbortController | undefined;
	const agentAudio = new AgentAudioPlayback();

	const stateLabels: Record<MicrophoneState, string> = {
		idle: 'NOT CHECKED',
		requesting: 'CHECKING',
		ready: 'READY',
		blocked: 'BLOCKED',
		unsupported: 'UNAVAILABLE'
	};

	const replayStateLabels: Record<ReplayState, string> = {
		idle: 'NOT STARTED',
		connecting: 'CONNECTING',
		playing: 'PLAYING',
		complete: 'COMPLETE',
		error: 'FAILED'
	};

	const audioOutputLabels: Record<AudioOutputState, string> = {
		idle: 'NOT CHECKED',
		requesting: 'CONNECTING',
		playing: 'PLAYING',
		confirming: 'CONFIRM',
		ready: 'READY',
		blocked: 'BLOCKED'
	};

	function payloadString(event: ServerEvent | undefined, key: string): string | undefined {
		const value: JsonValue | undefined = event?.payload[key];
		return typeof value === 'string' ? value : undefined;
	}

	function latestEvent(events: ServerEvent[], type: EventType): ServerEvent | undefined {
		return events.findLast((event) => event.type === type);
	}

	function machineState(events: ServerEvent[], machine: string): string | undefined {
		const transition = events.findLast(
			(event) => event.type === 'state_change' && event.payload.machine === machine
		);
		return payloadString(transition, 'after');
	}

	let latestUtterance = $derived(latestEvent(replayEvents, 'utterance'));
	let latestToolDecision = $derived(latestEvent(replayEvents, 'tool_decision'));
	let identityState = $derived(machineState(replayEvents, 'identity'));
	let promiseState = $derived(machineState(replayEvents, 'promise'));
	let disposition = $derived(payloadString(latestEvent(replayEvents, 'disposition'), 'disposition'));

	async function requestMicrophone(): Promise<void> {
		if (!navigator.mediaDevices?.getUserMedia) {
			microphoneState = 'unsupported';
			microphoneDetail = 'This browser does not provide microphone capture.';
			return;
		}

		microphoneState = 'requesting';
		microphoneDetail = 'Waiting for browser permission.';

		try {
			const stream = await navigator.mediaDevices.getUserMedia({
				audio: {
					channelCount: 1,
					echoCancellation: true,
					noiseSuppression: true
				}
			});

			for (const track of stream.getTracks()) {
				track.stop();
			}

			microphoneState = 'ready';
			microphoneDetail = 'Permission granted. The setup check released the microphone.';
		} catch (error: unknown) {
			microphoneState = 'blocked';
			microphoneDetail =
				error instanceof DOMException && error.name === 'NotAllowedError'
					? 'Permission was denied. Allow microphone access in browser settings, then check again.'
					: 'The microphone could not be opened. Check the selected input device and retry.';
		}
	}

	async function playAudioCheck(): Promise<void> {
		audioCheckAbort?.abort();
		agentAudio.stop();
		audioCheckAbort = new AbortController();
		audioOutputState = 'requesting';
		audioOutputDetail = 'Unlocking browser audio and requesting the fixed Bulbul check line.';

		try {
			// This must happen before the network await, while the click still
			// counts as a browser user gesture.
			await agentAudio.unlock();
			const audio = await fetchAudioCheck(audioCheckAbort.signal);
			audioOutputState = 'playing';
			audioOutputDetail = 'Listen through wired headphones. Open speakers are unsafe.';
			const result = await agentAudio.play(audio);
			if (result === 'cancelled') return;
			audioOutputState = 'confirming';
			audioOutputDetail = 'Confirm only if the full Bulbul line was clear in the headphones.';
		} catch (error: unknown) {
			if (error instanceof DOMException && error.name === 'AbortError') return;
			audioOutputState = 'blocked';
			audioOutputDetail =
				error instanceof Error ? error.message : 'Browser audio output could not be checked.';
		}
	}

	function confirmAudioCheck(): void {
		audioOutputState = 'ready';
		audioOutputDetail = 'Operator confirmed Bulbul playback through wired headphones.';
	}

	function stopAgentAudio(): void {
		audioCheckAbort?.abort();
		agentAudio.stop();
		if (audioOutputState === 'playing' || audioOutputState === 'requesting') {
			audioOutputState = 'idle';
			audioOutputDetail = 'Playback stopped. Run the headphone check again.';
		}
	}

	async function startDevReplay(): Promise<void> {
		stopReplay?.();
		stopReplay = undefined;
		replayEvents = [];
		replayLabel = '';
		replayState = 'connecting';
		replayDetail = 'Requesting a reviewed recorded sequence.';

		try {
			stopReplay = await connectReplay(replayFixture, {
				onOpen: (label) => {
					replayLabel = label;
					replayState = 'playing';
					replayDetail = 'Events below are canned fixtures, never a live call.';
				},
				onEvent: (event) => {
					replayEvents = [...replayEvents, event];
				},
				onComplete: () => {
					replayState = 'complete';
					replayDetail = 'Recorded sequence finished with a disposition.';
				},
				onError: (message) => {
					replayState = 'error';
					replayDetail = message;
				}
			});
		} catch (error: unknown) {
			replayState = 'error';
			replayDetail = error instanceof Error ? error.message : 'Replay could not start.';
		}
	}

	onDestroy(() => {
		stopReplay?.();
		audioCheckAbort?.abort();
		void agentAudio.close();
	});
</script>

<svelte:head>
	<title>Vachan Operator Console</title>
</svelte:head>

<main class="operator-shell">
	<header class="topbar">
		<div class="brand-lockup">
			<p class="eyebrow">COLLECTIONS VOICE AGENT</p>
			<h1>Vachan <span lang="hi">वचन</span></h1>
		</div>
		<p class="demo-badge">DEMO / MOCK DATA</p>
	</header>

	<section class="workspace" aria-labelledby="setup-heading">
		<div class="intro-panel">
			<p class="section-label">OPERATOR SETUP</p>
			<h2 id="setup-heading">Prepare the supervised call.</h2>
			<p class="lede">
				Private account context remains locked until deterministic verification confirms who is
				speaking. Complete the local audio check before opening a mock case.
			</p>

			<div class="trust-rule">
				<span class="rule-marker" aria-hidden="true"></span>
				<div>
					<p class="mono-label">DISCLOSURE POLICY</p>
					<p>Code controls identity, private context, and writes. The language model handles language.</p>
				</div>
			</div>
		</div>

		<aside class="preflight-panel" aria-labelledby="audio-heading">
			<div class="panel-heading">
				<div>
					<p class="section-label">PREFLIGHT 01</p>
					<h2 id="audio-heading">Browser audio</h2>
				</div>
				<span class:ready={microphoneState === 'ready'} class:blocked={microphoneState === 'blocked'}>
					{stateLabels[microphoneState]}
				</span>
			</div>

			<div class="check-row">
				<div>
					<p class="check-name">Microphone permission</p>
					<p class="check-detail" role="status" aria-live="polite">{microphoneDetail}</p>
				</div>
				<span class="state-dot" aria-hidden="true"></span>
			</div>

			<div class="check-row">
				<div>
					<p class="check-name">Bulbul headphone output</p>
					<p class="check-detail" role="status" aria-live="polite">{audioOutputDetail}</p>
				</div>
				<span
					class:ready={audioOutputState === 'ready'}
					class:blocked={audioOutputState === 'blocked'}
				>
					{audioOutputLabels[audioOutputState]}
				</span>
			</div>

			<p class="hardware-note">
				Use wired headphones. Open speakers can feed agent speech back into the microphone.
				Unplugged headphones are a documented known-bad configuration, not a supported demo mode.
			</p>

			<div class="replay-controls">
				<button
					type="button"
					onclick={requestMicrophone}
					disabled={microphoneState === 'requesting'}
				>
					{microphoneState === 'requesting' ? 'Checking microphone' : 'Request mic'}
				</button>
				<button
					type="button"
					onclick={playAudioCheck}
					disabled={audioOutputState === 'requesting' || audioOutputState === 'playing'}
				>
					Play Bulbul check
				</button>
				{#if audioOutputState === 'confirming'}
					<button type="button" onclick={confirmAudioCheck}>I hear Bulbul</button>
				{/if}
				{#if audioOutputState === 'requesting' || audioOutputState === 'playing'}
					<button type="button" onclick={stopAgentAudio}>Stop audio</button>
				{/if}
			</div>
		</aside>
	</section>

	{#if import.meta.env.DEV}
		<section class="replay-harness" aria-labelledby="replay-heading">
			<div class="replay-toolbar">
				<div>
					<p class="section-label">DEVELOPMENT FALLBACK</p>
					<h2 id="replay-heading">Protocol replay harness</h2>
					<p class="check-detail" role="status" aria-live="polite">{replayDetail}</p>
				</div>

				<div class="replay-controls">
					<label>
						<span>FIXTURE</span>
						<select bind:value={replayFixture} disabled={replayState === 'connecting' || replayState === 'playing'}>
							<option value="happy">Happy path</option>
							<option value="third_party">Third party</option>
							<option value="takeover">Takeover</option>
						</select>
					</label>
					<button
						type="button"
						onclick={startDevReplay}
						disabled={replayState === 'connecting' || replayState === 'playing'}
					>
						Run recorded replay
					</button>
				</div>
			</div>

			<div class="replay-status-line">
				<strong>{replayLabel || 'REPLAY — recorded sequence'}</strong>
				<span>{replayStateLabels[replayState]}</span>
			</div>

			<div class="replay-columns">
				<article>
					<p class="section-label">CALL</p>
					<h3>Recorded utterance</h3>
					<p>{payloadString(latestUtterance, 'text') || 'Waiting for a ledger event.'}</p>
				</article>

				<article>
					<p class="section-label">WATCH</p>
					<h3>Ledger-derived state</h3>
					<dl>
						<div><dt>IDENTITY</dt><dd>{identityState || '—'}</dd></div>
						<div><dt>PROMISE</dt><dd>{promiseState || '—'}</dd></div>
						<div>
							<dt>LATEST TOOL</dt>
							<dd>{payloadString(latestToolDecision, 'tool') || '—'}</dd>
						</div>
					</dl>
				</article>

				<article class="evidence-card">
					<p class="section-label">EVIDENCE</p>
					<h3>{disposition || `${replayEvents.length} ordered events`}</h3>
					<ol>
						{#each replayEvents as event (event.seq)}
							<li class:blocked-event={event.type === 'guard_block' || (event.type === 'tool_decision' && event.payload.allowed === false)}>
								<code>{String(event.seq).padStart(2, '0')}</code>
								<span>{event.type}</span>
								<small>{payloadString(event, 'reason') || payloadString(event, 'after') || payloadString(event, 'disposition') || ''}</small>
							</li>
						{/each}
					</ol>
				</article>
			</div>
		</section>
	{/if}

	<footer>
		<p>LOCAL STAGE ORIGIN</p>
		<code>http://localhost:3000</code>
	</footer>
</main>
