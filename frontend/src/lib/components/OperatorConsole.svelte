<script lang="ts">
	import {
		buildOperatorView,
		operatorActionState,
		type OperatorConnectionState
	} from '$lib/operator';
	import type { ServerEvent } from '$lib/protocol';

	interface Props {
		events: readonly ServerEvent[];
		connectionState?: OperatorConnectionState;
		streamLabel?: string;
		onEnd?: () => void;
		onTakeover?: () => void;
		takeoverActive?: boolean;
		endReason?: string;
	}

	let {
		events,
		connectionState = 'idle',
		streamLabel = 'LEDGER EVENT STREAM',
		onEnd,
		onTakeover,
		takeoverActive = false,
		endReason = $bindable('')
	}: Props = $props();

	let view = $derived(buildOperatorView(events, connectionState));
	let actionState = $derived(
		operatorActionState({
			complete: view.complete,
			hasEnd: Boolean(onEnd),
			hasTakeover: Boolean(onTakeover),
			takeoverActive,
			endReason
		})
	);
</script>

<section class="operator-console" aria-labelledby="operator-console-heading">
	<header class="console-header">
		<div>
			<p class="section-label">SUPERVISED CALL</p>
			<h2 id="operator-console-heading">Operator console</h2>
		</div>
		<div class="stream-status" class:degraded={connectionState === 'degraded'}>
			<span aria-hidden="true"></span>
			<div>
				<strong>{streamLabel}</strong>
				<small>{view.complete ? 'COMPLETE' : connectionState.toUpperCase()}</small>
			</div>
		</div>
	</header>

	{#if view.alert}
		<div class="operator-alert" role="alert">
			<strong>{view.alert.title}</strong>
			<span>{view.alert.detail}</span>
		</div>
	{/if}
	{#if takeoverActive}
		<div class="takeover-banner" role="alert">
			<strong>OPERATOR TAKEOVER — AGENT SILENCED</strong>
			<span>Agent output cannot resume. Speak directly, then record why you ended the call.</span>
		</div>
	{/if}

	<div class="operator-columns">
		<article class="console-card call-card">
			<div class="card-heading">
				<p class="section-label">CALL</p>
				<span>{view.callState}</span>
			</div>
			<p class="speaker-label">{view.latestSpeaker.toUpperCase()} · SAFE OUTPUT</p>
			<blockquote>{view.latestUtterance}</blockquote>
			{#if takeoverActive}
				<label class="end-reason">
					<span>REQUIRED END REASON</span>
					<input
						bind:value={endReason}
						maxlength="500"
						placeholder="Why the operator ended this call"
						autocomplete="off"
					/>
				</label>
			{/if}
			<div class="call-actions" aria-label="Operator call actions">
				<button
					type="button"
					class="secondary-action"
					onclick={onEnd}
					disabled={actionState.endDisabled}
				>
					End call
				</button>
				<button
					type="button"
					class="takeover-action"
					onclick={onTakeover}
					disabled={actionState.takeoverDisabled}
				>
					Break-glass takeover
				</button>
			</div>
		</article>

		<article class="console-card watch-card">
			<div class="card-heading">
				<p class="section-label">WATCH</p>
				<span>{view.dialogueStep}</span>
			</div>

			<div
				class="identity-ribbon"
				aria-label="Identity state journey"
				aria-live="polite"
				aria-atomic="true"
			>
				{#if view.identityJourney.length === 0}
					<strong class="unknown">NO IDENTITY EVIDENCE</strong>
				{:else}
					{#each view.identityJourney as state, index (index)}
						{#if index > 0}<span class="journey-arrow" aria-hidden="true">→</span>{/if}
						<strong
							class:confirmed={state === 'CONFIRMED'}
							class:demoted={state === 'THIRD_PARTY'}
						>
							{state}
						</strong>
					{/each}
				{/if}
			</div>

			<dl>
				<div>
					<dt>IDENTITY</dt>
					<dd class:demoted={view.identityState === 'THIRD_PARTY'}>{view.identityState}</dd>
				</div>
				<div>
					<dt>PROMISE</dt>
					<dd class:promise={view.promiseState === 'COMMITTED'}>{view.promiseState}</dd>
				</div>
				<div><dt>DIALOGUE</dt><dd>{view.dialogueStep}</dd></div>
				<div>
					<dt>LATEST TOOL</dt>
					<dd class:denied={view.latestToolDecision && !view.latestToolDecision.allowed}>
						{view.latestToolDecision
							? `${view.latestToolDecision.tool} · ${view.latestToolDecision.allowed ? 'ALLOWED' : 'DENIED'}`
							: '—'}
					</dd>
				</div>
			</dl>
		</article>

		<article class="console-card evidence-card">
			<div class="card-heading">
				<p class="section-label">EVIDENCE</p>
				<span>{view.evidence.length} EVENTS</span>
			</div>

			{#if view.disposition}
				<div
					class="outcome-panel"
					class:promise={view.disposition === 'PROMISE_CONFIRMED'}
					role="alert"
					aria-live="assertive"
					aria-atomic="true"
				>
					<span>FINAL DISPOSITION</span>
					<strong>{view.disposition}</strong>
				</div>
			{/if}

			<ol aria-live="polite">
				{#each view.evidence as row (row.seq)}
					<li
						class:blocked={row.tone === 'blocked'}
						class:held={row.tone === 'held'}
						class:promise={row.tone === 'promise' && row.detail.includes('COMMITTED')}
					>
						<code>{String(row.seq).padStart(2, '0')}</code>
						<div>
							<strong>{row.label}</strong>
							<small>{row.detail}</small>
						</div>
					</li>
				{/each}
			</ol>
		</article>
	</div>
</section>

<style>
	.operator-console {
		margin-bottom: 3rem;
		border: 1px solid var(--color-seam);
		border-radius: 1rem;
		padding: 1.25rem;
		background: var(--color-panel);
		box-shadow: 0 1.5rem 4rem rgba(0, 0, 0, 0.16);
	}

	.console-header,
	.card-heading,
	.stream-status,
	.call-actions,
	.watch-card dl > div {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
	}

	.console-header {
		padding-bottom: 1.25rem;
	}

	.console-header h2 {
		margin-top: 0.4rem;
		font-size: 1.5rem;
		font-weight: 550;
		letter-spacing: -0.025em;
	}

	.stream-status {
		justify-content: flex-start;
		font-family: var(--font-mono);
		font-size: 0.68rem;
		letter-spacing: 0.07em;
	}

	.stream-status > span {
		width: 0.55rem;
		height: 0.55rem;
		border-radius: 50%;
		background: var(--color-held);
	}

	.stream-status.degraded > span {
		background: var(--color-demoted);
	}

	.stream-status div {
		display: grid;
		gap: 0.25rem;
	}

	.stream-status small {
		color: var(--color-muted);
	}

	.operator-alert {
		display: grid;
		gap: 0.35rem;
		margin-bottom: 1rem;
		border-left: 3px solid var(--color-demoted);
		padding: 0.75rem 1rem;
		background: color-mix(in srgb, var(--color-demoted), transparent 88%);
	}

	.takeover-banner {
		display: grid;
		gap: 0.35rem;
		margin-bottom: 1rem;
		border: 1px solid var(--color-demoted);
		border-left-width: 4px;
		padding: 0.85rem 1rem;
		background: color-mix(in srgb, var(--color-demoted), transparent 82%);
	}

	.takeover-banner strong,
	.takeover-banner span,
	.end-reason span {
		font-family: var(--font-mono);
	}

	.takeover-banner strong {
		font-size: 0.78rem;
	}

	.takeover-banner span {
		color: var(--color-muted);
		font-size: 0.72rem;
	}

	.end-reason {
		display: grid;
		gap: 0.4rem;
		margin-bottom: 1rem;
	}

	.end-reason span {
		color: var(--color-muted);
		font-size: 0.65rem;
		letter-spacing: 0.07em;
	}

	.end-reason input {
		width: 100%;
		box-sizing: border-box;
		border: 1px solid var(--color-seam);
		border-radius: 0.4rem;
		padding: 0.65rem;
		background: var(--color-panel);
		color: var(--color-text);
	}

	.operator-alert strong,
	.operator-alert span {
		font-family: var(--font-mono);
		font-size: 0.72rem;
	}

	.operator-alert span {
		color: var(--color-muted);
	}

	.operator-columns {
		display: grid;
		grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr) minmax(0, 1.25fr);
		gap: 0.75rem;
	}

	.console-card {
		min-width: 0;
		min-height: 19rem;
		border: 1px solid var(--color-seam);
		border-radius: 0.75rem;
		padding: 1rem;
		background: var(--color-bg);
	}

	.card-heading {
		border-bottom: 1px solid var(--color-seam);
		padding-bottom: 0.75rem;
	}

	.card-heading > span {
		color: var(--color-muted);
		font-family: var(--font-mono);
		font-size: 0.67rem;
		letter-spacing: 0.05em;
		text-align: right;
	}

	.speaker-label {
		margin-top: 1.5rem;
		color: var(--color-muted);
		font-family: var(--font-mono);
		font-size: 0.68rem;
		letter-spacing: 0.08em;
	}

	blockquote {
		min-height: 7.5rem;
		margin: 0.75rem 0 1.25rem;
		border-left: 3px solid var(--color-held);
		padding-left: 1rem;
		color: var(--color-text);
		font-size: 1.05rem;
		line-height: 1.65;
	}

	.call-actions {
		align-items: stretch;
	}

	.call-actions button {
		flex: 1;
	}

	.secondary-action {
		border-color: var(--color-seam);
		background: transparent;
		color: var(--color-text);
	}

	.takeover-action {
		border-color: var(--color-demoted);
		background: color-mix(in srgb, var(--color-demoted), transparent 78%);
		color: var(--color-text);
	}

	.identity-ribbon {
		min-height: 4.25rem;
		display: flex;
		align-items: center;
		gap: 0.45rem;
		overflow-x: auto;
		border-bottom: 1px solid var(--color-seam);
		font-family: var(--font-mono);
		font-size: 1.25rem;
		white-space: nowrap;
	}

	.identity-ribbon strong {
		color: var(--color-muted);
	}

	.identity-ribbon strong.confirmed {
		color: var(--color-held);
	}

	.identity-ribbon strong.unknown {
		color: var(--color-muted);
		font-size: 0.85em;
	}

	.identity-ribbon strong.demoted,
	.watch-card dd.demoted {
		color: var(--color-demoted);
	}

	.journey-arrow {
		color: var(--color-muted);
	}

	.watch-card .card-heading > span {
		font-size: 1.25rem;
	}

	.watch-card dl {
		margin: 0;
	}

	.watch-card dl > div {
		align-items: start;
		border-bottom: 1px solid var(--color-seam);
		padding: 0.8rem 0;
	}

	.watch-card dt,
	.watch-card dd {
		font-family: var(--font-mono);
		font-size: 0.7rem;
	}

	.watch-card dt {
		color: var(--color-muted);
	}

	.watch-card dd {
		margin: 0;
		font-size: 1.25rem;
		text-align: right;
	}

	.watch-card dd.denied {
		color: var(--color-demoted);
	}

	.watch-card dd.promise {
		color: var(--color-accent);
	}

	.outcome-panel {
		display: grid;
		gap: 0.35rem;
		margin-top: 0.9rem;
		border-left: 3px solid var(--color-held);
		padding: 0.75rem;
		background: color-mix(in srgb, var(--color-held), transparent 90%);
	}

	.outcome-panel span,
	.outcome-panel strong {
		font-family: var(--font-mono);
	}

	.outcome-panel span {
		color: var(--color-muted);
		font-size: 0.65rem;
		letter-spacing: 0.08em;
	}

	.outcome-panel strong {
		font-size: 1.75rem;
	}

	.outcome-panel.promise {
		border-left-color: var(--color-accent);
		background: color-mix(in srgb, var(--color-accent), transparent 90%);
	}

	.evidence-card ol {
		max-height: 18rem;
		margin: 0.75rem 0 0;
		padding: 0;
		overflow: auto;
		list-style: none;
	}

	.evidence-card li {
		display: grid;
		grid-template-columns: 2rem minmax(0, 1fr);
		gap: 0.55rem;
		border-left: 3px solid transparent;
		border-top: 1px solid var(--color-seam);
		padding: 0.65rem 0.25rem;
	}

	.evidence-card li.blocked {
		border-left-color: var(--color-demoted);
		padding-left: 0.55rem;
	}

	.evidence-card li.held {
		border-left-color: var(--color-held);
		padding-left: 0.55rem;
	}

	.evidence-card li.promise {
		border-left-color: var(--color-accent);
		padding-left: 0.55rem;
	}

	.evidence-card code,
	.evidence-card strong,
	.evidence-card small {
		font-family: var(--font-mono);
		font-size: 0.68rem;
	}

	.evidence-card code {
		color: var(--color-text);
	}

	.evidence-card li div {
		min-width: 0;
		display: grid;
		gap: 0.3rem;
	}

	.evidence-card small {
		overflow-wrap: anywhere;
		color: var(--color-muted);
		line-height: 1.4;
	}

	@media (max-width: 62rem) {
		.operator-columns {
			grid-template-columns: 1fr 1fr;
		}

		.evidence-card {
			grid-column: 1 / -1;
		}
	}

	@media (max-width: 44rem) {
		.console-header,
		.call-actions {
			align-items: stretch;
			flex-direction: column;
		}

		.operator-columns {
			grid-template-columns: 1fr;
		}

		.watch-card {
			order: 1;
		}

		.evidence-card {
			grid-column: auto;
			order: 2;
		}

		.call-card {
			order: 3;
		}

		.identity-ribbon {
			flex-wrap: wrap;
			overflow-x: visible;
			white-space: normal;
		}
	}
</style>
