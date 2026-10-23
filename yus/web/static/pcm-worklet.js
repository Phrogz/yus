// AudioWorklet: the microphone, downsampled to 16 kHz mono PCM16, posted to the page in frames of `frameSamples` samples.
"use strict";

// Low-pass (windowed sinc, cutoff 0.45 x the output rate) at the input rate, then linear interpolation at the output rate.
class Downsampler {
  constructor(inRate, outRate = 16000, taps = 31) {
    this.step = inRate / outRate;
    this.kernel = new Float32Array(this.step > 1 ? taps : 1);
    if (this.step > 1) {
      const cutoff = (0.45 * outRate) / inRate; // cycles per input sample
      const m = taps - 1;
      let sum = 0;
      for (let i = 0; i < taps; i++) {
        const x = i - m / 2;
        const sinc = x === 0 ? 2 * Math.PI * cutoff : Math.sin(2 * Math.PI * cutoff * x) / x;
        this.kernel[i] = sinc * (0.54 - 0.46 * Math.cos((2 * Math.PI * i) / m)); // Hamming window
        sum += this.kernel[i];
      }
      for (let i = 0; i < taps; i++) this.kernel[i] /= sum;
    } else {
      this.kernel[0] = 1;
    }
    this.history = new Float32Array(this.kernel.length);
    this.head = 0; // where the next input sample goes in `history`
    this.n = 0; // input samples seen
    this.prev = 0; // the last filtered input sample
    this.next = 0; // input position of the next output sample
  }

  // Calls emit(sample) for each output sample the input completes.
  process(input, emit) {
    const kernel = this.kernel, history = this.history, taps = kernel.length;
    for (let i = 0; i < input.length; i++) {
      history[this.head] = input[i];
      let acc = 0;
      for (let k = 0, j = this.head; k < taps; k++, j = j === 0 ? taps - 1 : j - 1) acc += kernel[k] * history[j];
      this.head = (this.head + 1) % taps;
      while (this.next <= this.n) {
        const frac = this.next - (this.n - 1);
        emit(this.prev + (acc - this.prev) * frac);
        this.next += this.step;
      }
      this.prev = acc;
      this.n++;
    }
  }
}

if (typeof registerProcessor === "function") {
  class Pcm16Processor extends AudioWorkletProcessor {
    constructor(options) {
      super();
      const opts = (options && options.processorOptions) || {};
      this.down = new Downsampler(sampleRate, opts.targetRate || 16000);
      this.size = opts.frameSamples || 1600;
      this.frame = new Int16Array(this.size);
      this.fill = 0;
      this.energy = 0;
      this.mono = new Float32Array(128);
      this.emit = (v) => {
        const s = Math.max(-1, Math.min(1, v));
        this.frame[this.fill++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        this.energy += s * s;
        if (this.fill === this.size) {
          this.port.postMessage({ pcm: this.frame.buffer, level: Math.sqrt(this.energy / this.size) }, [this.frame.buffer]);
          this.frame = new Int16Array(this.size);
          this.fill = 0;
          this.energy = 0;
        }
      };
    }

    process(inputs) {
      const channels = inputs[0];
      if (channels && channels.length) {
        let mono = channels[0];
        if (channels.length > 1) {
          if (this.mono.length !== mono.length) this.mono = new Float32Array(mono.length);
          for (let i = 0; i < mono.length; i++) {
            let sum = 0;
            for (const channel of channels) sum += channel[i];
            this.mono[i] = sum / channels.length;
          }
          mono = this.mono;
        }
        this.down.process(mono, this.emit);
      }
      return true;
    }
  }
  registerProcessor("pcm16-downsampler", Pcm16Processor);
}

if (typeof module !== "undefined") module.exports = { Downsampler };
