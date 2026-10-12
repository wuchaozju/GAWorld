
import React from 'react';
import { useSimulationStore } from '../store';
import { CheckCircle, AlertCircle, Info, X } from 'lucide-react';

export const ToastContainer: React.FC = () => {
  const notifications = useSimulationStore(state => state.notifications);
  const removeNotification = useSimulationStore(state => state.removeNotification);

  if (notifications.length === 0) return null;

  return (
    <div className="fixed top-16 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
      {notifications.map(n => (
        <div 
          key={n.id}
          className={`pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg border animate-in slide-in-from-right-full duration-300 ${
            n.type === 'success' ? 'bg-white border-green-200 text-green-800' :
            n.type === 'error' ? 'bg-white border-red-200 text-red-800' :
            'bg-white border-blue-200 text-blue-800'
          }`}
        >
          {n.type === 'success' && <CheckCircle size={18} className="text-green-600" />}
          {n.type === 'error' && <AlertCircle size={18} className="text-red-600" />}
          {n.type === 'info' && <Info size={18} className="text-blue-600" />}
          
          <span className="text-sm font-medium">{n.message}</span>
          
          <button 
            onClick={() => removeNotification(n.id)}
            className="ml-2 text-slate-400 hover:text-slate-600"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
};
