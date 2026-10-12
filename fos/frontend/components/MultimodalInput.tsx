import React, { useState, useCallback, DragEvent, useId } from 'react';
import { uploadImage } from '../services/uploads';
import { useTranslation } from 'react-i18next';
import { Image as ImageIcon, Loader2, Upload as UploadIcon, X } from 'lucide-react';
import { useImageCrop, calculateCropOverlay, calculateCropPreviewStyle } from '../hooks/useImageCrop';

interface Props {
  label?: string;
  helperText?: string;
  onInsert?: (url: string, altText?: string) => void;
  onUploadComplete?: (url: string) => void;
  presetUrl?: string | null;
  enableCrop?: boolean;
  enableAltText?: boolean; // Enable alt text input for accessibility
}

const MEDIA_MAX_BYTES = 5 * 1024 * 1024;
const DOC_MAX_BYTES = 10 * 1024 * 1024;
const DOC_TYPES = ['application/pdf','application/msword','application/vnd.openxmlformats-officedocument.wordprocessingml.document'];
const ALLOWED = ['image/jpeg','image/png','image/gif','image/webp','audio/mpeg','audio/mp3','audio/wav','audio/ogg','video/mp4','video/webm',...DOC_TYPES];

export const MultimodalInput: React.FC<Props> = ({
  label,
  helperText,
  onInsert,
  onUploadComplete,
  presetUrl = null,
  enableCrop = true,
  enableAltText = true
}) => {
  const { t } = useTranslation();
  const [previewUrl, setPreviewUrl] = useState<string | null>(presetUrl);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [status, setStatus] = useState<{ kind: 'idle' | 'error' | 'success'; message: string }>({ kind: 'idle', message: '' });
  const [altText, setAltText] = useState('');
  const [progress, setProgress] = useState(0);
  const [lastUploadedName, setLastUploadedName] = useState<string>('');
  const [imageError, setImageError] = useState(false);
  const inputId = useId();

  // Use the custom hook for cropping logic
  const {
    cropState,
    setCropState,
    isCropping,
    handleCrop,
    resetCrop,
  } = useImageCrop({
    onCropped: (url) => {
      setPreviewUrl(url);
      onInsert?.(url, altText || undefined);
      setStatus({ kind: 'success', message: t('components.multimodalInput.cropAndUploadSuccess') });
    },
    onError: (message) => {
      setStatus({ kind: 'error', message });
    },
  });

  const setError = (message: string) => setStatus({ kind: 'error', message });
  const setSuccess = (message: string) => setStatus({ kind: 'success', message });

  const handleFile = async (file: File | null) => {
    if (!file) return;
    const isDoc = DOC_TYPES.includes(file.type);
    const limit = isDoc ? DOC_MAX_BYTES : MEDIA_MAX_BYTES;
    if (file.size > limit) {
      setError(isDoc ? t('components.multimodalInput.docSizeLimit') : t('components.multimodalInput.fileSizeLimit'));
      return;
    }
    if (file.type && !ALLOWED.includes(file.type)) {
      setError(t('components.multimodalInput.allowedTypes'));
      return;
    }
    setIsUploading(true);
    setProgress(0);
    setStatus({ kind: 'idle', message: '' });
    setImageError(false);
    try {
      const asset = await uploadImage(file, { onProgress: setProgress });
      const isImage = file.type.startsWith('image/');
      console.log('Uploaded asset:', asset); // Debug
      setPreviewUrl(isImage ? asset.url : null);
      setLastUploadedName(file.name);
      onInsert?.(asset.url, altText || undefined);
      onUploadComplete?.(asset.url);
      setSuccess(t('components.multimodalInput.uploadSuccess'));
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : t('components.multimodalInput.uploadFailed'));
    } finally {
      setIsUploading(false);
    }
  };

  const onDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    handleFile(file ?? null);
  }, []);

  const onDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback(() => setIsDragging(false), []);

  return (
    <div className="space-y-2">
      {label && <div className="text-xs font-bold text-slate-700">{label}</div>}
      <div
        className={`border-2 border-dashed rounded-lg p-3 bg-white flex flex-col items-center justify-center text-xs text-slate-500 cursor-pointer transition-colors ${isDragging ? 'border-emerald-400 bg-emerald-50' : 'border-slate-300 hover:border-slate-400'}`}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onClick={() => document.getElementById(inputId)?.click()}
      >
        <input
          id={inputId}
          type="file"
          className="hidden"
          accept="image/*,audio/*,video/*,.pdf,.doc,.docx"
          onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
        />
        {isUploading ? (
          <div className="flex items-center gap-2 text-emerald-600">
            <Loader2 size={16} className="animate-spin" /> {t('components.multimodalInput.uploading')}
          </div>
        ) : (
          <div className="flex flex-col items-center gap-1">
            <UploadIcon size={18} className="text-slate-400" />
            <span>{t('components.multimodalInput.dragDropUpload')}</span>
          </div>
        )}
      </div>
      <div className="text-[11px] text-slate-400">
        {helperText || (enableCrop ? t('components.multimodalInput.dragDropUploadWithCrop') : t('components.multimodalInput.dragDropUploadSimple'))}{t('components.multimodalInput.sizeWarning')}
      </div>
      {status.kind !== 'idle' && (
        <div className={`text-[11px] ${status.kind === 'error' ? 'text-red-500' : 'text-emerald-600'}`}>
          {status.message}
        </div>
      )}
      {isUploading && (
        <div className="w-full h-2 bg-slate-100 rounded overflow-hidden">
          <div className="h-full bg-emerald-500 transition-all" style={{ width: `${progress}%` }} />
        </div>
      )}
      {enableAltText && (
        <div className="space-y-1">
          <label className="text-xs font-semibold text-slate-700">
            {t('components.multimodalInput.imageDescLabel')}
          </label>
          <input
            type="text"
            className="w-full px-2 py-1 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-emerald-400"
            placeholder={t('components.multimodalInput.imageDescPlaceholder')}
            value={altText}
            onChange={(e) => setAltText(e.target.value)}
            maxLength={200}
          />
          <div className="text-[10px] text-slate-400">
            {altText.length}/200
          </div>
        </div>
      )}
      {previewUrl && (
        <div className="relative w-full border rounded bg-black/5" style={{ minHeight: '300px' }}>
          {imageError ? (
            <div className="flex items-center justify-center h-[300px] text-red-500">
              {t('components.multimodalInput.imageLoadError')} {previewUrl}
            </div>
          ) : (
            <img
              src={previewUrl}
              alt="preview"
              className="w-full rounded"
              style={{ maxHeight: '400px', objectFit: 'contain' }}
              onError={() => { console.error('Image load error:', previewUrl); setImageError(true); }}
              onLoad={() => { console.log('Image loaded:', previewUrl); setImageError(false); }}
            />
          )}
          {enableCrop && (
            <div className="absolute inset-0 pointer-events-none">
              <div
                className="absolute border-2 border-emerald-400/80 shadow-[0_0_0_9999px_rgba(0,0,0,0.25)]"
                style={{
                  width: `${calculateCropOverlay(cropState).width}%`,
                  height: `${calculateCropOverlay(cropState).height}%`,
                  left: `${calculateCropOverlay(cropState).left}%`,
                  top: `${calculateCropOverlay(cropState).top}%`
                }}
              />
            </div>
          )}
          <button
            onClick={() => {
              setPreviewUrl(null);
              setLastUploadedName('');
              setStatus({ kind: 'idle', message: '' });
              resetCrop();
            }}
            className="absolute top-2 right-2 bg-white/90 rounded-full p-1 shadow text-slate-600 hover:text-red-500"
          >
            <X size={14} />
          </button>
          {enableCrop && (
            <div className="bg-white/90 backdrop-blur p-2 flex flex-wrap gap-3 items-center text-[11px] text-slate-700 sticky bottom-0">
              <label className="flex items-center gap-1">{t('components.multimodalInput.xOrigin')}<input type="range" min="0" max="1" step="0.01" value={cropState.x} onChange={(e) => setCropState({ ...cropState, x: Number(e.target.value) })} /></label>
              <label className="flex items-center gap-1">{t('components.multimodalInput.yOrigin')}<input type="range" min="0" max="1" step="0.01" value={cropState.y} onChange={(e) => setCropState({ ...cropState, y: Number(e.target.value) })} /></label>
              <label className="flex items-center gap-1">{t('components.multimodalInput.mode')}
                <select
                  className="border rounded px-1 py-0.5 text-[11px]"
                  value={cropState.mode}
                  onChange={(e) => {
                    const mode = e.target.value as 'square' | 'free';
                    setCropState({ ...cropState, mode, scaleY: mode === 'square' ? cropState.scaleX : cropState.scaleY });
                  }}
                >
                  <option value="square">{t('components.multimodalInput.square')}</option>
                  <option value="free">{t('components.multimodalInput.free')}</option>
                </select>
              </label>
              <label className="flex items-center gap-1">{t('components.multimodalInput.widthScale')}<input type="range" min="1" max="3" step="0.05" value={cropState.scaleX} onChange={(e) => {
                const val = Number(e.target.value);
                setCropState({ ...cropState, scaleX: val, scaleY: cropState.mode === 'square' ? val : cropState.scaleY });
              }} /></label>
              <label className="flex items-center gap-1">{t('components.multimodalInput.heightScale')}
                <input
                  type="range"
                  min="1"
                  max="3"
                  step="0.05"
                  value={cropState.scaleY}
                  disabled={cropState.mode === 'square'}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    setCropState({ ...cropState, scaleY: val, scaleX: cropState.mode === 'square' ? val : cropState.scaleX });
                  }}
                />
              </label>
              <div className="flex items-center gap-2 ml-auto">
                <div
                  className="w-16 h-16 rounded border overflow-hidden bg-white"
                  style={calculateCropPreviewStyle(previewUrl, cropState)}
                  title={t('components.multimodalInput.cropPreview')}
                />
                <button
                  onClick={() => handleCrop(previewUrl)}
                  disabled={isUploading || isCropping}
                  className="px-2 py-1 bg-white border rounded text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-60"
                >
                  {isCropping ? t('components.multimodalInput.cropping') : t('components.multimodalInput.cropAndReupload')}
                </button>
                <button
                  onClick={() => {
                    setPreviewUrl(null);
                    setLastUploadedName('');
                    setStatus({ kind: 'idle', message: '' });
                    resetCrop();
                  }}
                  className="px-2 py-1 border border-red-200 text-red-600 rounded text-[11px] hover:bg-red-50"
                >
                  {t('components.multimodalInput.deleteImage')}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
      {!previewUrl && lastUploadedName && status.kind === 'success' && (
        <div className="text-[11px] text-slate-600">{t('components.multimodalInput.uploaded')} {lastUploadedName}</div>
      )}
    </div>
  );
};
