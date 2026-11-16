/**
 * This file decides which landing page preview video to show.
 * isBilibiliConfigured tells the page if a Bilibili video id was provided.
 * getBilibiliEmbedUrl builds the Bilibili player link when that id exists.
 */

export const VIDEO_CONFIG = {
  bilibili: {
    baseUrl: "https://player.bilibili.com/player.html",
    bvId: import.meta.env.VITE_BILIBILI_VIDEO_BVID || "",
  },
} as const;

export function isBilibiliConfigured(): boolean {
  return Boolean(VIDEO_CONFIG.bilibili.bvId);
}

export function getBilibiliEmbedUrl(): string {
  const { baseUrl, bvId } = VIDEO_CONFIG.bilibili;
  return `${baseUrl}?bvid=${bvId}`;
}
