

export interface SimNode {
  id: string;
  display_id: string; // #5 新增层级化 ID (如 0.1.2)
  parentId: string | null;
  name: string;
  depth: number;
  isLeaf: boolean;
  status: 'completed' | 'running' | 'failed' | 'pending';
  timestamp: string; // System timestamp of creation
  worldTime: string; // #9 Simulated world time (ISO string)
  meta?: Record<string, any> | null;
}

export interface LLMConfig {
  provider: string;
  model: string;
}

export interface UploadedAsset {
  url: string;
  filename: string;
  size: number;
  content_type: string;
  extracted_text?: string | null;
  extracted_title?: string | null;
  extracted_abstract?: string | null;
  extraction_method?: string | null;
  extraction_warnings?: string[];
  page_count?: number | null;
  extracted_figure_captions?: string[];
  extracted_table_captions?: string[];
  extracted_document_quality?: {
    section_count?: number;
    has_title?: boolean;
    has_abstract?: boolean;
    has_references?: boolean;
    ocr_used?: boolean;
    strong_extraction?: boolean;
    average_page_quality?: number;
    warnings?: string[];
    char_count?: number;
  } | null;
  extracted_pages?: Array<{
    page_number: number;
    text: string;
    method: string;
    char_count: number;
  }>;
  extracted_sections?: Array<{
    id: string;
    title: string;
    excerpt: string;
    page?: number | null;
  }>;
}

export interface EngineConfig {
  endpoint: string; // e.g., "http://localhost:8000/api"
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  latency?: number;
  token?: string;
}

// #23 RAG Knowledge Base Item
export interface KnowledgeItem {
  id: string;
  title: string;
  type?: 'text' | 'file' | 'url';
  content: string; // Text content or URL
  enabled?: boolean;
  timestamp?: string;
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  avatarUrl: string;
  profile: string; // 静态画像描述
  llmConfig: LLMConfig; // #10 LLM 配置
  provider_id?: number;
  properties: Record<string, any>; // 动态属性 (如信任值, 压力值)
  // #14 新增历史数据用于趋势分析
  history: Record<string, number[]>; // key: property name, value: array of values per round
  memory: MemoryItem[];
  knowledgeBase: KnowledgeItem[]; // #23 动态知识库
}

export interface MemoryItem {
  id: string;
  round: number;
  content: string;
  type: 'dialogue' | 'observation' | 'thought';
  timestamp: string;
}

export interface LogEntry {
  id: string;
  nodeId: string;
  type: 'SYSTEM' | 'AGENT_ACTION' | 'AGENT_SAY' | 'ENVIRONMENT' | 'HOST_INTERVENTION' | 'AGENT_METADATA';
  agentId?: string;
  content: string;
  actionLabel?: string;
  outcome?: Record<string, number>; // numeric results from this event (e.g. payoff, amount)
  structuredData?: {
    kind: 'policy_diff';
    title: string;
    agentLabel?: string;
    leftTitle: string;
    leftContent: string;
    draftTitle?: string;
    draftContent?: string;
    rightTitle: string;
    rightContent: string;
    reasonLabel: string;
    reason: string;
    metricsLabel: string;
    metrics: string;
  };
  imageUrl?: string; // #24 Multimodal Content
  imageAlt?: string; // Alt text for accessibility
  audioUrl?: string;
  videoUrl?: string;
  timestamp: string;
  round: number;
}

export interface InitialEventItem {
  id: string;
  title: string;
  content: string;
  imageUrl?: string;
  imageAlt?: string; // Alt text for accessibility
  audioUrl?: string;
  videoUrl?: string;
}

// #9 Time Configuration
export type TimeUnit = 'minute' | 'hour' | 'day' | 'week' | 'month' | 'year';

export interface TimeConfig {
  baseTime: string; // ISO string start time
  unit: TimeUnit;
  step: number;
}

// #22 Social Network Topology
// Adjacency List: agentId -> array of agentIds they can send messages to
export type SocialNetwork = Record<string, string[]>;

// #14 Simulation Report
export interface SimulationReport {
  id: string;
  generatedAt: string;
  refinedByLLM?: boolean;
  summary: string;
  keyEvents: { round: number; description: string }[];
  agentAnalysis: { agentName: string; analysis: string }[];
  suggestions: string[];
  roundStats?: { round: number; actions: number; errors: number; broadcasts: number }[];
  benchmarkComparison?: {
    armId: string;
    armLabel: string;
    sampleSize: number;
    items: {
      key: string;
      label: string;
      benchmarkMean: number;
      simulatedValue: number;
      delta: number;
      interpretation: string;
    }[];
    possibleDrivers: string[];
  };
}

// #20 Template System
export interface SimulationTemplate {
  id: string;
  name: string;
  description: string;
  category: 'system' | 'custom';
  sceneType: string; // underlying hardcoded logic type (village, council, etc., or 'generic' for custom templates)
  agents: Agent[]; // Pre-configured agents
  defaultTimeConfig: TimeConfig;
  defaultNetwork?: SocialNetwork; // #22
  socialNetwork?: SocialNetwork;
  genericConfig?: GenericTemplateConfig; // For custom templates built with TemplateBuilder
}

export type Template = SimulationTemplate;

export interface Simulation {
  id: string;
  name: string; // #7 自定义实验名称
  templateId: string;
  scene_type?: string;
  status: 'active' | 'archived';
  createdAt: string;
  timeConfig: TimeConfig; // #9
  socialNetwork: SocialNetwork; // #22
  report?: SimulationReport; // #14
  scene_config?: Record<string, any>; // Dynamic environment config
}

export enum ViewMode {
  LIST = 'LIST',
  CARD = 'CARD',
  TIMELINE = 'TIMELINE'
}

// #18 Parallel Experiment Types
export type InterventionType =
  | 'INSTRUCTION'
  | 'ENVIRONMENT'
  | 'AGENT_PROPERTY'
  | 'FOLLOW_UP_CONDITION'
  | 'FOLLOW_UP_THREAD_SEED'
  | 'SCENARIO_PARAMS'
  | 'NETWORK_TOPOLOGY';

// Network topology types (inline to avoid circular deps)
export type NetworkPreset =
  | 'full' | 'random' | 'ring' | 'star'
  | 'newman-watts' | 'core-periphery' | 'holme-kim' | 'waxman' | 'sbm'
  | 'custom';

export interface NetworkResult {
  edges: [string, string][];
  preset: NetworkPreset;
  seed: number;
}

export interface NetworkParams {
  random: { connectionChance: number };
  'newman-watts': { neighborsEachSide: number; shortcutChance: number };
  'core-periphery': {
    influencerPercent: number;
    influencerConnectivity: number;
    influencerReach: number;
    regularConnectivity: number;
  };
  'holme-kim': { newConnections: number; clusteringChance: number };
  waxman: { maxDistance: number; distanceEffect: number };
  sbm: { groupSize: number; withinGroupConnectivity: number; bridgeConnections: number };
}

export interface Intervention {
  id: string;
  type: InterventionType;
  targetId?: string; // agentId if applicable
  description: string;
  // SCENARIO_PARAMS fields
  rawParamsText?: string; // raw key=value text
  parsedParams?: Record<string, string | number | boolean>; // parsed for type coercion
  unknownKeys?: string[]; // unknown keys warnings
  scenarioDescription?: string; // scenario description override
  roundVisibility?: 'simultaneous' | 'sequential' | 'random'; // round visibility override
  // NETWORK_TOPOLOGY fields
  networkPreset?: NetworkPreset;
  networkParams?: Partial<NetworkParams>;
  customEdges?: [string, string][];
  resolvedNetwork?: NetworkResult; // frozen at submit time
}

export interface ExperimentVariant {
  id?: string;
  name: string;
  description?: string;
  interventions?: Intervention[];
  ops?: any[];
}

export interface Notification {
  id: string;
  type: 'success' | 'error' | 'info';
  message: string;
}

// #13 Guide Assistant Message
export interface GuideMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  suggestedActions?: GuideActionType[]; // Actions parsed from content
}

export type GuideActionType =
  | 'OPEN_WIZARD'
  | 'OPEN_NETWORK'
  | 'OPEN_EXPERIMENT'
  | 'OPEN_EXPORT'
  | 'OPEN_ANALYTICS'
  | 'OPEN_HOST';

// =============================================================================
// Generic Template System Types
// =============================================================================

export type CoreMechanicType = 'grid' | 'discussion' | 'voting' | 'resources' | 'hierarchy' | 'time';

export interface CoreMechanicConfig {
  type: CoreMechanicType;
  enabled: boolean;
  config: Record<string, any>;
}

export interface SemanticActionConfig {
  name: string;
  description: string;
  instruction: string;
  parameters?: Record<string, string>;
  effect?: string;
}

export interface AgentArchetypeConfig {
  name: string;
  rolePrompt: string;
  style?: string;
  userProfile?: string;
  properties?: Record<string, any>;
  allowedActions?: string[];
}

export interface GenericTemplateConfig {
  id: string;
  name: string;
  description: string;
  version?: string;
  coreMechanics: CoreMechanicConfig[];
  availableActions: string[];  // Array of action IDs from ACTION_SPACE_MAP
  actions?: Array<string | Record<string, any>>;
  parameters?: Record<string, any>;
  scenario_id?: string;
  round_visibility?: 'simultaneous' | 'sequential' | 'random';
  environment: {
    description: string;
    rules?: string[];
  };
  defaultTimeConfig?: TimeConfig;
}
