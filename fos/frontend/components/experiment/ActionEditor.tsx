/**
 * Action editor component for configurable scenario actions.
 *
 * Renders editable fields for action name and description pairs.
 * Used by matrix games (Battle of the Sexes, Stag Hunt) to allow
 * researchers to customize action labels for their experiments.
 *
 * Exports: ActionEditor (default)
 */

import React from 'react';
import { useTranslation } from 'react-i18next';

interface ActionConfig {
  id: string;
  nameParam: string;
  descParam: string;
  defaultName: string;
  defaultDesc: string;
}

interface ActionEditorProps {
  actions: ActionConfig[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
}

export const ActionEditor: React.FC<ActionEditorProps> = ({
  actions,
  values,
  onChange,
}) => {
  const { t } = useTranslation();

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-medium text-gray-700">
        {t('experimentBuilder.actionEditor.title')}
      </h3>

      {actions.map((action, index) => (
        <div key={action.id} className="border border-gray-200 rounded-lg p-4">
          <h4 className="font-medium text-gray-800 mb-3">
            {t('experimentBuilder.actionEditor.actionNumber', { number: index + 1 })}
          </h4>

          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t('experimentBuilder.actionEditor.nameLabel')}
              </label>
              <input
                type="text"
                value={values[action.nameParam] || action.defaultName}
                onChange={(e) => onChange(action.nameParam, e.target.value)}
                placeholder={t('experimentBuilder.actionEditor.namePlaceholder')}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t('experimentBuilder.actionEditor.descriptionLabel')}
              </label>
              <input
                type="text"
                value={values[action.descParam] || action.defaultDesc}
                onChange={(e) => onChange(action.descParam, e.target.value)}
                placeholder={t('experimentBuilder.actionEditor.descriptionPlaceholder')}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};

export default ActionEditor;
