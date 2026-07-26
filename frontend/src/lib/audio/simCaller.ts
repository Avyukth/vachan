/**
 * Simulated-caller mode: an INPUT SUBSTITUTION, not a dialogue player.
 *
 * A prerecorded borrower-side WAV is pushed over the SAME `/ws/call/{id}` socket in
 * the SAME PCM16/16 kHz frames the live microphone uses, so Saaras STT, the dialogue
 * controller, verification, the guard, the promise machine and the evidence ledger
 * all run unmodified and cannot tell the difference. That indistinguishability is the
 * point: a fallback that exercises a different code path proves nothing about the
 * thing being demonstrated.
 *
 * TWO RULES ENFORCED HERE RATHER THAN BY DISCIPLINE:
 *
 * 1. ONE SESSION PER CALL. The backend `SttSessionRegistry` cancels the prior session
 *    for a call id, so two open sockets fight silently — audio flows and turns
 *    execute, but transcripts never reach the binding that advances identity. (This
 *    was observed live: six turns ran and identity stayed UNVERIFIED.) The caller
 *    MUST stop live capture before `startSimulatedCaller`, and this module opens
 *    exactly one socket.
 *
 * 2. AGENT CLIPS ARE NOT ELIGIBLE. Playing an `*_agent_*` clip would fake Vachan's
 *    OWN voice, which is a worse honesty violation than substituting the caller.
 *    `assertCallerFixture` rejects them by construction.
 */

const CALL_WEBSOCKET_PATH = '/ws/call';
const TARGET_SAMPLE_RATE = 16_000;
/** 100 ms at 16 kHz => 3200 bytes/frame: same cadence as the mic worklet, far under the 64 KiB cap. */
const CHUNK_SAMPLES = 1_600;
/** Real-time pacing keeps STT segmentation behaving as it does with a live speaker. */
const FRAME_INTERVAL_MS = 100;

export interface SimulatedCallerFixture {
	readonly id: string;
	readonly label: string;
	/** happy | non-happy | blocker — shown to the operator so the choice is deliberate. */
	readonly pathKind: string;
	readonly url: string;
}

export interface SimulatedCallerSession {
	readonly callId: string;
	readonly fixtureId: string;
	/** Resolves when every frame has been sent and the utterance flushed. */
	readonly done: Promise<void>;
	cancel(): Promise<void>;
}

export interface SimulatedCallerCallbacks {
	onServerEvent(message: unknown): void;
	onFirstFrame(): void;
	onLocalError(message: string): void;
}

export type SimulatedCallerSocketDecode =
	| { readonly serverEvent: unknown; readonly localError?: never }
	| { readonly serverEvent?: never; readonly localError: string };

export function decodeSimulatedCallerSocketMessage(data: string): SimulatedCallerSocketDecode {
	try {
		return { serverEvent: JSON.parse(data) };
	} catch {
		return {
			localError: 'The simulated-caller socket returned an unparseable server frame.'
		};
	}
}

/**
 * Borrower- and spouse-side fixtures only. Served by the backend fixture route (or a
 * local CORS server during testing); every one is STT round-trip verified, so a
 * fixture cannot silently claim content it does not carry.
 */
export const CALLER_FIXTURES: readonly SimulatedCallerFixture[] = [
	{
		id: 'happy_1_borrower_claim',
		label: '1/3 · Borrower says “मैं राकेश बोल रहा हूँ”',
		pathKind: 'HAPPY',
		url: '/fixtures/audio_e2e_happy_1_borrower_claim.wav'
	},
	{
		id: 'happy_2_verification_values',
		label: '2/3 · Borrower gives the two verification values',
		pathKind: 'HAPPY',
		url: '/fixtures/audio_e2e_happy_2_verification_values.wav'
	},
	{
		id: 'happy_3_promise_offer',
		label: '3/3 · Borrower promises ₹1,500 by Friday',
		pathKind: 'HAPPY',
		url: '/fixtures/audio_e2e_happy_3_promise_offer.wav'
	},
	{
		id: 'nonhappy_refuses_verification',
		label: 'Borrower refuses to verify',
		pathKind: 'NON-HAPPY',
		url: '/fixtures/audio_e2e_nonhappy_refuses_verification.wav'
	},
	{
		id: 'blocker_verification_failed',
		label: 'Wrong verification values',
		pathKind: 'BLOCKER',
		url: '/fixtures/audio_e2e_blocker_verification_failed.wav'
	},
	{
		id: 'blocker_handover_midcall',
		label: 'Borrower hands the phone over mid-call',
		pathKind: 'BLOCKER',
		url: '/fixtures/audio_e2e_blocker_handover_midcall.wav'
	},
	{
		id: 'blocker_spouse_demands_balance',
		label: 'Spouse demands the outstanding amount',
		pathKind: 'BLOCKER',
		url: '/fixtures/audio_e2e_blocker_spouse_demands_balance.wav'
	}
] as const;

/** Rejects any fixture that would put words in the agent's mouth. */
export function assertCallerFixture(url: string): void {
	if (/_agent_|\/agent[-_]/i.test(url)) {
		throw new Error(
			'Refusing to inject an agent clip: simulated-caller mode may only substitute the caller, never Vachan itself.'
		);
	}
}

/** Pure, so it is unit-testable without a browser audio stack. */
export function floatToPcm16(mono: Float32Array): Int16Array {
	const pcm = new Int16Array(mono.length);
	for (let index = 0; index < mono.length; index += 1) {
		const sample = Math.max(-1, Math.min(1, mono[index]));
		pcm[index] = sample < 0 ? Math.round(sample * 0x8000) : Math.round(sample * 0x7fff);
	}
	return pcm;
}

function websocketUrl(path: string): string {
	const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	return `${scheme}//${window.location.host}${path}`;
}

/**
 * Fetch a fixture and return caller audio as PCM16 at exactly 16 kHz.
 *
 * Bulbul emits 24 kHz WAV; `decodeAudioData` may hand back the device rate (44.1 kHz
 * was observed), so the OfflineAudioContext render is what guarantees 16 kHz. One
 * output channel also downmixes any stereo fixture for free.
 */
export async function loadFixturePcm16(url: string): Promise<Int16Array> {
	assertCallerFixture(url);

	const response = await fetch(url);
	if (!response.ok) {
		throw new Error(`Simulated-caller fixture is unavailable (HTTP ${response.status}).`);
	}
	const encoded = await response.arrayBuffer();

	const decodeContext = new AudioContext();
	let decoded: AudioBuffer;
	try {
		decoded = await decodeContext.decodeAudioData(encoded);
	} finally {
		await decodeContext.close();
	}

	const frames = Math.ceil(decoded.duration * TARGET_SAMPLE_RATE);
	const offline = new OfflineAudioContext(1, frames, TARGET_SAMPLE_RATE);
	const source = offline.createBufferSource();
	source.buffer = decoded;
	source.connect(offline.destination);
	source.start();

	const rendered = await offline.startRendering();
	if (rendered.sampleRate !== TARGET_SAMPLE_RATE) {
		throw new Error('Browser refused a 16 kHz offline render; simulated caller is unavailable.');
	}
	return floatToPcm16(rendered.getChannelData(0));
}

/**
 * Open the ONE call socket and stream the fixture as caller audio.
 *
 * The caller must already have stopped live microphone capture — see rule 1 above.
 */
export async function startSimulatedCaller(
	callId: string,
	fixtureUrl: string,
	callbacks: SimulatedCallerCallbacks
): Promise<SimulatedCallerSession> {
	const pcm = await loadFixturePcm16(fixtureUrl);

	const socket = new WebSocket(
		websocketUrl(`${CALL_WEBSOCKET_PATH}/${encodeURIComponent(callId)}`)
	);
	socket.binaryType = 'arraybuffer';

	await new Promise<void>((resolve, reject) => {
		socket.addEventListener('open', () => resolve(), { once: true });
		socket.addEventListener(
			'error',
			() => reject(new Error('Simulated-caller WebSocket could not connect.')),
			{ once: true }
		);
	});

	socket.addEventListener('message', (event) => {
		const decoded = decodeSimulatedCallerSocketMessage(String(event.data));
		if (decoded.localError) callbacks.onLocalError(decoded.localError);
		else callbacks.onServerEvent(decoded.serverEvent);
	});

	let cancelled = false;

	const done = (async () => {
		try {
			for (let offset = 0; offset < pcm.length; offset += CHUNK_SAMPLES) {
				if (cancelled || socket.readyState !== WebSocket.OPEN) return;
				const slice = pcm.subarray(offset, Math.min(offset + CHUNK_SAMPLES, pcm.length));
				// Copy into a fresh ArrayBuffer: the view's underlying buffer may be typed
				// SharedArrayBuffer, which WebSocket.send does not accept.
				const frame = new Uint8Array(slice.byteLength);
				frame.set(new Uint8Array(pcm.buffer, slice.byteOffset, slice.byteLength));
				if (offset === 0) callbacks.onFirstFrame();
				socket.send(frame.buffer);
				await new Promise((resolve) => setTimeout(resolve, FRAME_INTERVAL_MS));
			}
			if (!cancelled && socket.readyState === WebSocket.OPEN) {
				socket.send(JSON.stringify({ type: 'flush' }));
			}
		} catch (error: unknown) {
			callbacks.onLocalError(
				error instanceof Error ? error.message : 'The simulated caller failed locally.'
			);
		}
	})();

	return {
		callId,
		fixtureId: fixtureUrl,
		done,
		async cancel(): Promise<void> {
			cancelled = true;
			await done.catch(() => undefined);
			if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
				socket.close();
			}
		}
	};
}
