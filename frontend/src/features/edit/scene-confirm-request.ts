import { useSyncExternalStore } from 'react';

/**
 * The script step asks the edit step to open the scene check as soon as the
 * edit step can show it, so confirming the script leads straight to the one
 * confirmation that starts the video. The request belongs to one video and is
 * used up by the first edit step that shows it.
 */
let requested: string | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function requestSceneConfirm(videoId: string): void {
  requested = videoId;
  emit();
}

export function clearSceneConfirmRequest(): void {
  if (requested === null) return;
  requested = null;
  emit();
}

/** Whether the script step asked for the scene check of this video. */
export function useSceneConfirmRequested(videoId: string | null): boolean {
  return useSyncExternalStore(subscribe, () => videoId !== null && requested === videoId);
}
