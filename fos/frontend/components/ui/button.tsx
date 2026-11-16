/**
 * Button UI Component
 *
 * Reusable button component with variants for different visual styles.
 */

import React from 'react';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline' | 'ghost' | 'destructive';
  size?: 'sm' | 'md' | 'lg';
  children: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'default',
  size = 'md',
  className = '',
  children,
  ...props
}) => {
  const baseClasses =
    'inline-flex items-center justify-center gap-2 rounded-full font-medium tracking-[0.01em] whitespace-nowrap transition-all focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none';

  const variantClasses = {
    default:
      'bg-[var(--ss-brand-primary)] text-[var(--ss-brand-on)] shadow-[0_16px_40px_rgba(212,162,78,0.16)] hover:-translate-y-0.5 hover:brightness-110 focus:ring-[var(--ss-brand-primary)]',
    outline:
      'border border-[var(--ss-border)] bg-[var(--ss-surface)] text-[var(--ss-text)] hover:-translate-y-0.5 hover:border-[var(--ss-border-strong)] focus:ring-[var(--ss-border-strong)]',
    ghost:
      'bg-transparent text-[var(--ss-text-muted)] hover:bg-[var(--ss-surface-muted)] hover:text-[var(--ss-text)] focus:ring-[var(--ss-border)]',
    destructive:
      'bg-[var(--ss-danger)] text-white shadow-[0_14px_32px_rgba(196,96,90,0.18)] hover:-translate-y-0.5 hover:brightness-110 focus:ring-[var(--ss-danger)]',
  };

  const sizeClasses = {
    sm: 'px-5 py-2 text-sm',
    md: 'px-6 py-2.5 text-sm',
    lg: 'px-8 py-3 text-base',
  };

  return (
    <button
      className={`${baseClasses} ${variantClasses[variant]} ${sizeClasses[size]} ${className}`.trim()}
      {...props}
    >
      {children}
    </button>
  );
};

export default Button;
