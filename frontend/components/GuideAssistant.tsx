/**
 * This file shows the built-in helper chat for the app.
 *
 * GuideAssistant lets people ask for help, upload an image into the chat,
 * and open the right part of the app from suggested actions.
 */

import React, { useRef, useEffect, useState, useMemo } from 'react';
import { useSimulationStore } from '../store';
import { useTranslation } from 'react-i18next';
import { MessageSquare, X, Send, Sparkles, Loader2, ArrowRight } from 'lucide-react';
import { GuideActionType } from '../types';
import { uploadImage } from '../services/uploads';

const extractMarkdownImages = (text: string): string[] => {
   const matches = Array.from(text.matchAll(/!\[[^\]]*\]\(([^)]+)\)/g));
   return matches.map((m) => m[1]).filter(Boolean);
};

export const GuideAssistant: React.FC = () => {
  const { t } = useTranslation();
  const isOpen = useSimulationStore(state => state.isGuideOpen);
  const toggle = useSimulationStore(state => state.toggleGuide);
  const messages = useSimulationStore(state => state.guideMessages);
  const isGuideLoading = useSimulationStore(state => state.isGuideLoading);
  const sendGuideMessage = useSimulationStore(state => state.sendGuideMessage);
  
  // UI Triggers
  const toggleWizard = useSimulationStore(state => state.toggleWizard);
  const toggleNetworkEditor = useSimulationStore(state => state.toggleNetworkEditor);
  const toggleExperimentDesigner = useSimulationStore(state => state.toggleExperimentDesigner);
  const toggleExport = useSimulationStore(state => state.toggleExport);
  const toggleAnalytics = useSimulationStore(state => state.toggleAnalytics);
  const setActiveTab = useSimulationStore(state => state.setActiveTab);
   const addNotification = useSimulationStore(state => state.addNotification);

  const [input, setInput] = useState('');
   const [isUploadingImage, setIsUploadingImage] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
   const fileInputRef = useRef<HTMLInputElement>(null);

   const imageUrls = useMemo(() => extractMarkdownImages(input), [input]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isOpen]);

  const handleSend = () => {
    if (!input.trim() || isGuideLoading) return;
    sendGuideMessage(input);
    setInput('');
  };

   const handleEmbedImage = async (file: File | null) => {
      if (!file) return;
      setIsUploadingImage(true);
      try {
         const asset = await uploadImage(file);
         setInput((prev) => `${prev}${prev ? '\n' : ''}![image](${asset.url})`);
         addNotification('success', t('components.guideAssistant.uploadSuccess'));
      } catch (err) {
         const message = err instanceof Error ? err.message : t('components.guideAssistant.uploadFailed');
         addNotification('error', message);
      } finally {
         setIsUploadingImage(false);
         if (fileInputRef.current) fileInputRef.current.value = '';
      }
   };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const executeAction = (action: GuideActionType) => {
     switch(action) {
        case 'OPEN_WIZARD': toggleWizard(true); break;
        case 'OPEN_NETWORK': toggleNetworkEditor(true); break;
        case 'OPEN_EXPERIMENT':
           setActiveTab('intervention');
           toggleExperimentDesigner(true);
           break;
        case 'OPEN_EXPORT': toggleExport(true); break;
        case 'OPEN_ANALYTICS': toggleAnalytics(true); break;
        case 'OPEN_HOST': setActiveTab('intervention'); break;
     }
  };

  const getActionLabel = (action: GuideActionType) => {
     switch(action) {
        case 'OPEN_WIZARD': return t('components.guideAssistant.openWizard');
        case 'OPEN_NETWORK': return t('components.guideAssistant.openNetwork');
        case 'OPEN_EXPERIMENT': return t('components.guideAssistant.openExperiment');
        case 'OPEN_EXPORT': return t('components.guideAssistant.openExport');
        case 'OPEN_ANALYTICS': return t('components.guideAssistant.openAnalytics');
        case 'OPEN_HOST': return t('components.guideAssistant.openHost');
        default: return t('components.guideAssistant.executeAction');
     }
  };

  if (!isOpen) {
    return (
      <button 
        onClick={() => toggle(true)}
        className="fixed bottom-6 right-6 z-40 w-12 h-12 bg-indigo-600 hover:bg-indigo-700 text-white rounded-full shadow-lg flex items-center justify-center transition-transform hover:scale-110 active:scale-95 group"
      >
        <Sparkles size={20} className="group-hover:animate-pulse" />
      </button>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-40 w-96 h-[500px] bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden border border-slate-200 animate-in slide-in-from-bottom-10 fade-in duration-300">
      
      {/* Header */}
      <div className="bg-indigo-600 p-4 flex justify-between items-center text-white shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles size={18} />
          <h3 className="font-bold text-sm">{t('components.guideAssistant.title')}</h3>
        </div>
        <button onClick={() => toggle(false)} className="text-indigo-200 hover:text-white transition-colors">
          <X size={18} />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-50" ref={scrollRef}>
        {messages.map(msg => (
          <div key={msg.id} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
            <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
               msg.role === 'user' 
                  ? 'bg-indigo-600 text-white rounded-br-none' 
                  : 'bg-white text-slate-700 border border-slate-100 rounded-bl-none'
            }`}>
               <div className="whitespace-pre-wrap">{msg.content}</div>
            </div>
            
            {/* Action Chips (#15 Workflow) */}
            {msg.suggestedActions && msg.suggestedActions.length > 0 && (
               <div className="mt-2 flex flex-wrap gap-2">
                  {msg.suggestedActions.map(action => (
                     <button 
                        key={action}
                        onClick={() => executeAction(action)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-xs font-bold rounded-full border border-indigo-200 transition-colors"
                     >
                        {getActionLabel(action)}
                        <ArrowRight size={12} />
                     </button>
                  ))}
               </div>
            )}
          </div>
        ))}
        {isGuideLoading && (
           <div className="flex justify-start">
              <div className="bg-white px-4 py-3 rounded-2xl rounded-bl-none border shadow-sm">
                 <Loader2 size={16} className="animate-spin text-indigo-500" />
              </div>
           </div>
        )}
      </div>

      {/* Input */}
      <div className="p-3 bg-white border-t shrink-0">
         <div className="relative">
            <input
               type="text"
               value={input}
               onChange={(e) => setInput(e.target.value)}
               onKeyDown={handleKeyPress}
               placeholder={t('components.guideAssistant.placeholder')}
               className="w-full pl-4 pr-20 py-3 bg-slate-100 border-transparent focus:bg-white focus:ring-2 focus:ring-indigo-500 rounded-xl text-sm outline-none transition-all"
               autoFocus
            />
            <div className="absolute right-2 top-2 flex items-center gap-1">
              <input
                type="file"
                ref={fileInputRef}
                accept="image/*"
                className="hidden"
                onChange={(e) => handleEmbedImage(e.target.files?.[0] ?? null)}
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploadingImage}
                className="p-1.5 text-indigo-500 hover:bg-indigo-50 rounded-lg disabled:opacity-50"
                title={t('components.guideAssistant.insertImage')}
              >
                {isUploadingImage ? <Loader2 size={16} className="animate-spin" /> : <MessageSquare size={16} />}
              </button>
              <button
                 onClick={handleSend}
                 disabled={!input.trim() || isGuideLoading}
                 className="p-1.5 text-indigo-600 hover:bg-indigo-50 rounded-lg disabled:opacity-50 disabled:hover:bg-transparent"
              >
                 <Send size={18} />
              </button>
            </div>
         </div>
         {imageUrls.length > 0 && (
           <div className="mt-2 flex flex-wrap gap-2">
             {imageUrls.map((url) => (
               <div key={url} className="w-14 h-14 border rounded overflow-hidden bg-slate-50">
                 <img src={url} alt="preview" className="w-full h-full object-cover" />
               </div>
             ))}
           </div>
         )}
         <p className="text-[10px] text-center text-slate-400 mt-2">
            {t('components.guideAssistant.disclaimer')}
         </p>
      </div>
    </div>
  );
};
