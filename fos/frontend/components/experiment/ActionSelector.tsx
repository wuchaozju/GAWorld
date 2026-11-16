/**
 * Action Selector Component
 *
 * A reusable dropdown component for selecting actions from the structured list.
 * Displays selected actions as removable chips and provides a dropdown
 * for selecting from available action types.
 */

import React, { useEffect, useState } from 'react';
import { Check, ChevronDown, X } from 'lucide-react';
import { fetchAvailableActionTypes, ActionType } from '../../services/experiment-templates';
import { useTranslation } from 'react-i18next';

interface ActionSelectorProps {
  /** Currently selected action values */
  selectedActions: string[];
  /** Callback when selection changes */
  onSelectionChange: (actions: string[]) => void;
  /** Maximum number of actions that can be selected */
  maxActions?: number;
  /** Whether the selector is disabled */
  disabled?: boolean;
  /** Label for the selector */
  label?: string;
}

export const ActionSelector: React.FC<ActionSelectorProps> = ({
  selectedActions,
  onSelectionChange,
  maxActions = 10,
  disabled = false,
  label,
}) => {
  const { t } = useTranslation();
  const [availableActions, setAvailableActions] = useState<ActionType[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const dropdownRef = React.useRef<HTMLDivElement>(null);

  // Default label uses translation
  const displayLabel = label || t('experiment.actionSelector.availableLabel');

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Fetch available actions on mount
  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchAvailableActionTypes()
      .then(data => {
        setAvailableActions(data.actions);
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load action types:', err);
        setError(t('experiment.actionSelector.loadError'));
        setLoading(false);
        // Set fallback actions so the component still works
        setAvailableActions([
          { value: 'cooperate', label: t('experiment.actionSelector.fallbackCooperate'), description: t('experiment.actionSelector.fallbackCooperateDesc') },
          { value: 'defect', label: t('experiment.actionSelector.fallbackDefect'), description: t('experiment.actionSelector.fallbackDefectDesc') },
        ]);
      });
  }, []);

  const toggleAction = (actionValue: string) => {
    const isSelected = selectedActions.includes(actionValue);
    let newSelection: string[];

    if (isSelected) {
      newSelection = selectedActions.filter(a => a !== actionValue);
    } else if (selectedActions.length < maxActions) {
      newSelection = [...selectedActions, actionValue];
    } else {
      return; // Max reached
    }

    onSelectionChange(newSelection);
  };

  const removeAction = (actionValue: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const newSelection = selectedActions.filter(a => a !== actionValue);
    onSelectionChange(newSelection);
  };

  const getActionLabel = (value: string): string => {
    const option = availableActions.find(a => a.value === value);
    return option?.label || value;
  };

  return (
    <div className="space-y-2">
      {displayLabel && (
        <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-text)' }}>
          {displayLabel}
        </label>
      )}

      {/* Selected Actions Display */}
      <div className="flex flex-wrap gap-2 p-3 border rounded-md min-h-[60px]" style={{ background: 'var(--ss-page-surface-muted)', borderColor: 'var(--ss-border-strong)' }}>
        {selectedActions.length === 0 ? (
          <span className="text-sm" style={{ color: 'var(--ss-text-muted)' }}>
            {loading ? t('experiment.actionSelector.loading') : t('experiment.actionSelector.selectPrompt')}
          </span>
        ) : (
          selectedActions.map(action => (
            <span
              key={action}
              className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm font-medium"
              style={{ background: 'var(--ss-accent-warm-soft)', color: 'var(--ss-text)' }}
            >
              {getActionLabel(action)}
              <button
                onClick={(e) => removeAction(action, e)}
                className="ml-1 disabled:opacity-50" style={{ color: 'var(--ss-brand-primary)' }}
                disabled={disabled}
                type="button"
              >
                <X size={14} />
              </button>
            </span>
          ))
        )}
      </div>

      {error && (
        <div className="text-xs" style={{ color: 'var(--ss-warning)' }}>
          {error} - {t('experiment.actionSelector.fallbackWarning')}
        </div>
      )}

      {/* Available Actions Dropdown */}
      <div className="relative" ref={dropdownRef}>
        <button
          onClick={() => !disabled && setIsOpen(!isOpen)}
          disabled={disabled}
          type="button"
          className="w-full flex items-center justify-between px-3 py-2 border rounded-md text-left disabled:cursor-not-allowed transition-colors"
          style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
        >
          <span className="text-sm" style={{ color: 'var(--ss-text)' }}>
            {loading ? t('experiment.actionSelector.loading') : isOpen ? t('experiment.actionSelector.selectAction') : t('experiment.actionSelector.addAction', { count: selectedActions.length, max: maxActions })}
          </span>
          <ChevronDown className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`} style={{ color: 'var(--ss-text-subtle)' }} />
        </button>

        {isOpen && !disabled && (
          <div className="absolute z-10 w-full mt-1 border rounded-md shadow-lg max-h-60 overflow-auto" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}>
            {availableActions.length === 0 ? (
              <div className="px-3 py-2 text-sm" style={{ color: 'var(--ss-text-subtle)' }}>
                {t('experiment.actionSelector.noneAvailable')}
              </div>
            ) : (
              availableActions.map(action => {
                const isSelected = selectedActions.includes(action.value);
                const isDisabled = !isSelected && selectedActions.length >= maxActions;

                return (
                  <button
                    key={action.value}
                    onClick={() => !isDisabled && toggleAction(action.value)}
                    disabled={isDisabled}
                    type="button"
                    className={`w-full text-left px-3 py-2 flex items-start gap-2 transition-colors ${
                      isDisabled
                        ? 'cursor-not-allowed'
                        : ''
                    }`}
                    style={{
                      background: isSelected ? 'var(--ss-page-surface-muted)' : isDisabled ? 'var(--ss-page-surface-muted)' : undefined,
                      color: isSelected ? 'var(--ss-success)' : isDisabled ? 'var(--ss-text-subtle)' : 'var(--ss-heading)',
                    }}
                  >
                    <span className="flex-1">
                      <div className={`font-medium text-sm`}>
                        {action.label}
                      </div>
                      <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>
                        {action.description}
                      </div>
                    </span>
                    {isSelected && (
                      <Check className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: 'var(--ss-success)' }} />
                    )}
                  </button>
                );
              })
            )}
          </div>
        )}
      </div>

      {/* Max actions hint */}
      {selectedActions.length >= maxActions && (
        <div className="text-xs" style={{ color: 'var(--ss-warning)' }}>
          {t('experimentBuilder.actionSelector.maxSelected', { max: maxActions })}
        </div>
      )}
    </div>
  );
};
