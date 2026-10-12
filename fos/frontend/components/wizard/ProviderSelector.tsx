/**
 * ProviderSelector component for SimulationWizard.
 *
 * Dropdown for selecting LLM provider for agent generation.
 *
 * Props:
 *   - providers: List of available LLM providers
 *   - selectedProviderId: ID of selected provider
 *   - onProviderChange: Callback when provider is changed
 *   - title: Title for the selector section
 *   - hint: Hint text below the title
 *   - noProviderOption: Text for no provider option
 *   - defaultProviderText: Default text when provider name is unavailable
 */

import React from 'react';
import { Bot } from 'lucide-react';

interface LLMProvider {
  id: string;
  name: string;
  provider?: string;
  model?: string;
  base_url?: string;
  is_active?: boolean;
  is_default?: boolean;
}

interface ProviderSelectorProps {
  providers: LLMProvider[];
  selectedProviderId: string | null;
  onProviderChange: (id: string | null) => void;
  title: string;
  hint: string;
  noProviderOption: string;
  defaultProviderText: string;
}

export const ProviderSelector: React.FC<ProviderSelectorProps> = ({
  providers,
  selectedProviderId,
  onProviderChange,
  title,
  hint,
  noProviderOption,
  defaultProviderText,
}) => {
  const getProviderLabel = (p: LLMProvider) => {
    const name = p.name || defaultProviderText;
    const model = p.model ? ` (${p.model})` : '';
    const baseUrl = p.base_url ? ` · ${p.base_url}` : '';
    // Show active/default status
    const status = [];
    if (p.is_active) status.push('Active');
    if (p.is_default) status.push('Default');
    const statusStr = status.length > 0 ? ` · ${status.join(', ')}` : '';
    return name + model + statusStr + baseUrl;
  };

  return (
    <div className="bg-indigo-50 border border-indigo-100 p-4 rounded-lg flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className="bg-indigo-100 p-2 rounded text-indigo-600">
          <Bot size={20} />
        </div>
        <div>
          <h3 className="text-sm font-bold text-indigo-900">{title}</h3>
          <p className="text-xs text-indigo-700">{hint}</p>
        </div>
      </div>

      <select
        value={selectedProviderId ?? ''}
        onChange={(e) => onProviderChange(e.target.value || null)}
        className="text-xs border-indigo-200 rounded px-2 py-1.5 focus:ring-indigo-500 min-w-[300px]"
      >
        {providers.length === 0 && (
          <option value="" disabled className="text-gray-400 italic">{noProviderOption}</option>
        )}
        {providers.map((p) => (
          <option
            key={p.id}
            value={p.id}
            className={selectedProviderId === p.id ? 'font-semibold text-indigo-900' : 'text-gray-700'}
          >
            {getProviderLabel(p)}
          </option>
        ))}
      </select>
    </div>
  );
};
