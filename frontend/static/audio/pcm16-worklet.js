const TARGET_SAMPLE_RATE = 16_000;
const CHUNK_SAMPLES = 1_600;

class Pcm16CaptureProcessor extends AudioWorkletProcessor {
	constructor() {
		super();
		this.ratio = sampleRate / TARGET_SAMPLE_RATE;
		this.source = [];
		this.cursor = 0;
		this.output = [];
		this.stopped = false;
		this.port.onmessage = (event) => {
			if (event.data?.type === 'stop') {
				this.flushOutput();
				this.stopped = true;
				this.port.postMessage({ type: 'stopped' });
			}
		};
	}

	flushOutput() {
		if (this.output.length === 0) return;
		const pcm = new Int16Array(this.output.length);
		for (let index = 0; index < this.output.length; index += 1) {
			const sample = Math.max(-1, Math.min(1, this.output[index]));
			pcm[index] = sample < 0 ? Math.round(sample * 0x8000) : Math.round(sample * 0x7fff);
		}
		this.output = [];
		this.port.postMessage(pcm.buffer, [pcm.buffer]);
	}

	downsample(input) {
		for (let index = 0; index < input.length; index += 1) {
			this.source.push(input[index]);
		}

		while (this.cursor + this.ratio <= this.source.length) {
			const start = Math.floor(this.cursor);
			const end = Math.max(start + 1, Math.floor(this.cursor + this.ratio));
			let sum = 0;
			for (let index = start; index < end; index += 1) sum += this.source[index];
			this.output.push(sum / (end - start));
			this.cursor += this.ratio;
			if (this.output.length >= CHUNK_SAMPLES) this.flushOutput();
		}

		const consumed = Math.floor(this.cursor);
		if (consumed > 0) {
			this.source.splice(0, consumed);
			this.cursor -= consumed;
		}
	}

	process(inputs) {
		if (this.stopped) return false;
		const input = inputs[0]?.[0];
		if (input) this.downsample(input);
		return true;
	}
}

registerProcessor('pcm16-capture', Pcm16CaptureProcessor);
