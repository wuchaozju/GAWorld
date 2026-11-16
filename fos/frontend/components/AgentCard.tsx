/**
 * Agent card component for the workspace agent panel.
 *
 * Displays a single agent's profile, LLM configuration, attributes,
 * knowledge base, uploaded documents, and short-term memory.
 * Handles profile editing, knowledge CRUD, document uploads with RAG, and LLM switching.
 *
 * Exports: AgentCard
 */
import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSimulationStore } from '../store';
import { Brain, Activity, ChevronDown, ChevronRight, Bot, BookOpen, Plus, FileText, Trash2, Upload, File, Loader2, Edit3, Save, X, RefreshCw } from 'lucide-react';
import { Agent, KnowledgeItem } from '../types';
import { uploadAgentDocument, listAgentDocuments, deleteAgentDocument, DocumentInfo } from '../services/simulations';
import { listProviders, Provider } from '../services/providers';
import { MultimodalInput } from './MultimodalInput';

const renderProfileHtml = (text: string) => {
  const escape = (v: string) => v.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#x27;');
  const escaped = escape(text || '');
  const withImages = escaped.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_m, alt, url) => {
    const safeAlt = escape(alt || 'image');
    // Only allow safe URL protocols (http, https, relative paths)
    const trimmedUrl = (url || '').trim();
    const isSafeUrl = /^(https?:\/\/|\/[^/]|\.\/|[^:/?#][^?#]*)$/i.test(trimmedUrl) && !trimmedUrl.toLowerCase().startsWith('javascript:') && !trimmedUrl.toLowerCase().startsWith('data:text/html');
    if (!isSafeUrl) {
      return `[${safeAlt}]`;
    }
    const safeUrl = escape(trimmedUrl);
    return `<img src="${safeUrl}" alt="${safeAlt}" class="inline-block max-h-32 rounded border mr-2 mb-2" style="border-color:var(--ss-workspace-border)" />`;
  });
  return withImages.replace(/\n/g, '<br />');
};

const humanizeBackendLabel = (value: string): string => {
  const normalized = String(value || '').trim();
  if (!normalized) return '';
  return normalized
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());
};

export const AgentCard: React.FC<{ agent: Agent }> = ({ agent }) => {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(false);
  const [isMemoryOpen, setIsMemoryOpen] = useState(true);
  const [isPropsOpen, setIsPropsOpen] = useState(false);
  const [isKBOpen, setIsKBOpen] = useState(false); // #23
  const [isDocsOpen, setIsDocsOpen] = useState(false); // Documents section

  const addKnowledgeToAgent = useSimulationStore(state => state.addKnowledgeToAgent);
  const removeKnowledgeFromAgent = useSimulationStore(state => state.removeKnowledgeFromAgent);
  const updateKnowledgeInAgent = useSimulationStore(state => state.updateKnowledgeInAgent);
  const updateAgentProfile = useSimulationStore(state => state.updateAgentProfile);
  const updateAgentLLM = useSimulationStore(state => state.updateAgentLLM);
  const addNotification = useSimulationStore(state => state.addNotification);
  const simulationId = useSimulationStore(state => state.currentSimulation?.id);
  const selectedNodeId = useSimulationStore(state => state.selectedNodeId);

  const [newKbTitle, setNewKbTitle] = useState('');
  const [newKbContent, setNewKbContent] = useState('');
  const [isAddingKB, setIsAddingKB] = useState(false);

  // LLM dropdown state
  const [availableProviders, setAvailableProviders] = useState<Provider[]>([]);
  const [providersLoading, setProvidersLoading] = useState<boolean>(true);
  const [providersError, setProvidersError] = useState<string | null>(null);

  const translateMemoryType = (type: string) => {
    switch (type) {
      case 'thought':
        return t('components.agentPanel.memoryTypes.thought');
      case 'assistant':
        return t('components.agentPanel.memoryTypes.assistant');
      case 'user':
        return t('components.agentPanel.memoryTypes.user');
      case 'system':
        return t('components.agentPanel.memoryTypes.system');
      default:
        return humanizeBackendLabel(type);
    }
  };

  // Fetch available LLM providers
  useEffect(() => {
    const fetchProviders = async () => {
      setProvidersLoading(true);
      setProvidersError(null);
      try {
        const providers = await listProviders();
        setAvailableProviders(providers);
      } catch (err) {
        console.error('Failed to fetch LLM providers:', err);
        setProvidersError(t('components.agentPanel.providersLoadError', { defaultValue: '加载提供商失败' }));
      } finally {
        setProvidersLoading(false);
      }
    };
    fetchProviders();
  }, [t]);

  // Handle LLM change
  const handleLLMChange = async (providerId: number) => {
    const provider = availableProviders.find(p => p.id === providerId);
    if (!provider) return;

    await updateAgentLLM(agent.name, {
      provider: provider.provider,
      model: provider.model,
      provider_id: providerId,
    });
  };

  // Edit state for knowledge items
  const [editingItemId, setEditingItemId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');

  const trimmedProfile = String(agent.profile || '').trim();
  const trimmedRole = String(agent.role || '').trim();
  const profileText = trimmedProfile || t('components.agentPanel.noProfile');
  const roleBadgeText = trimmedRole.length > 0 && trimmedRole.length <= 40 ? trimmedRole : '';
  const rolePreviewText = trimmedRole.length > 40 ? trimmedRole : '';

  // Profile editing state
  const [isProfileEditing, setIsProfileEditing] = useState(false);
  const [profileDraft, setProfileDraft] = useState(agent.profile);

  // Document upload state
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load documents when docs section is opened
  const loadDocuments = useCallback(async () => {
    if (!simulationId) return;
    try {
      // Pass selectedNodeId to fetch documents from the correct tree node
      const docs = await listAgentDocuments(simulationId, agent.name, selectedNodeId ?? undefined);
      setDocuments(docs);
    } catch (err) {
      console.error('Failed to load documents:', err);
    }
  }, [simulationId, agent.name, selectedNodeId]);

  // Auto-load documents when node changes to keep count accurate
  useEffect(() => {
    if (simulationId) {
      loadDocuments();
    }
  }, [simulationId, selectedNodeId, agent.name, loadDocuments]);

  const handleDocsToggle = () => {
    const newState = !isDocsOpen;
    setIsDocsOpen(newState);
    if (newState) {
      loadDocuments();
    }
  };

  // Handle file upload
  const handleFileUpload = async (file: File) => {
    if (!simulationId) {
      setUploadError(t('components.agentPanel.noSimulationId'));
      return;
    }

    // Validate file type
    const allowedTypes = ['.pdf', '.txt', '.docx', '.md'];
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!allowedTypes.includes(ext)) {
      setUploadError(t('components.agentPanel.invalidFileType', { types: allowedTypes.join(', ') }));
      return;
    }

    // Validate file size (10MB)
    if (file.size > 10 * 1024 * 1024) {
      setUploadError(t('components.agentPanel.fileTooLarge'));
      return;
    }

    setIsUploading(true);
    setUploadError(null);

    try {
      console.log(`INFO: Upload started - agent=${agent.name}, file=${file.name}`);
      const result = await uploadAgentDocument(simulationId, agent.name, file);
      console.log(`INFO: Upload complete - doc_id=${result.doc_id}, chunks=${result.chunks_count}`);
      loadDocuments(); // Refresh the list
    } catch (err: any) {
      console.error('ERROR: Upload failed -', err);
      setUploadError(err.message || t('components.agentPanel.uploadFailed'));
    } finally {
      setIsUploading(false);
    }
  };

  // Handle delete document
  const handleDeleteDocument = async (docId: string) => {
    if (!simulationId) return;
    try {
      await deleteAgentDocument(simulationId, agent.name, docId);
      loadDocuments();
    } catch (err) {
      console.error('Failed to delete document:', err);
    }
  };

  // Drag and drop handlers
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
    // Reset input
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  // Format file size
  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  // Helper to color code models
  const getModelBadgeStyle = (provider: string): { className: string; style?: React.CSSProperties } => {
    switch(provider.toLowerCase()) {
      case 'openai': return { className: 'bg-green-50 text-green-700 border-green-200' };
      case 'anthropic': return { className: 'bg-amber-50 text-amber-700 border-amber-200' };
      case 'google': return { className: 'bg-blue-50 text-blue-700 border-blue-200' };
      default: return { className: '', style: { color: 'var(--ss-workspace-text)', borderColor: 'var(--ss-workspace-border)' } };
    }
  };

  const handleAddKB = () => {
    if (!newKbTitle || !newKbContent) return;
    const item: KnowledgeItem = {
      id: `kb-${Date.now()}`,
      title: newKbTitle,
      type: 'text',
      content: newKbContent,
      enabled: true,
      timestamp: new Date().toISOString()
    };
    addKnowledgeToAgent(agent.id, item);
    setNewKbTitle('');
    setNewKbContent('');
    setIsAddingKB(false);
  };

  // Edit handlers for knowledge items
  const handleStartEdit = (kb: KnowledgeItem) => {
    setEditingItemId(kb.id);
    setEditTitle(kb.title);
    setEditContent(kb.content);
  };

  const handleSaveEdit = () => {
    if (!editingItemId || !editTitle.trim()) return;
    updateKnowledgeInAgent(agent.id, editingItemId, {
      title: editTitle,
      content: editContent,
      timestamp: new Date().toISOString()
    });
    setEditingItemId(null);
    setEditTitle('');
    setEditContent('');
  };

  const handleCancelEdit = () => {
    setEditingItemId(null);
    setEditTitle('');
    setEditContent('');
  };

  return (
    <div className="ss-agent-card border-b last:border-b-0" style={{ background: 'var(--ss-workspace-surface)' }}>
      {/* Collapsible Header — always visible, click to expand/collapse */}
      <div
        className="flex items-start gap-4 px-4 py-4 cursor-pointer select-none"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <img
          src={agent.avatarUrl}
          alt={agent.name}
          className="w-14 h-14 rounded-2xl border object-cover flex-shrink-0 shadow-sm"
          style={{ borderColor: 'var(--ss-workspace-border)' }}
        />
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="max-w-full text-base font-bold leading-tight break-words" style={{ color: 'var(--ss-workspace-heading)' }}>{agent.name}</h4>
            {roleBadgeText ? (
              <span className="ss-agent-card__role-chip" style={{ background: 'var(--ss-surface-inset)', color: 'var(--ss-workspace-text)', borderColor: 'var(--ss-workspace-border)' }}>
                {roleBadgeText}
              </span>
            ) : null}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <span className={`inline-flex max-w-full items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] ${getModelBadgeStyle(agent.llmConfig?.provider || 'default').className}`} style={getModelBadgeStyle(agent.llmConfig?.provider || 'default').style}>
              <Bot size={11} />
              <span className="font-mono break-all">{agent.llmConfig?.model || t('components.agentPanel.auto')}</span>
            </span>
          </div>
          {rolePreviewText ? (
            <div className="ss-agent-card__role-preview">
              <div className="ss-agent-card__role-preview-copy">{rolePreviewText}</div>
            </div>
          ) : null}
          <div className="ss-agent-card__profile-preview">
            <div className="ss-agent-card__profile-preview-copy">{profileText}</div>
          </div>
        </div>
        <div className="ml-auto flex-shrink-0">
          {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </div>

      {/* Expanded content — heavy sections only mounted when expanded */}
      {isExpanded && (
        <div className="px-3 pb-3 border-t" style={{ borderColor: 'var(--ss-workspace-border)' }}>
          {/* Profile section */}
          {isProfileEditing ? (
            <div className="space-y-2 mt-3">
              <textarea
                value={profileDraft}
                onChange={(e) => setProfileDraft(e.target.value)}
                className="w-full text-xs border rounded p-2 focus:ring-1 focus:ring-brand-500 outline-none min-h-[80px]"
                placeholder={t('components.agentPanel.profilePlaceholder')}
              />
              <MultimodalInput
                helperText={t('components.agentPanel.uploadHelperText')}
                onInsert={(url) => setProfileDraft((prev) => `${prev}${prev ? '\n' : ''}![image](${url})`)}
              />
              <div className="flex gap-2">
                <button
                  className="flex-1 py-1.5 bg-brand-600 text-white rounded text-xs flex items-center justify-center gap-1"
                  onClick={() => {
                    updateAgentProfile(agent.id, profileDraft);
                    setIsProfileEditing(false);
                  }}
                >
                  <Save size={12} /> {t('components.agentPanel.saveProfile')}
                </button>
                <button
                  className="flex-1 py-1.5 text-xs flex items-center justify-center gap-1 rounded"
                  style={{ background: 'var(--ss-surface-inset)', color: 'var(--ss-workspace-text)' }}
                  onClick={() => {
                    setProfileDraft(agent.profile);
                    setIsProfileEditing(false);
                  }}
                >
                  <X size={12} /> {t('common.cancel')}
                </button>
              </div>
            </div>
          ) : (
            <>
              {trimmedRole ? (
                <div className="ss-agent-card__profile-section">
                  <div className="ss-agent-card__profile-section-head">
                    <span className="ss-agent-card__profile-section-label">
                      {t('components.agentPanel.roleLabel', { defaultValue: '角色设定' })}
                    </span>
                  </div>
                  <div
                    className="ss-agent-card__profile-box markdown-body"
                    style={{ color: 'var(--ss-workspace-muted)' }}
                    dangerouslySetInnerHTML={{ __html: renderProfileHtml(trimmedRole) }}
                  />
                </div>
              ) : null}
              <div className="ss-agent-card__profile-section">
                <div className="ss-agent-card__profile-section-head">
                  <span className="ss-agent-card__profile-section-label">
                    {t('components.agentPanel.profileLabel', { defaultValue: '智能体简介' })}
                  </span>
                  <button
                    className="ss-agent-card__profile-edit hover:text-brand-600"
                    style={{ color: 'var(--ss-workspace-muted)' }}
                    onClick={() => setIsProfileEditing(true)}
                    title={t('components.agentPanel.editProfile')}
                  >
                    <Edit3 size={14} />
                  </button>
                </div>
                <div
                  className={`ss-agent-card__profile-box markdown-body${trimmedProfile ? '' : ' is-empty'}`}
                  style={{ color: 'var(--ss-workspace-muted)' }}
                  dangerouslySetInnerHTML={{ __html: renderProfileHtml(profileText) }}
                />
              </div>
            </>
          )}

          {/* LLM Provider Dropdown (expanded only) */}
          <div className="mt-3 flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase" style={{ color: 'var(--ss-workspace-muted)' }}>
              {t('components.agentPanel.changeLLM', { defaultValue: '切换 LLM' })}
            </span>
            {providersLoading ? (
              <span className="flex items-center gap-1 text-[10px]" style={{ color: 'var(--ss-workspace-muted)' }}>
                <Loader2 size={10} className="animate-spin" />
              </span>
            ) : providersError ? (
              <div className="flex items-center gap-1">
                <span className="text-[10px] text-red-500">{providersError}</span>
                <button
                  onClick={() => {
                    setProvidersError(null);
                    setProvidersLoading(true);
                    listProviders()
                      .then(setAvailableProviders)
                      .catch(() => {
                        setProvidersError(t('components.agentPanel.providersLoadError', { defaultValue: '加载提供商失败' }));
                      })
                      .finally(() => setProvidersLoading(false));
                  }}
                  className="hover:text-brand-500 p-1"
                  style={{ color: 'var(--ss-workspace-muted)' }}
                  title={t('components.agentPanel.retry', { defaultValue: '重试' })}
                >
                  <RefreshCw size={10} />
                </button>
              </div>
            ) : (
              <select
                value={(() => {
                  if (agent.provider_id != null) {
                    return String(agent.provider_id);
                  }
                  const matched = availableProviders.find(p =>
                    p.provider === agent.llmConfig?.provider && p.model === agent.llmConfig?.model
                  );
                  return matched ? String(matched.id) : '';
                })()}
                onChange={(e) => {
                  const providerId = Number(e.target.value);
                  if (!isNaN(providerId)) handleLLMChange(providerId);
                }}
                className={`text-[10px] border rounded px-1.5 py-0.5 focus:ring-1 focus:ring-brand-500 focus:border-brand-500 ${getModelBadgeStyle(agent.llmConfig?.provider || 'default').className}`}
                style={getModelBadgeStyle(agent.llmConfig?.provider || 'default').style}
              >
                <option value="" disabled>
                  {agent.llmConfig?.model || t('components.agentPanel.auto')}
                </option>
                {availableProviders.map(p => (
                  <option key={p.id} value={String(p.id)}>
                    {p.provider} - {p.model}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Attributes Comparison Section (#6 contrast view placeholder) */}
          <div className="mt-2">
            <button
              onClick={() => setIsPropsOpen(!isPropsOpen)}
              className="w-full flex items-center justify-between px-2 py-1.5 transition-colors rounded"
              style={{ background: 'var(--ss-surface-strong)' }}
            >
              <div className="flex items-center gap-2 text-xs font-semibold" style={{ color: 'var(--ss-workspace-heading)' }}>
                <Activity size={14} />
                <span>{t('components.agentPanel.currentAttributes')}</span>
              </div>
              {isPropsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>

            {isPropsOpen && (
              <div className="p-3 grid grid-cols-2 gap-2">
                {Object.entries(agent.properties)
                  .filter(([key]) => !['emotion_enabled', 'archetype_id', 'demographic_attributes', 'internal', '_internal', 'avatarUrl'].includes(key))
                  .map(([key, value]) => (
                  <div key={key} className="flex flex-col p-2 rounded border" style={{ background: 'var(--ss-surface-strong)' }}>
                    <span className="text-[10px] uppercase font-bold" style={{ color: 'var(--ss-workspace-muted)' }}>{key}</span>
                    <span className="text-sm font-mono font-medium" style={{ color: 'var(--ss-workspace-heading)' }}>{String(value)}</span>
                  </div>
                ))}
                {Object.entries(agent.properties).filter(([key]) =>
!['emotion_enabled', 'archetype_id', 'demographic_attributes', 'internal', '_internal', 'avatarUrl'].includes(key)
                ).length === 0 && (
                  <div className="col-span-2 text-center text-xs italic py-2" style={{ color: 'var(--ss-workspace-muted)' }}>
                    {t('components.agentPanel.noCustomAttributes')}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Knowledge Base (#23) */}
          <div className="mt-2 border-t" style={{ borderColor: 'var(--ss-workspace-border)' }}>
            <button
              onClick={() => setIsKBOpen(!isKBOpen)}
              className="w-full flex items-center justify-between px-2 py-1.5 transition-colors rounded"
              style={{ background: 'var(--ss-surface-strong)' }}
            >
              <div className="flex items-center gap-2 text-xs font-semibold" style={{ color: 'var(--ss-workspace-heading)' }}>
                <BookOpen size={14} />
                <span>{t('components.agentPanel.knowledgeBase')} ({agent.knowledgeBase.length})</span>
              </div>
              {isKBOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>

            {isKBOpen && (
              <div className="p-3 space-y-3" style={{ background: 'var(--ss-surface-strong)' }}>
                 {agent.knowledgeBase.length === 0 && !isAddingKB && (
                   <div className="text-center py-2 text-xs italic" style={{ color: 'var(--ss-workspace-muted)' }}>{t('components.agentPanel.noKnowledgeDocs')}</div>
                 )}

                 {agent.knowledgeBase.map(kb => {
                   const isEditing = editingItemId === kb.id;
                   return (
                     <div key={kb.id} className="border rounded p-2 text-xs relative group" style={{ background: 'var(--ss-workspace-surface)' }}>
                       {isEditing ? (
                         <div className="space-y-2">
                           <input
                             type="text"
                             value={editTitle}
                             onChange={(e) => setEditTitle(e.target.value)}
                             className="w-full p-1 border rounded text-xs outline-none focus:ring-1 focus:ring-brand-500"
                             placeholder={t('components.agentPanel.title')}
                           />
                           <textarea
                             value={editContent}
                             onChange={(e) => setEditContent(e.target.value)}
                             className="w-full p-1 border rounded text-xs h-20 resize-none outline-none focus:ring-1 focus:ring-brand-500"
                             placeholder={t('components.agentPanel.knowledgeContent')}
                           />
                           <div className="flex gap-2 justify-end">
                             <button
                               onClick={handleSaveEdit}
                               disabled={!editTitle.trim()}
                               className="px-2 py-1 text-green-600 hover:text-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
                             >
                               {t('components.agentPanel.save')}
                             </button>
                             <button
                               onClick={handleCancelEdit}
                               className="px-2 py-1 hover:text-slate-600"
                               style={{ color: 'var(--ss-workspace-muted)' }}
                             >
                               {t('common.cancel')}
                             </button>
                           </div>
                         </div>
                       ) : (
                         <>
                           <div className="flex items-center gap-2 font-bold mb-1" style={{ color: 'var(--ss-workspace-heading)' }}>
                             <FileText size={12} className="text-blue-500" />
                             {kb.title}
                           </div>
                           <p style={{ color: 'var(--ss-workspace-muted)' }} className="line-clamp-2">{kb.content}</p>
                           <div className="flex gap-2 absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                             <button
                               onClick={() => handleStartEdit(kb)}
                               className="hover:text-blue-500"
                               style={{ color: 'var(--ss-workspace-muted)' }}
                               title={t('components.agentPanel.edit')}
                             >
                               ✏️
                             </button>
                             <button
                               onClick={() => removeKnowledgeFromAgent(agent.id, kb.id)}
                               className="hover:text-red-500"
                               style={{ color: 'var(--ss-workspace-muted)' }}
                               title={t('components.agentPanel.delete')}
                             >
                               🗑️
                             </button>
                           </div>
                         </>
                       )}
                     </div>
                   );
                 })}

                 {isAddingKB ? (
                    <div className="border border-brand-200 rounded p-2 text-xs space-y-2" style={{ background: 'var(--ss-workspace-surface)' }}>
                       <input
                         type="text"
                         placeholder={t('components.agentPanel.titlePlaceholder')}
                         value={newKbTitle}
                         onChange={(e) => setNewKbTitle(e.target.value)}
                         className="w-full p-1 border rounded outline-none focus:ring-1 focus:ring-brand-500"
                       />
                       <textarea
                         placeholder={t('components.agentPanel.knowledgeContent')}
                         value={newKbContent}
                         onChange={(e) => setNewKbContent(e.target.value)}
                         className="w-full p-1 border rounded outline-none focus:ring-1 focus:ring-brand-500 h-16 resize-none"
                       />
                       <div className="flex gap-2">
                          <button onClick={handleAddKB} className="flex-1 py-1 bg-brand-600 text-white rounded hover:bg-brand-700">{t('components.agentPanel.save')}</button>
                          <button onClick={() => setIsAddingKB(false)} className="flex-1 py-1 rounded" style={{ background: 'var(--ss-surface-inset)', color: 'var(--ss-workspace-text)' }}>{t('common.cancel')}</button>
                       </div>
                    </div>
                 ) : (
                    <button
                       onClick={() => setIsAddingKB(true)}
                       className="w-full py-1.5 border border-dashed rounded text-xs flex items-center justify-center gap-1 transition-colors hover:border-brand-500 hover:text-brand-600"
                       style={{ borderColor: 'var(--ss-workspace-border)', color: 'var(--ss-workspace-muted)' }}
                    >
                       <Plus size={12} /> {t('components.agentPanel.addKnowledge')}
                    </button>
                 )}
              </div>
            )}
          </div>

          {/* Documents Section (Embedded RAG) */}
          <div className="mt-2 border-t" style={{ borderColor: 'var(--ss-workspace-border)' }}>
            <button
              onClick={handleDocsToggle}
              className="w-full flex items-center justify-between px-2 py-1.5 transition-colors rounded"
              style={{ background: 'var(--ss-surface-strong)' }}
            >
              <div className="flex items-center gap-2 text-xs font-semibold" style={{ color: 'var(--ss-workspace-heading)' }}>
                <Upload size={14} />
                <span>{t('components.agentPanel.documentKnowledgeBase')} ({documents.length})</span>
              </div>
              {isDocsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>

            {isDocsOpen && (
              <div className="p-3 space-y-3" style={{ background: 'var(--ss-surface-strong)' }}>
                <div
                  className={`border-2 border-dashed rounded-lg p-4 text-center transition-colors ${
                    isDragging
                      ? 'border-brand-500 bg-brand-50'
                      : 'hover:border-brand-400'
                  } ${isUploading ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                  style={!isDragging ? { borderColor: 'var(--ss-workspace-border)' } : undefined}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => !isUploading && fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.txt,.docx,.md"
                    onChange={handleFileInput}
                    className="hidden"
                    disabled={isUploading}
                  />
                  {isUploading ? (
                    <div className="flex items-center justify-center gap-2" style={{ color: 'var(--ss-workspace-muted)' }}>
                      <Loader2 size={16} className="animate-spin" />
                      <span className="text-xs">{t('components.agentPanel.uploading')}</span>
                    </div>
                  ) : (
                    <>
                      <Upload size={20} className="mx-auto mb-2" style={{ color: 'var(--ss-workspace-muted)' }} />
                      <p className="text-xs" style={{ color: 'var(--ss-workspace-muted)' }}>
                        {t('components.agentPanel.dragDropUpload')}
                      </p>
                      <p className="text-[10px] mt-1" style={{ color: 'var(--ss-workspace-muted)' }}>
                        {t('components.agentPanel.supportedFormats')}
                      </p>
                    </>
                  )}
                </div>

                {uploadError && (
                  <div className="bg-red-50 border border-red-200 rounded p-2 text-xs text-red-600">
                    {uploadError}
                  </div>
                )}

                {documents.length === 0 && !isUploading && (
                  <div className="text-center py-2 text-xs italic" style={{ color: 'var(--ss-workspace-muted)' }}>
                    {t('components.agentPanel.noUploadedDocs')}
                  </div>
                )}

                {documents.map(doc => (
                  <div key={doc.id} className="border rounded p-2 text-xs relative group" style={{ background: 'var(--ss-workspace-surface)' }}>
                    <div className="flex items-center gap-2 font-bold mb-1" style={{ color: 'var(--ss-workspace-heading)' }}>
                      <File size={12} className="text-blue-500" />
                      <span className="truncate flex-1">{doc.filename}</span>
                      <span className="font-normal" style={{ color: 'var(--ss-workspace-muted)' }}>{formatFileSize(doc.file_size)}</span>
                    </div>
                    <div className="flex items-center gap-2" style={{ color: 'var(--ss-workspace-muted)' }}>
                      <span>{doc.chunks_count} {t('components.agentPanel.textChunks')}</span>
                      <span>·</span>
                      <span>{new Date(doc.uploaded_at).toLocaleDateString()}</span>
                    </div>
                    <button
                      onClick={() => handleDeleteDocument(doc.id)}
                      className="absolute top-2 right-2 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                      style={{ color: 'var(--ss-workspace-muted)' }}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Collapsible Memory (#6) */}
          <div className="mt-2 border-t" style={{ borderColor: 'var(--ss-workspace-border)' }}>
            <button
              onClick={() => setIsMemoryOpen(!isMemoryOpen)}
              className="w-full flex items-center justify-between px-2 py-1.5 transition-colors rounded"
              style={{ background: 'var(--ss-surface-strong)' }}
            >
              <div className="flex items-center gap-2 text-xs font-semibold" style={{ color: 'var(--ss-workspace-heading)' }}>
                <Brain size={14} />
                <span>{t('components.agentPanel.shortTermMemory')} ({agent.memory.length})</span>
              </div>
              {isMemoryOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>

            {isMemoryOpen && (
              <div className="max-h-64 overflow-y-auto p-3 space-y-3" style={{ background: 'var(--ss-surface-strong)' }}>
                {agent.memory.map((mem) => (
                  <div key={mem.id} className="text-xs relative pl-3 border-l-2" style={{ borderColor: 'var(--ss-workspace-border)' }}>
                    <div className="flex justify-between mb-0.5" style={{ color: 'var(--ss-workspace-muted)' }}>
                      <span className="uppercase text-[10px] font-bold tracking-wider">{translateMemoryType(mem.type)}</span>
                      <span className="font-mono text-[10px]">{mem.timestamp}</span>
                    </div>
                    <p className={`leading-relaxed ${mem.type === 'thought' ? 'italic' : ''}`} style={{ color: mem.type === 'thought' ? 'var(--ss-workspace-muted)' : 'var(--ss-workspace-heading)' }}>
                      {mem.content}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
