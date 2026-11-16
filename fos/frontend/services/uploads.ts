import { apiClient } from "./client";
import { UploadedAsset } from "../types";

const MEDIA_MAX_SIZE_BYTES = 5 * 1024 * 1024;
const DOC_MAX_SIZE_BYTES = 10 * 1024 * 1024;
const DOC_TYPES = [
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
];
const ALLOWED = [
  'image/jpeg', 'image/png', 'image/gif', 'image/webp',
  'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/ogg',
  'video/mp4', 'video/webm',
  ...DOC_TYPES,
];

export interface UploadedFile {
  id: string;
  filename: string;
  size: number;
  created: number;
  type: string;
}

export async function uploadImage(
  file: File,
  opts: { onProgress?: (percent: number) => void; ocr?: boolean } = {}
): Promise<UploadedAsset> {
  const isDoc = DOC_TYPES.includes(file.type);
  const limit = isDoc ? DOC_MAX_SIZE_BYTES : MEDIA_MAX_SIZE_BYTES;
  if (file.size > limit) {
    throw new Error(isDoc ? "文档大小超过 10MB 限制" : "文件大小超过 5MB 限制");
  }
  if (file.type && !ALLOWED.includes(file.type)) {
    throw new Error("仅支持 JPG/PNG/GIF/WEBP/MP3/WAV/OGG/MP4/WEBM/TXT/PDF/DOC/DOCX");
  }

  const formData = new FormData();
  formData.append("file", file);
  if (opts.ocr) {
    formData.append("ocr", "true");
  }

  const response = await apiClient.post<UploadedAsset>("/uploads", formData, {
    onUploadProgress: (evt) => {
      if (!opts.onProgress) return;
      const percent = evt.total ? Math.round((evt.loaded / evt.total) * 100) : 0;
      opts.onProgress(percent);
    },
  });

  return response.data;
}

export async function listUploads(): Promise<UploadedFile[]> {
  const response = await apiClient.get<UploadedFile[]>("/uploads");
  return response.data;
}

export async function deleteUpload(fileId: string): Promise<{ deleted: number; id: string }> {
  const response = await apiClient.delete<{ deleted: number; id: string }>(`/uploads/${fileId}`);
  return response.data;
}

export async function findOrphans(): Promise<{ orphaned: string[]; total: number; note?: string }> {
  const response = await apiClient.post<{ orphaned: string[]; total: number; note?: string }>("/uploads/cleanup", {});
  return response.data;
}
