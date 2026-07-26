<script lang="ts">
	import { onDestroy } from 'svelte';

	import {
		CALLER_FIXTURES,
		startSimulatedCaller,
		type SimulatedCallerSession
	} from '$lib/audio/simCaller';
	import {
		INITIAL_SIMULATED_CALLER_DISCLOSURE,
		advanceSimulatedCallerDisclosure,
		clearSimulatedCallerDisclosure,
		persistSimulatedCallerDisclosure,
		restoreSimulatedCallerDisclosure,
		type SimulatedCallerDisclosure
	} from '$lib/audio/simCallerDisclosure';
	import { SIM_CALLER_LABEL } from '$lib/audio/simCallerGate';

	const ACTIVE_CALL_STORAGE_KEY = 'vachan.activeCallId';

	type SimulatedCallerUiState = 'idle' | 'confirming' | 'injecting' | 'complete' | 'error';

	interface Props {
		activeCallId: string;
		stopLiveCapture(): Promise<void>;
		onVoiceMessage(message: unknown): void;
	}

	let { activeCallId, stopLiveCapture, onVoiceMessage }: Props = $props();
	let uiState: SimulatedCallerUiState = $state('idle');
	let fixtureId = $state(CALLER_FIXTURES[0]?.id ?? '');
	let detail = $state('');
	let disclosure: SimulatedCallerDisclosure = $state(INITIAL_SIMULATED_CALLER_DISCLOSURE);
	let session: SimulatedCallerSession | undefined;
	let lifecycleCallId = '';

	$effect(() => {
		// During a same-call reload the page deliberately restores the call in
		// evidence-only mode, so the active prop is blank while this durable marker
		// still identifies the call whose disclosure must remain visible.
		const nextCallId =
			activeCallId || sessionStorage.getItem(ACTIVE_CALL_STORAGE_KEY)?.trim() || '';
		if (nextCallId === lifecycleCallId) return;
		if (lifecycleCallId) {
			// The page removes its active-call marker only at a durable terminal/reset
			// boundary. A direct non-empty change is a genuinely different call.
			clearSimulatedCallerDisclosure(sessionStorage, lifecycleCallId);
		}
		lifecycleCallId = nextCallId;
		disclosure = nextCallId
			? restoreSimulatedCallerDisclosure(sessionStorage, nextCallId)
			: INITIAL_SIMULATED_CALLER_DISCLOSURE;
		uiState = 'idle';
		detail = '';
		void cancelSession();
	});

	function advanceDisclosure(event: Parameters<typeof advanceSimulatedCallerDisclosure>[1]): void {
		disclosure = advanceSimulatedCallerDisclosure(disclosure, event);
		persistSimulatedCallerDisclosure(sessionStorage, lifecycleCallId, disclosure);
	}

	async function cancelSession(): Promise<void> {
		const activeSession = session;
		session = undefined;
		if (activeSession) await activeSession.cancel();
	}

	async function stop(event: 'stopped' | 'takeover_requested' | 'end_requested'): Promise<void> {
		advanceDisclosure(event);
		await cancelSession();
		uiState = 'complete';
		detail = 'Prerecorded input stopped. Disclosure remains visible until terminal disposition.';
	}

	export async function stopForControl(
		reason: 'takeover_requested' | 'end_requested'
	): Promise<void> {
		await stop(reason);
	}

	async function arm(): Promise<void> {
		uiState = 'idle';
		const fixture = CALLER_FIXTURES.find((entry) => entry.id === fixtureId);
		if (!fixture) {
			uiState = 'error';
			detail = 'Select a caller fixture first.';
			return;
		}
		if (!activeCallId) {
			uiState = 'error';
			detail = 'Start a mock call before arming prerecorded caller input.';
			return;
		}

		try {
			await stopLiveCapture();
			uiState = 'injecting';
			detail = `Injecting ${fixture.label}`;
			let failedLocally = false;
			session = await startSimulatedCaller(activeCallId, fixture.url, {
				onServerEvent: onVoiceMessage,
				onFirstFrame: () => {
					advanceDisclosure('first_frame');
				},
				onLocalError: (message) => {
					failedLocally = true;
					advanceDisclosure('failed');
					uiState = 'error';
					detail = `Local prerecorded-input error: ${message}`;
				}
			});
			await session.done;
			if (!failedLocally) {
				advanceDisclosure('completed');
				uiState = 'complete';
				detail =
					'Prerecorded input finished and flushed. Disclosure remains until terminal disposition.';
			}
		} catch (error: unknown) {
			advanceDisclosure('failed');
			uiState = 'error';
			detail =
				error instanceof Error ? error.message : 'Prerecorded caller input could not start.';
		}
	}

	onDestroy(() => {
		void cancelSession();
	});
</script>

<svelte:head>
	<title>{disclosure.latched
			? '[SIMULATED CALLER] Vachan Operator Console'
			: 'Vachan Operator Console'}</title>
</svelte:head>

{#if disclosure.latched}
	<p class="banner" role="status" aria-live="assertive">
		<strong>{SIM_CALLER_LABEL}</strong>
		<span>Live microphone released. This caller audio is not a live speaker.</span>
	</p>
{/if}

<section class="control" aria-labelledby="simulated-input-heading">
	<h2 id="simulated-input-heading">Prerecorded caller input — break-glass fallback</h2>
	<p>
		Live microphone is the demo. Use this only if venue audio fails. Caller-side audio only;
		agent clips are refused.
	</p>
	<label>
		<span>Caller fixture</span>
		<select bind:value={fixtureId} disabled={uiState === 'injecting'}>
			{#each CALLER_FIXTURES as fixture (fixture.id)}
				<option value={fixture.id}>{fixture.pathKind} · {fixture.label}</option>
			{/each}
		</select>
	</label>

	{#if uiState === 'confirming'}
		<div class="confirmation">
			<strong>{SIM_CALLER_LABEL}</strong>
			<p>
				Prerecorded audio will be sent as the caller and the live microphone will be
				released. Anyone watching must be told.
			</p>
			<div class="actions">
				<button type="button" class="secondary-button" onclick={() => (uiState = 'idle')}>
					Cancel
				</button>
				<button type="button" onclick={arm}>Confirm arm</button>
			</div>
		</div>
	{:else}
		<div class="actions">
			<button
				type="button"
				class="secondary-button"
				disabled={!activeCallId || uiState === 'injecting'}
				onclick={() => (uiState = 'confirming')}
			>
				{uiState === 'injecting' ? 'Prerecorded caller active' : 'Arm prerecorded caller'}
			</button>
			{#if uiState === 'injecting'}
				<button type="button" class="secondary-button" onclick={() => stop('stopped')}>
					Stop prerecorded caller
				</button>
			{/if}
		</div>
	{/if}

	{#if detail}
		<p class:error={uiState === 'error'} class="detail" role="status" aria-live="polite">
			{detail}
		</p>
	{/if}
</section>

<style>
	.banner {
		position: sticky;
		top: 0;
		z-index: 5;
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem 1rem;
		align-items: baseline;
		border: 1px solid var(--color-demoted);
		border-left: 4px solid var(--color-demoted);
		background: color-mix(in srgb, var(--color-demoted) 14%, var(--color-panel));
		padding: 0.75rem 1.25rem;
	}

	.banner strong,
	.control label > span,
	.confirmation strong {
		font-family: var(--font-mono);
		letter-spacing: 0.08em;
		color: var(--color-demoted);
	}

	.control {
		display: grid;
		gap: 0.9rem;
		border: 1px solid var(--color-seam);
		border-left: 4px solid var(--color-demoted);
		background: var(--color-panel);
		padding: 1.25rem 1.5rem;
		margin-top: 1rem;
	}

	.control > p,
	.confirmation p,
	.detail {
		margin: 0;
		color: var(--color-muted);
		font-size: 0.95rem;
		line-height: 1.5;
	}

	.control label,
	.confirmation {
		display: grid;
		gap: 0.6rem;
	}

	.confirmation {
		border: 1px solid var(--color-demoted);
		padding: 1rem 1.25rem;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.6rem;
	}

	.detail {
		font-family: var(--font-mono);
		color: var(--color-text);
	}

	.detail.error {
		color: var(--color-demoted);
	}

	@media (max-width: 48rem) {
		.actions {
			flex-direction: column;
			align-items: stretch;
		}
	}
</style>
