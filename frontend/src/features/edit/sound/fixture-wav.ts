const SAMPLE_RATE = 8000;
const SECONDS = 0.4;

/**
 * A short fixed tone as a `data:` URL, so a mock run can play a preview without a
 * server. The pitch follows the seed, which keeps two items audibly different
 * and one item the same on every press.
 */
export function fixtureWavUrl(seed: string): string {
  let hash = 0;
  for (const char of seed) hash = (hash * 31 + (char.codePointAt(0) ?? 0)) >>> 0;
  const frequency = 330 + (hash % 8) * 55;
  const samples = Math.floor(SAMPLE_RATE * SECONDS);
  const bytes = new Uint8Array(44 + samples * 2);
  const view = new DataView(bytes.buffer);
  const text = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };
  text(0, 'RIFF');
  view.setUint32(4, 36 + samples * 2, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, SAMPLE_RATE, true);
  view.setUint32(28, SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, 'data');
  view.setUint32(40, samples * 2, true);
  for (let index = 0; index < samples; index += 1) {
    const fade = Math.min(1, index / 200, (samples - index) / 200);
    const value = Math.sin((2 * Math.PI * frequency * index) / SAMPLE_RATE) * 0.3 * fade;
    view.setInt16(44 + index * 2, Math.round(value * 32767), true);
  }
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return `data:audio/wav;base64,${btoa(binary)}`;
}
