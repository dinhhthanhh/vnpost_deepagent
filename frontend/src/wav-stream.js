// Incremental RIFF/WAV PCM parser. Does not assume a 44-byte header or a fixed sample rate.
export class WavPCMParser {
  constructor() {
    this.buffer = new Uint8Array(); this.riff = false; this.format = null;
    this.data = false; this.remaining = null; this.samples = 0; this.dataPad = 0;
  }
  append(bytes) {
    const combined = new Uint8Array(this.buffer.length + bytes.length);
    combined.set(this.buffer); combined.set(bytes, this.buffer.length); this.buffer = combined;
  }
  tag(offset) { return String.fromCharCode(...this.buffer.slice(offset, offset + 4)); }
  push(bytes) {
    this.append(bytes); const frames = [];
    if (!this.riff) {
      if (this.buffer.length < 12) return frames;
      if (this.tag(0) !== "RIFF" || this.tag(8) !== "WAVE") throw new Error("Luồng âm thanh không phải WAV.");
      this.riff = true; this.buffer = this.buffer.slice(12);
    }
    while (true) {
      if (this.data) {
        const alignment = this.format.channels * 2;
        const available = Math.min(this.buffer.length, this.remaining ?? Infinity);
        const size = Math.floor(available / alignment) * alignment;
        if (size) {
          const count = size / alignment, channels = Array.from({ length: this.format.channels }, () => new Float32Array(count));
          const view = new DataView(this.buffer.buffer, this.buffer.byteOffset, size);
          for (let i = 0; i < count; i++) for (let c = 0; c < channels.length; c++) {
            const sample = view.getInt16(i * alignment + c * 2, true);
            channels[c][i] = sample / (sample < 0 ? 32768 : 32767);
          }
          frames.push({ sampleRate: this.format.sampleRate, channels });
          this.samples += count; this.buffer = this.buffer.slice(size);
          if (this.remaining !== null) this.remaining -= size;
        }
        if (this.remaining !== 0) break;
        this.data = false;
        if (this.dataPad) {
          if (!this.buffer.length) break;
          this.buffer = this.buffer.slice(1); this.dataPad = 0;
        }
        continue;
      }
      if (this.dataPad) {
        if (!this.buffer.length) break;
        this.buffer = this.buffer.slice(1); this.dataPad = 0;
      }
      if (this.buffer.length < 8) break;
      const tag = this.tag(0), size = new DataView(this.buffer.buffer, this.buffer.byteOffset + 4, 4).getUint32(0, true);
      if (tag === "data") {
        if (!this.format) throw new Error("WAV chưa có thông tin định dạng.");
        const isStreaming = size === 0 || size === 0xffffffff || size >= 0x70000000;
        if (!isStreaming && (size % (this.format.channels * 2) !== 0)) {
          throw new Error("Kích thước PCM không hợp lệ.");
        }
        this.buffer = this.buffer.slice(8); this.data = true;
        this.remaining = isStreaming ? null : size; this.dataPad = isStreaming ? 0 : size % 2;
        continue;
      }
      if (size > 1024 * 1024) throw new Error("Header WAV quá lớn hoặc không hợp lệ.");
      if (this.buffer.length < 8 + size + size % 2) break;
      if (tag === "fmt ") {
        if (size < 16) throw new Error("Header fmt không hợp lệ.");
        const view = new DataView(this.buffer.buffer, this.buffer.byteOffset + 8, size);
        const codec = view.getUint16(0, true), channels = view.getUint16(2, true), sampleRate = view.getUint32(4, true);
        if (codec !== 1 || view.getUint16(14, true) !== 16 || channels < 1 || channels > 2 || sampleRate < 8000 || sampleRate > 192000 || view.getUint16(12, true) !== channels * 2) {
          throw new Error("Chỉ hỗ trợ streaming WAV PCM 16-bit mono/stereo.");
        }
        this.format = { channels, sampleRate };
      }
      this.buffer = this.buffer.slice(8 + size + size % 2);
    }
    return frames;
  }
  finish() {
    if (!this.format || !this.samples) {
      throw new Error("Luồng WAV chưa đầy đủ hoặc không có dữ liệu âm thanh.");
    }
    if (this.remaining !== null && this.remaining > (this.format.channels * 2)) {
      throw new Error("Luồng WAV bị ngắt trước khi hoàn tất.");
    }
  }
}

export async function playWavStream(response, audioContext, { onFirstAudio, signal } = {}) {
  const parser = new WavPCMParser(), reader = response.body.getReader();
  let nextTime = audioContext.currentTime + 0.05, first = true;
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("Đã dừng", "AbortError");
      const { done, value } = await reader.read(); if (done) break;
      for (const frame of parser.push(value)) {
        const buffer = audioContext.createBuffer(frame.channels.length, frame.channels[0].length, frame.sampleRate);
        frame.channels.forEach((channel, index) => buffer.copyToChannel(channel, index));
        const source = audioContext.createBufferSource(); source.buffer = buffer; source.connect(audioContext.destination);
        const at = Math.max(audioContext.currentTime + 0.01, nextTime); source.start(at); nextTime = at + buffer.duration;
        if (first) { onFirstAudio?.(); first = false; }
      }
      // Bound the queued playback to prevent huge numbers of scheduled AudioBuffers.
      while (nextTime - audioContext.currentTime > 3) {
        if (signal?.aborted) throw new DOMException("Đã dừng", "AbortError");
        await new Promise(resolve => setTimeout(resolve, 50));
      }
    }
    parser.finish();
    while (audioContext.currentTime < nextTime) {
      if (signal?.aborted) throw new DOMException("Đã dừng", "AbortError");
      await new Promise(resolve => setTimeout(resolve, 50));
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
