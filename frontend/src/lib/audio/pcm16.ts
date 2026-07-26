const SPIKE_WEBSOCKET_PATH = '/ws/spike/stt';
const WORKLET_PATH = '/audio/pcm16-worklet.js';

export interface PcmCaptureSession {
	readonly sourceSampleRate: number;
	finishInput(): Promise<void>;
	close(): Promise<void>;
}

interface CaptureResources {
	context: AudioContext;
	stream: MediaStream;
	source: MediaStreamAudioSourceNode;
	worklet: AudioWorkletNode;
	silentGain: GainNode;
	socket: WebSocket;
}

export type PcmCaptureEventHandler = (message: unknown) => void;
export type AudioSpikeEventHandler = PcmCaptureEventHandler;

function websocketUrl(path: string): string {
	const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	return `${scheme}//${window.location.host}${path}`;
}

function waitForOpen(socket: WebSocket): Promise<void> {
	return new Promise((resolve, reject) => {
		socket.addEventListener('open', () => resolve(), { once: true });
		socket.addEventListener(
			'error',
			() => reject(new Error('Audio spike WebSocket could not connect')),
			{ once: true }
		);
	});
}

async function releaseCapture(resources: CaptureResources): Promise<void> {
	for (const track of resources.stream.getTracks()) track.stop();
	resources.source.disconnect();
	resources.worklet.disconnect();
	resources.silentGain.disconnect();
	await resources.context.close();
}

export async function startPcm16Capture(
	onEvent: PcmCaptureEventHandler,
	websocketPath = SPIKE_WEBSOCKET_PATH
): Promise<PcmCaptureSession> {
	if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
		throw new Error('This browser does not support AudioWorklet microphone capture');
	}

	const context = new AudioContext();
	await context.resume();
	let stream: MediaStream | undefined;

	try {
		stream = await navigator.mediaDevices.getUserMedia({
			audio: {
				channelCount: 1,
				echoCancellation: true,
				noiseSuppression: true,
				autoGainControl: true
			}
		});
		await context.audioWorklet.addModule(WORKLET_PATH);
		const source = context.createMediaStreamSource(stream);
		const worklet = new AudioWorkletNode(context, 'pcm16-capture', {
			numberOfInputs: 1,
			numberOfOutputs: 1,
			outputChannelCount: [1]
		});
		const silentGain = context.createGain();
		silentGain.gain.value = 0;
		source.connect(worklet).connect(silentGain).connect(context.destination);

		const socket = new WebSocket(websocketUrl(websocketPath));
		socket.binaryType = 'arraybuffer';
		socket.addEventListener('message', (event) => {
			try {
				onEvent(JSON.parse(String(event.data)));
			} catch {
				onEvent({ type: 'error', detail: 'Backend sent malformed JSON' });
			}
		});
		await waitForOpen(socket);

		const resources = { context, stream, source, worklet, silentGain, socket };
		let inputFinished = false;
		let markWorkletStopped: (() => void) | undefined;
		const workletStopped = new Promise<void>((resolve) => {
			markWorkletStopped = resolve;
		});
		worklet.port.onmessage = (event: MessageEvent<ArrayBuffer | { type?: string }>) => {
			if (event.data instanceof ArrayBuffer && socket.readyState === WebSocket.OPEN) {
				socket.send(event.data);
			} else if (!(event.data instanceof ArrayBuffer) && event.data.type === 'stopped') {
				markWorkletStopped?.();
			}
		};

		async function finishCapture(): Promise<void> {
			worklet.port.postMessage({ type: 'stop' });
			await Promise.race([
				workletStopped,
				new Promise<void>((resolve) => window.setTimeout(resolve, 250))
			]);
			await releaseCapture(resources);
		}

		return {
			sourceSampleRate: context.sampleRate,
			async finishInput(): Promise<void> {
				if (inputFinished) return;
				inputFinished = true;
				await finishCapture();
				if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'flush' }));
			},
			async close(): Promise<void> {
				if (!inputFinished) {
					inputFinished = true;
					await finishCapture();
				}
				socket.close(1000, 'audio capture closed');
			}
		};
	} catch (error) {
		if (stream) for (const track of stream.getTracks()) track.stop();
		await context.close();
		throw error;
	}
}

export function startCallPcm16Capture(
	callId: string,
	onEvent: PcmCaptureEventHandler
): Promise<PcmCaptureSession> {
	if (!callId.trim()) throw new Error('Call ID is required for microphone capture');
	const path = `/ws/call/${encodeURIComponent(callId)}`;
	return startPcm16Capture(onEvent, path);
}
