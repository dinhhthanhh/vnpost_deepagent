import { test } from "node:test";
import assert from "node:assert/strict";
import { WavPCMParser } from "../src/wav-stream.js";
import { parseSSE } from "../src/api.js";

function fixture({ sampleRate = 16000, channels = 1, junk = false } = {}) {
  const fmt = Buffer.alloc(24); fmt.write("fmt "); fmt.writeUInt32LE(16, 4); fmt.writeUInt16LE(1, 8); fmt.writeUInt16LE(channels, 10);
  fmt.writeUInt32LE(sampleRate, 12); fmt.writeUInt32LE(sampleRate * channels * 2, 16); fmt.writeUInt16LE(channels * 2, 20); fmt.writeUInt16LE(16, 22);
  const pcm = Buffer.alloc(12 * channels * 2);
  for (let i = 0; i < pcm.length; i += 2) pcm.writeInt16LE(i % 4 === 0 ? -32768 : 32767, i);
  const data = Buffer.alloc(8); data.write("data"); data.writeUInt32LE(pcm.length, 4);
  const metadata = Buffer.alloc(14); metadata.write("JUNK"); metadata.writeUInt32LE(5, 4); metadata.write("hello", 8);
  const body = Buffer.concat([fmt, ...(junk ? [metadata] : []), data, pcm]);
  const riff = Buffer.alloc(12); riff.write("RIFF"); riff.writeUInt32LE(body.length + 4, 4); riff.write("WAVE", 8);
  return Buffer.concat([riff, body]);
}

for (const chunkSize of [1, 2, 7, 13, 44, 1000]) test(`WAV fragmented in ${chunkSize}-byte chunks keeps every sample`, () => {
  const input = fixture({ junk: true }), parser = new WavPCMParser(); const frames = [];
  for (let i = 0; i < input.length; i += chunkSize) frames.push(...parser.push(input.subarray(i, i + chunkSize)));
  parser.finish(); assert.equal(frames.reduce((sum, f) => sum + f.channels[0].length, 0), 12);
  assert.ok(frames.every(f => f.sampleRate === 16000));
  assert.equal(frames[0].channels[0][0], -1);
});
test("WAV supports stereo and its actual sample rate", () => {
  const parser = new WavPCMParser(), [frame] = parser.push(fixture({ sampleRate: 22050, channels: 2 }));
  parser.finish(); assert.equal(frame.sampleRate, 22050); assert.equal(frame.channels.length, 2); assert.equal(frame.channels[0].length, 12);
});
test("WAV accepts unknown streaming data length", () => {
  const data = fixture(); data.writeUInt32LE(0xffffffff, 40);
  const parser = new WavPCMParser(); parser.push(data); parser.finish(); assert.equal(parser.samples, 12);
});
test("WAV detects truncated data instead of claiming playback completed", () => {
  const data = fixture(), parser = new WavPCMParser(); parser.push(data.subarray(0, data.length - 3));
  assert.throws(() => parser.finish(), /chưa đầy đủ/);
});
test("WAV rejects unsupported codecs and invalid headers", () => {
  const data = fixture(); data.writeUInt16LE(3, 20);
  assert.throws(() => new WavPCMParser().push(data), /PCM 16-bit/);
  assert.throws(() => new WavPCMParser().push(Buffer.alloc(20)), /không phải WAV/);
});
test("SSE preserves partial JSON frames and handles keepalive", () => {
  const a = parseSSE(': keepalive\n\nevent: answer\ndata: {"type":"answer","text":"xin chào"}\n\nevent: done\ndata: {"ty');
  assert.equal(a.items[0].text, "xin chào");
  const b = parseSSE(a.pending + 'pe":"done"}\n\n'); assert.equal(b.items[0].type, "done");
});
