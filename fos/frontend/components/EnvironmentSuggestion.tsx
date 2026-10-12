import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSimulationStore } from '../store';
import { type EnvironmentSuggestion } from '../services/environmentSuggestions';
import { Cloud, Loader2, X, CloudDrizzle, AlertTriangle, Megaphone, ToggleLeft, ToggleRight } from 'lucide-react';

const severityColors = {
  mild: 'bg-blue-50 text-blue-700 border-blue-200',
  moderate: 'bg-yellow-50 text-yellow-700 border-yellow-200',
  severe: 'bg-red-50 text-red-700 border-red-200',
};

const severityIcon = {
  mild: CloudDrizzle,
  moderate: Cloud,
  severe: AlertTriangle,
};

const eventTypeIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  weather: CloudDrizzle,
  emergency: AlertTriangle,
  notification: Megaphone,
  opinion: Cloud,
};

export const EnvironmentSuggestionIndicator: React.FC = () => {
  const { t } = useTranslation();
  const environmentSuggestionsAvailable = useSimulationStore((s) => s.environmentSuggestionsAvailable);
  const checkEnvironmentSuggestions = useSimulationStore((s) => s.checkEnvironmentSuggestions);
  const generateEnvironmentSuggestions = useSimulationStore((s) => s.generateEnvironmentSuggestions);
  const currentSimulation = useSimulationStore((s) => s.currentSimulation);
  const nodes = useSimulationStore((s) => s.nodes);
  const selectedNodeId = useSimulationStore((s) => s.selectedNodeId);

  React.useEffect(() => {
    // Check status when simulation loads or when nodes change (turns advance)
    if (currentSimulation) {
      checkEnvironmentSuggestions();
    }
  }, [currentSimulation?.id, nodes.length, selectedNodeId, checkEnvironmentSuggestions]);

  if (!environmentSuggestionsAvailable) return null;

  return (
    <div className="fixed bottom-4 right-4 z-40">
      <button
        onClick={generateEnvironmentSuggestions}
        className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg shadow-lg flex items-center gap-2 transition-colors"
      >
        <Cloud className="w-5 h-5" />
        <span>{t('components.environmentSuggestion.eventsAvailable')}</span>
      </button>
    </div>
  );
};

interface EnvironmentSuggestionDialogProps {
  onClose?: () => void;
}

export const EnvironmentSuggestionDialog: React.FC<EnvironmentSuggestionDialogProps> = ({ onClose }) => {
  const { t } = useTranslation();
  const environmentSuggestions = useSimulationStore((s) => s.environmentSuggestions);
  const environmentSuggestionsLoading = useSimulationStore((s) => s.environmentSuggestionsLoading);
  const applyEnvironmentSuggestion = useSimulationStore((s) => s.applyEnvironmentSuggestion);
  const dismissEnvironmentSuggestions = useSimulationStore((s) => s.dismissEnvironmentSuggestions);

  const handleApply = async (suggestion: EnvironmentSuggestion) => {
    await applyEnvironmentSuggestion(suggestion);
    onClose?.();
  };

  const handleDismiss = () => {
    dismissEnvironmentSuggestions();
    onClose?.();
  };

  if (environmentSuggestionsLoading) {
    return (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
        <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
          <div className="flex items-center justify-center py-8">
            <Loader2 className="animate-spin h-8 w-8 text-indigo-600" />
            <span className="ml-3 text-gray-600">{t('components.environmentSuggestion.generating')}</span>
          </div>
        </div>
      </div>
    );
  }

  if (environmentSuggestions.length === 0) {
    return null;
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-hidden flex flex-col">
        <div className="p-4 border-b flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">{t('components.environmentSuggestion.suggestionsTitle')}</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-500"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        <div className="p-4 overflow-y-auto flex-1">
          <p className="text-sm text-gray-600 mb-4">
            {t('components.environmentSuggestion.suggestionsDescription')}
          </p>

          <div className="space-y-3">
            {environmentSuggestions.map((suggestion, index) => {
              const IconComponent = eventTypeIcons[suggestion.event_type] || Cloud;
              const SeverityIcon = severityIcon[suggestion.severity as keyof typeof severityIcon] || Cloud;

              return (
                <div
                  key={index}
                  className={`border rounded-lg p-4 ${severityColors[suggestion.severity as keyof typeof severityColors]}`}
                >
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <IconComponent className="w-4 h-4" />
                      <span className="text-sm font-medium">
                        {t(`components.environmentSuggestion.eventType.${suggestion.event_type}`) || suggestion.event_type}
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      <SeverityIcon className="w-3 h-3" />
                      <span className="text-xs capitalize">
                        {t(`components.environmentSuggestion.severity.${suggestion.severity}`)}
                      </span>
                    </div>
                  </div>
                  <p className="text-gray-700">{suggestion.description}</p>

                  <div className="mt-3 flex gap-2">
                    <button
                      onClick={() => handleApply(suggestion)}
                      className="px-3 py-1 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 transition-colors"
                    >
                      {t('components.environmentSuggestion.apply')}
                    </button>
                    <button
                      onClick={handleDismiss}
                      className="px-3 py-1 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300 transition-colors"
                    >
                      {t('components.environmentSuggestion.skipAll')}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="p-4 border-t bg-gray-50">
          <button
            onClick={handleDismiss}
            className="w-full px-4 py-2 text-gray-700 hover:text-gray-900 transition-colors"
          >
            {t('components.environmentSuggestion.dismissAll')}
          </button>
        </div>
      </div>
    </div>
  );
};

export const EnvironmentSuggestionDialogWrapper: React.FC = () => {
  const environmentSuggestions = useSimulationStore((s) => s.environmentSuggestions);
  const [isDialogOpen, setIsDialogOpen] = React.useState(false);

  // Auto-open dialog when suggestions arrive
  React.useEffect(() => {
    if (environmentSuggestions.length > 0 && !isDialogOpen) {
      setIsDialogOpen(true);
    }
  }, [environmentSuggestions.length]);

  const handleCloseDialog = () => setIsDialogOpen(false);

  if (environmentSuggestions.length > 0 && isDialogOpen) {
    return <EnvironmentSuggestionDialog onClose={handleCloseDialog} />;
  }

  return <EnvironmentSuggestionIndicator />;
};

// Toggle button to enable/disable dynamic environment suggestions
export const EnvironmentToggleButton: React.FC<{ className?: string }> = ({ className = "" }) => {
  const { t } = useTranslation();
  const environmentEnabled = useSimulationStore((s) => s.environmentEnabled);
  const toggleEnvironmentEnabled = useSimulationStore((s) => s.toggleEnvironmentEnabled);

  return (
    <button
      onClick={() => toggleEnvironmentEnabled()}
      className={`flex items-center gap-2 px-3 py-1.5 rounded text-sm border transition-all ${
        environmentEnabled
          ? 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100'
          : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100'
      } ${className}`}
      title={environmentEnabled ? t('components.environmentSuggestion.toggle.disable') : t('components.environmentSuggestion.toggle.enable')}
    >
      {environmentEnabled ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
      <span>{t('components.environmentSuggestion.dynamicEvents')}</span>
    </button>
  );
};

export default EnvironmentSuggestionDialogWrapper;
