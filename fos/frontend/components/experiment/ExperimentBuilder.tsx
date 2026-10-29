/**
 * Main Experiment Builder Component
 *
 * 6-step wizard for creating social science experiments:
 * 1. Select interaction patterns
 * 2. Choose starter template (optional)
 * 3. Configure scenario and mechanics
 * 4. Design agents
 * 5. Configure network
 * 6. Set structure, conditions, and review
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { useExperimentBuilder, STEPS } from '../../store/experiment-builder';
import { ProgressBar } from '../ui/progress-bar';
import { Button } from '../ui/button';
import { Card } from '../ui/card';
// Step components
import { Step1InteractionType } from './Step1InteractionType';
import { Step2StarterTemplate } from './Step2StarterTemplate';
import { Step3Scenario } from './Step3Scenario';
import { Step4Agents } from './Step4Agents';
import { Step5Network } from './Step5Network';
import { Step6Structure } from './Step6Structure';
import type { SocialNetwork } from '../../types';
import type { ExperimentBuilderState } from '../../store/experiment-builder';

export type ExperimentBuilderSubmission = ExperimentBuilderState & {
  socialNetwork: SocialNetwork;
};

interface ExperimentBuilderProps {
  onComplete?: (config: ExperimentBuilderSubmission) => void;
  onCancel?: () => void;
  onBackFromStep2?: () => void;
}

export const ExperimentBuilder: React.FC<ExperimentBuilderProps> = ({
  onComplete,
  onCancel,
  onBackFromStep2,
}) => {
  const { t } = useTranslation();
  const {
    currentStep,
    completedSteps,
    selectedScenarioId,
    scenarioDescription,
    selectedActionIds,
    agentTypes,
    socialNetwork,
    nextStep,
    prevStep,
  } = useExperimentBuilder();

  const handleNext = () => {
    if (!canProceed()) return;
    nextStep();
  };

  const handleBack = () => {
    if (currentStep === 2 && onBackFromStep2) {
      onBackFromStep2();
      return;
    }
    prevStep();
  };

  const handleComplete = () => {
    const state = useExperimentBuilder.getState();
    onComplete?.({
      ...state,
      socialNetwork, // Include network in config
    });
  };

  const canProceed = () => {
    // Step-specific validation
    switch (currentStep) {
      case 1:
        return selectedScenarioId !== null;
      case 2:
        return scenarioDescription.trim() !== '';
      case 3:
        return selectedActionIds.length >= 1;
      case 4:
        // Total agent count >= 1
        const totalAgents = agentTypes.reduce((sum, type) => sum + (type.count || 0), 0);
        return totalAgents >= 1;
      case 5:
        // Network step - optional, can proceed even without connections
        return true;
      case 6:
        return true; // Review page - always allowed
      default:
        return false;
    }
  };

  const canGoBack = () => currentStep > 1;

  const isLastStep = currentStep === 6;

  // Scroll to top when step changes (previous step may leave page scrolled)
  React.useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [currentStep]);

  return (
    <div className={`mx-auto p-6 ${currentStep === 5 ? 'max-w-full' : 'max-w-4xl'}`}>
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold" style={{ color: 'var(--ss-heading)' }}>
          {t('experimentBuilder.title')}
        </h1>
        <p className="mt-1" style={{ color: 'var(--ss-text-muted)' }}>
          {t('experimentBuilder.subtitle')}
        </p>
      </div>

      {/* Progress */}
      <div className="mb-8">
        <ProgressBar
          current={currentStep}
          total={6}
          completed={Array.from(completedSteps)}
          steps={STEPS}
        />
      </div>

      {/* Step Content */}
      <Card className={`mb-6 ${currentStep === 5 ? 'p-0' : 'p-6'}`}>
        {currentStep === 1 && (
          <Step1InteractionType />
        )}
        {currentStep === 2 && (
          <Step2StarterTemplate />
        )}
        {currentStep === 3 && (
          <Step3Scenario />
        )}
        {currentStep === 4 && (
          <Step4Agents />
        )}
        {currentStep === 5 && (
          <Step5Network />
        )}
        {currentStep === 6 && (
          <Step6Structure />
        )}
      </Card>

      {/* Navigation */}
      <div className="flex justify-between mt-6">
        <div>
          {canGoBack() && (
            <Button variant="outline" onClick={handleBack}>
              {t('experimentBuilder.back')}
            </Button>
          )}
        </div>

        <div className="flex gap-2">
          <Button variant="outline" onClick={onCancel}>
            {t('experimentBuilder.cancel')}
          </Button>

          {currentStep < 6 ? (
            <Button onClick={handleNext} disabled={!canProceed()}>
              {t('experimentBuilder.next')} →
            </Button>
          ) : (
            <Button onClick={handleComplete} variant="default">
              {t('experimentBuilder.create')}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};

export default ExperimentBuilder;
