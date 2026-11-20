import type { Video } from '../client';

// Mock edit keeps its own video snapshot. The preset endpoint saves those settings.
export const editedVideoSettings = new Map<string, Video['settings']>();
