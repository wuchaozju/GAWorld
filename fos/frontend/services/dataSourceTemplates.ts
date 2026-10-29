/**
 * Pre-built data source templates for common external APIs.
 * All user-facing text uses i18n keys resolved at render time.
 */

export interface DataSourceTemplate {
  id: string;
  /** i18n key for template name, e.g. "settings.dataSourceTemplate.yahooFinance.name" */
  nameKey: string;
  descriptionKey: string;
  hintKey?: string;
  icon: string;
  category: 'market' | 'news' | 'social' | 'crypto' | 'policy' | 'custom';
  defaults: {
    name: string;
    api_url: string;
    auth_type: 'none' | 'bearer' | 'api_key';
    auth_token?: string;
    poll_interval_seconds: number;
    event_type: 'market' | 'policy' | 'news' | 'custom';
    field_mapping: {
      title_path: string;
      content_path: string;
      timestamp_path: string;
      url_path: string;
      items_path?: string;
    };
  };
}

export const DATA_SOURCE_TEMPLATES: DataSourceTemplate[] = [
  // ── Market / Finance ──────────────────────────────────────────────
  {
    id: 'yahoo-finance',
    nameKey: 'settings.dataSourceTemplate.yahooFinance.name',
    descriptionKey: 'settings.dataSourceTemplate.yahooFinance.description',
    hintKey: 'settings.dataSourceTemplate.yahooFinance.hint',
    icon: '📈',
    category: 'market',
    defaults: {
      name: 'Yahoo Finance Market',
      api_url: 'https://query1.finance.yahoo.com/v1/finance/search?q=USDT&quotesQueryId=news',
      auth_type: 'none',
      poll_interval_seconds: 300,
      event_type: 'market',
      field_mapping: {
        items_path: 'quotes',
        title_path: 'shortName',
        content_path: 'longname',
        timestamp_path: 'quoteType',
        url_path: 'quoteType',
      },
    },
  },

  {
    id: 'alphavantage',
    nameKey: 'settings.dataSourceTemplate.alphavantage.name',
    descriptionKey: 'settings.dataSourceTemplate.alphavantage.description',
    hintKey: 'settings.dataSourceTemplate.alphavantage.hint',
    icon: '📊',
    category: 'market',
    defaults: {
      name: 'Alpha Vantage',
      api_url: 'https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=IBM&apikey=DEMO',
      auth_type: 'api_key',
      auth_token: '',
      poll_interval_seconds: 300,
      event_type: 'market',
      field_mapping: {
        items_path: '',
        title_path: '01. symbol',
        content_path: '01. symbol',
        timestamp_path: '07. latest trading day',
        url_path: '',
      },
    },
  },

  {
    id: 'coingecko',
    nameKey: 'settings.dataSourceTemplate.coingecko.name',
    descriptionKey: 'settings.dataSourceTemplate.coingecko.description',
    hintKey: 'settings.dataSourceTemplate.coingecko.hint',
    icon: '🪙',
    category: 'crypto',
    defaults: {
      name: 'CoinGecko Crypto',
      api_url: 'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc',
      auth_type: 'none',
      poll_interval_seconds: 120,
      event_type: 'market',
      field_mapping: {
        items_path: '',
        title_path: 'name',
        content_path: 'current_price',
        timestamp_path: 'last_updated',
        url_path: 'symbol',
      },
    },
  },

  // ── News ──────────────────────────────────────────────────────────
  {
    id: 'newsapi',
    nameKey: 'settings.dataSourceTemplate.newsapi.name',
    descriptionKey: 'settings.dataSourceTemplate.newsapi.description',
    hintKey: 'settings.dataSourceTemplate.newsapi.hint',
    icon: '📰',
    category: 'news',
    defaults: {
      name: 'NewsAPI Headlines',
      api_url: 'https://newsapi.org/v2/top-headlines?country=us&category=business&apiKey=DEMO_KEY',
      auth_type: 'api_key',
      auth_token: '',
      poll_interval_seconds: 600,
      event_type: 'news',
      field_mapping: {
        items_path: 'articles',
        title_path: 'title',
        content_path: 'description',
        timestamp_path: 'publishedAt',
        url_path: 'url',
      },
    },
  },

  {
    id: 'hackernews',
    nameKey: 'settings.dataSourceTemplate.hackernews.name',
    descriptionKey: 'settings.dataSourceTemplate.hackernews.description',
    hintKey: 'settings.dataSourceTemplate.hackernews.hint',
    icon: '💻',
    category: 'news',
    defaults: {
      name: 'Hacker News Top',
      api_url: 'https://hacker-news.firebaseio.com/v0/topstories.json',
      auth_type: 'none',
      poll_interval_seconds: 300,
      event_type: 'news',
      field_mapping: {
        items_path: '',
        title_path: 'title',
        content_path: 'score',
        timestamp_path: 'time',
        url_path: 'url',
      },
    },
  },

  // ── Social ─────────────────────────────────────────────────────────
  {
    id: 'reddit',
    nameKey: 'settings.dataSourceTemplate.reddit.name',
    descriptionKey: 'settings.dataSourceTemplate.reddit.description',
    hintKey: 'settings.dataSourceTemplate.reddit.hint',
    icon: '💬',
    category: 'social',
    defaults: {
      name: 'Reddit r/worldnews',
      api_url: 'https://www.reddit.com/r/worldnews/hot.json?limit=10',
      auth_type: 'none',
      poll_interval_seconds: 600,
      event_type: 'news',
      field_mapping: {
        items_path: 'data.children',
        title_path: 'data.title',
        content_path: 'data.selftext',
        timestamp_path: 'data.created_utc',
        url_path: 'data.url',
      },
    },
  },

  // ── Policy ─────────────────────────────────────────────────────────
  {
    id: 'gov.cn',
    nameKey: 'settings.dataSourceTemplate.govcn.name',
    descriptionKey: 'settings.dataSourceTemplate.govcn.description',
    hintKey: 'settings.dataSourceTemplate.govcn.hint',
    icon: '🏛️',
    category: 'policy',
    defaults: {
      name: '中国政府网公告',
      api_url: 'http://www.gov.cn/fore_1/api/news/list?page=1&pageSize=10',
      auth_type: 'none',
      poll_interval_seconds: 900,
      event_type: 'policy',
      field_mapping: {
        items_path: 'data',
        title_path: 'title',
        content_path: 'description',
        timestamp_path: 'pubDate',
        url_path: 'url',
      },
    },
  },

  // ── Custom / Webhook ──────────────────────────────────────────────
  {
    id: 'webhook-generic',
    nameKey: 'settings.dataSourceTemplate.webhook.name',
    descriptionKey: 'settings.dataSourceTemplate.webhook.description',
    hintKey: 'settings.dataSourceTemplate.webhook.hint',
    icon: '🔗',
    category: 'custom',
    defaults: {
      name: 'Webhook 数据源',
      api_url: 'https://your-server.com/events/api',
      auth_type: 'bearer',
      auth_token: 'your-webhook-secret-token',
      poll_interval_seconds: 0,
      event_type: 'custom',
      field_mapping: {
        title_path: 'title',
        content_path: 'content',
        timestamp_path: 'timestamp',
        url_path: 'url',
      },
    },
  },
];

export const TEMPLATE_CATEGORIES = [
  { id: 'market', labelKey: 'settings.dataSourceTemplate.category.market' },
  { id: 'news', labelKey: 'settings.dataSourceTemplate.category.news' },
  { id: 'social', labelKey: 'settings.dataSourceTemplate.category.social' },
  { id: 'crypto', labelKey: 'settings.dataSourceTemplate.category.crypto' },
  { id: 'policy', labelKey: 'settings.dataSourceTemplate.category.policy' },
  { id: 'custom', labelKey: 'settings.dataSourceTemplate.category.custom' },
] as const;