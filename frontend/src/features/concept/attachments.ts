import type { Attachment } from './types';

/** The most text materials one video accepts (CONTRACTS 1.2). */
export const MAX_TEXT_ATTACHMENTS = 5;

export type Deployment = 'local' | 'hosted';
export type ReferencePlatform = 'youtube' | 'instagram' | 'tiktok';

export interface LinkPolicy {
  /** Whether the deployment may download a reference link at all. */
  enabled: boolean;
  /** Local runs show the warning and need an explicit yes before attaching. */
  consentRequired: boolean;
}

export type ReferenceUrlProblem =
  | 'empty'
  | 'length'
  | 'characters'
  | 'scheme'
  | 'syntax'
  | 'userinfo'
  | 'ip_literal'
  | 'port'
  | 'host';

export type ReferenceUrlCheck =
  | { ok: true; url: string; platform: ReferencePlatform }
  | { ok: false; reason: ReferenceUrlProblem };

interface PlatformRule {
  platform: ReferencePlatform;
  hosts: readonly string[];
}

/**
 * The three platforms in SPEC 8b. The server owns the download itself; this
 * list only refuses a link the mock boundary would reject anyway.
 */
const PLATFORM_RULES: readonly PlatformRule[] = [
  {
    platform: 'youtube',
    hosts: ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'],
  },
  {
    platform: 'instagram',
    hosts: ['instagram.com', 'www.instagram.com'],
  },
  {
    platform: 'tiktok',
    hosts: ['tiktok.com', 'www.tiktok.com', 'm.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'],
  },
];

const PLATFORMS = new Map<string, ReferencePlatform>(
  PLATFORM_RULES.flatMap((rule) => rule.hosts.map((host) => [host, rule.platform] as const)),
);

const MAX_URL_CHARS = 500;

/**
 * Hosted runs cannot download links (SPEC 8b). A local run can, but reads the
 * warning and asks for consent before the attachment exists.
 */
export function linkPolicy(deployment: Deployment): LinkPolicy {
  return deployment === 'local'
    ? { enabled: true, consentRequired: true }
    : { enabled: false, consentRequired: false };
}

/**
 * Validates a reference link before it becomes an attachment. The rules mirror
 * the server boundary: HTTPS only, no user info, no port, ASCII URL, and one
 * of the platform hosts. The returned URL drops the fragment.
 */
export function validateReferenceUrl(value: string): ReferenceUrlCheck {
  const url = value.trim();
  if (url === '') {
    return { ok: false, reason: 'empty' };
  }
  if (url.length > MAX_URL_CHARS) {
    return { ok: false, reason: 'length' };
  }
  if (url.includes('\\') || hasUnsafeCharacters(url)) {
    return { ok: false, reason: 'characters' };
  }
  if (!url.startsWith('https://')) {
    return { ok: false, reason: 'scheme' };
  }

  const authority = url.slice(8).split(/[/?#]/u, 1)[0] ?? '';
  if (authority === '' || /[\s]/u.test(authority)) {
    return { ok: false, reason: 'syntax' };
  }
  if (authority.includes('@')) {
    return { ok: false, reason: 'userinfo' };
  }
  if (authority.startsWith('[')) {
    return { ok: false, reason: 'ip_literal' };
  }
  if (authority.includes(':')) {
    return { ok: false, reason: 'port' };
  }

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return { ok: false, reason: 'syntax' };
  }
  if (parsed.protocol !== 'https:' || parsed.username !== '' || parsed.password !== '') {
    return { ok: false, reason: 'syntax' };
  }

  const host = parsed.hostname.toLowerCase();
  const platform = PLATFORMS.get(host);
  if (platform === undefined) {
    return { ok: false, reason: 'host' };
  }
  const fragmentAt = url.indexOf('#');
  return {
    ok: true,
    url: fragmentAt < 0 ? url : url.slice(0, fragmentAt),
    platform,
  };
}

function hasUnsafeCharacters(value: string): boolean {
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    if (code > 127 || code <= 32 || code === 127) {
      return true;
    }
  }
  return false;
}

/**
 * The attachment kind a picked file becomes. Images are recognised so the
 * caller can say they are unavailable instead of silently ignoring the file.
 */
export function attachmentKindOf(file: File): Attachment['kind'] | 'image' | null {
  const name = file.name.toLowerCase();
  const type = file.type.toLowerCase();
  if (type.startsWith('image/')) {
    return 'image';
  }
  if (type.startsWith('video/')) {
    return 'reference';
  }
  if (type.startsWith('audio/')) {
    return 'bgm';
  }
  if (/\.(mp4|m4v|mov|webm|mkv|avi)$/u.test(name)) {
    return 'reference';
  }
  if (/\.(mp3|wav|m4a|ogg|oga|flac|aac)$/u.test(name)) {
    return 'bgm';
  }
  if (
    name.endsWith('.md') ||
    name.endsWith('.txt') ||
    type === 'text/plain' ||
    type === 'text/markdown'
  ) {
    return 'text';
  }
  return null;
}

/** Reads a text material so its words travel with the attachment, not its name. */
export function readTextFile(file: File): Promise<string> {
  return file.text();
}

export function formatDurationMs(durationMs: number): string {
  const totalSeconds = Math.max(0, Math.round(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

let nextId = 0;

/** A local-only identifier; attachments never reach a server in this build. */
export function newAttachmentId(): string {
  nextId += 1;
  return `a_${String(nextId).padStart(4, '0')}`;
}
