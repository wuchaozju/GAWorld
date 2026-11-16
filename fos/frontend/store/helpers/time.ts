import i18n from '../../i18n';
import type { TimeConfig, TimeUnit } from '../../types';

export const isZh = () => (i18n.language || 'en').toLowerCase().startsWith('zh');
export const getLocale = () => (isZh() ? 'zh-CN' : 'en-US');
export const pickText = (en: string, zh: string) => (isZh() ? zh : en);

export const addTime = (dateStr: string, value: number, unit: TimeUnit): string => {
  const date = new Date(dateStr);
  switch (unit) {
    case 'minute':
      date.setMinutes(date.getMinutes() + value);
      break;
    case 'hour':
      date.setHours(date.getHours() + value);
      break;
    case 'day':
      date.setDate(date.getDate() + value);
      break;
    case 'week':
      date.setDate(date.getDate() + value * 7);
      break;
    case 'month':
      date.setMonth(date.getMonth() + value);
      break;
    case 'year':
      date.setFullYear(date.getFullYear() + value);
      break;
  }
  return date.toISOString();
};

export const formatWorldTime = (isoString: string) => {
  const date = new Date(isoString);
  return date.toLocaleString(getLocale(), {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export const DEFAULT_TIME_CONFIG: TimeConfig = {
  baseTime: new Date().toISOString(),
  unit: 'hour',
  step: 1,
};
