import { useState, useCallback } from 'react';
import { uploadImage } from '../services/uploads';

export interface CropState {
  x: number;        // Horizontal starting point (0-1)
  y: number;        // Vertical starting point (0-1)
  scaleX: number;   // Width scale (1-3)
  scaleY: number;   // Height scale (1-3)
  mode: 'square' | 'free';
}

export interface UseImageCropOptions {
  onCropped?: (url: string) => void;
  onError?: (message: string) => void;
}

export interface UseImageCropResult {
  cropState: CropState;
  setCropState: React.Dispatch<React.SetStateAction<CropState>>;
  isCropping: boolean;
  handleCrop: (imageUrl: string) => Promise<void>;
  resetCrop: () => void;
}

const INITIAL_CROP_STATE: CropState = {
  x: 0.5,
  y: 0.5,
  scaleX: 1,
  scaleY: 1,
  mode: 'free',
};

/**
 * Custom hook for handling image cropping logic.
 * Extracted from MultimodalInput to improve code organization.
 */
export function useImageCrop(options: UseImageCropOptions = {}): UseImageCropResult {
  const [cropState, setCropState] = useState<CropState>(INITIAL_CROP_STATE);
  const [isCropping, setIsCropping] = useState(false);

  const { onCropped, onError } = options;

  const handleCrop = useCallback(async (imageUrl: string) => {
    if (!imageUrl) return;

    setIsCropping(true);
    try {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.src = imageUrl;

      await new Promise((res, rej) => {
        img.onload = res;
        img.onerror = rej;
      });

      const cropW = Math.min(img.naturalWidth, Math.max(16, img.naturalWidth / cropState.scaleX));
      const cropH = cropState.mode === 'square'
        ? Math.min(img.naturalHeight, Math.max(16, img.naturalHeight / cropState.scaleX))
        : Math.min(img.naturalHeight, Math.max(16, img.naturalHeight / cropState.scaleY));

      const sx = Math.max(0, Math.min(img.naturalWidth - cropW, cropState.x * img.naturalWidth));
      const sy = Math.max(0, Math.min(img.naturalHeight - cropH, cropState.y * img.naturalHeight));

      const canvas = document.createElement('canvas');
      canvas.width = cropW;
      canvas.height = cropH;

      const ctx = canvas.getContext('2d');
      if (!ctx) {
        throw new Error('Failed to get canvas context');
      }

      ctx.drawImage(img, sx, sy, cropW, cropH, 0, 0, cropW, cropH);

      canvas.toBlob(async (blob) => {
        if (!blob) return;

        const MEDIA_MAX_BYTES = 5 * 1024 * 1024;
        if (blob.size > MEDIA_MAX_BYTES) {
          onError?.('裁剪后文件超过 5MB');
          setIsCropping(false);
          return;
        }

        try {
          const file = new File([blob], 'cropped.png', { type: 'image/png' });
          const asset = await uploadImage(file);
          onCropped?.(asset.url);
        } catch (err) {
          onError?.(err instanceof Error ? err.message : '裁剪上传失败');
        } finally {
          setIsCropping(false);
        }
      }, 'image/png');
    } catch (err) {
      onError?.('裁剪失败');
      setIsCropping(false);
    }
  }, [cropState, onCropped, onError]);

  const resetCrop = useCallback(() => {
    setCropState(INITIAL_CROP_STATE);
  }, []);

  return {
    cropState,
    setCropState,
    isCropping,
    handleCrop,
    resetCrop,
  };
}

/**
 * Helper to calculate overlay dimensions for the crop preview.
 */
export function calculateCropOverlay(
  state: CropState
): { width: number; height: number; left: number; top: number } {
  const overlayW = Math.min(100, Math.max(5, 100 / state.scaleX));
  const overlayH = state.mode === 'square'
    ? overlayW
    : Math.min(100, Math.max(5, 100 / state.scaleY));
  const left = Math.min(100 - overlayW, Math.max(0, state.x * 100));
  const top = Math.min(100 - overlayH, Math.max(0, state.y * 100));

  return { width: overlayW, height: overlayH, left, top };
}

/**
 * Helper to calculate background style for crop preview thumbnail.
 */
export function calculateCropPreviewStyle(
  imageUrl: string,
  state: CropState
): React.CSSProperties {
  const scaleY = state.mode === 'square' ? state.scaleX : state.scaleY;
  return {
    backgroundImage: `url(${imageUrl})`,
    backgroundSize: `${100 * state.scaleX}% ${100 * scaleY}%`,
    backgroundPosition: `${-state.x * (100 * state.scaleX - 100)}% ${-state.y * (100 * scaleY - 100)}%`,
    backgroundRepeat: 'no-repeat' as const,
  };
}
