/**
 * Card UI Component
 *
 * Reusable card component for containing content with consistent styling.
 */

import React from 'react';

export interface CardProps {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

export const Card: React.FC<CardProps> = ({ children, className = '', style }) => {
  return (
    <div className={`lab-surface overflow-hidden ${className}`.trim()} style={style}>
      {children}
    </div>
  );
};

export interface CardHeaderProps {
  children: React.ReactNode;
  className?: string;
}

export const CardHeader: React.FC<CardHeaderProps> = ({ children, className = '' }) => {
  return (
    <div className={`border-b border-[var(--ss-border)] px-6 py-5 ${className}`.trim()}>
      {children}
    </div>
  );
};

export interface CardContentProps {
  children: React.ReactNode;
  className?: string;
}

export const CardContent: React.FC<CardContentProps> = ({ children, className = '' }) => {
  return (
    <div className={`p-6 ${className}`.trim()}>
      {children}
    </div>
  );
};

export interface CardTitleProps {
  children: React.ReactNode;
  className?: string;
}

export const CardTitle: React.FC<CardTitleProps> = ({ children, className = '' }) => {
  return (
    <h3 className={`font-[var(--font-display)] text-xl font-semibold tracking-[-0.03em] text-[var(--ss-heading)] ${className}`.trim()}>
      {children}
    </h3>
  );
};

export default Card;
