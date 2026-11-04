// Response shapes of the backend API. Point values are theoretical NIFTY 50 index points.

export interface ComponentHealth {
  status: "ok" | "unavailable";
  detail: string | null;
}

export interface Health {
  status: "ok" | "degraded";
  database: ComponentHealth;
  redis: ComponentHealth;
}

export interface Instrument {
  id: string;
  symbol: string;
  name: string;
  exchange: string;
  instrument_type: string;
  timezone: string;
  is_tradable: boolean;
}

export interface Overview {
  instruments: number;
  data_providers: number;
  datasets: number;
  strategies: number;
  strategy_versions: number;
  backtests: number;
  completed_backtests: number;
}

export type JobStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type Json = Record<string, unknown>;

export interface DatasetInfo {
  id: string;
  provider_id: string;
  timeframe: string;
  version: number;
  content_hash: string;
  status: "building" | "ready" | "invalid";
  start_date: string | null;
  end_date: string | null;
  row_count: number;
  quality_report: Json;
  created_at: string;
}

export interface ProviderHealth {
  code: string;
  name: string;
  configured: boolean;
  connected: boolean | null;
  detail: string | null;
  data_subscription_active: boolean | null;
}

export interface MarketDataHealth {
  providers: ProviderHealth[];
  datasets: DatasetInfo[];
}

export interface IngestionJob {
  id: string;
  provider_id: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  status: JobStatus;
  progress: Json;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Strategy {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface StrategyVersion {
  id: string;
  strategy_id: string;
  version: string;
  pine_source_reference: string | null;
  pine_source_sha256: string | null;
  python_implementation_version: string;
  code_hash: string;
  parameters: Json;
  indicator_settings: Json;
  execution_settings: { entry_rules?: Record<string, string> } & Json;
  change_description: string | null;
  created_at: string;
}

export interface StrategyDetail extends Strategy {
  versions: StrategyVersion[];
}

export interface Backtest {
  id: string;
  strategy_version_id: string;
  intraday_dataset_id: string;
  daily_dataset_id: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  execution_method: string;
  execution_settings: Json;
  risk_settings: Json;
  capital_assumptions: Json;
  strategy_options: StrategyOptions | Record<string, never>;
  input_hash: string;
  result_hash: string | null;
  status: JobStatus;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export type Pattern = "OR" | "DR" | "ER" | "WR";
export type MtzChoice = "daily" | "weekly" | "both";
export type StrategyKind = "mtz_reversal" | "pivot_boss";
export type BookSetup =
  | "BREAKAWAY"
  | "MAGNET"
  | "TREND_CHANGE"
  | "CPR_PULLBACK"
  | "CPR_FADE"
  | "PERSON_PLAN"
  | "FLOOR_PIVOT"
  | "CAM_REVERSAL"
  | "CAM_PATTERN"
  | "CAM_BREAKOUT";

/** Empty for backtests made before options existed: all patterns, both MTZs. The later options are
 * missing from older runs, which used the script's thresholds without day direction or ADR trades. */
export interface StrategyOptions {
  entry_patterns: Pattern[];
  mtz: MtzChoice;
  cpr_thresholds?: [number, number, number];
  day_direction?: boolean;
  adr_trade?: boolean;
  strategy?: StrategyKind;
  book_setups?: BookSetup[];
  weekly_filter?: boolean;
  trend_analysis?: boolean;
  clear_trend?: boolean;
}

export interface BacktestListItem extends Backtest {
  summary: { total_trades: number; win_rate: number | null; net_points: number; profit_factor: number | null } | null;
}

export interface BacktestDetail extends Backtest {
  trade_count: number;
  events: { type: string; message: string | null; details: Json; at: string }[];
}

export interface Reproducibility {
  input_hash: string;
  runs: { id: string; status: JobStatus; result_hash: string | null; created_at: string }[];
  completed_runs: number;
  identical: boolean | null;
}

export interface ConditionStats {
  trades: number;
  wins: number;
  losses: number;
  net_points: number;
  win_rate: number;
  average_points: number;
}

export interface Metrics {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number | null;
  gross_profit_points: number;
  gross_loss_points: number;
  net_points: number;
  profit_factor: number | null;
  expectancy_points: number | null;
  average_trade_points: number | null;
  average_win_points: number | null;
  average_loss_points: number | null;
  max_drawdown_points: number | null;
  average_holding_seconds: number | null;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  sharpe_ratio: number | null;
  sharpe_assumptions: Record<string, string | number>;
  by_market_condition: Record<string, Record<string, ConditionStats>>;
  unit_summary: Json;
}

export interface Trade {
  id: string;
  trade_number: number;
  trading_date: string;
  side: "long" | "short";
  entry_ts: string;
  exit_ts: string;
  entry_price: number;
  exit_price: number;
  stop_loss: number | null;
  target: number | null;
  exit_reason: string;
  holding_seconds: number;
  gross_points: number;
  cost_points: number;
  net_points: number;
  market_regime: string | null;
  indicators_at_entry: Json;
  indicators_at_exit: Json;
  decision_reason: string[];
  execution_assumptions: Json;
}

export interface Page<T> {
  total: number;
  items: T[];
}

export interface EquityPoint {
  ts: string;
  cumulative_points: number;
  drawdown_points: number;
}

export interface PeriodRow {
  trading_date: string;
  trades: number;
  wins: number;
  losses: number;
  net_points: number;
}

export interface CprLevels {
  pp: number | null;
  tc: number | null;
  bc: number | null;
  [key: string]: unknown;
}

export interface DecisionContext {
  cpr: { daily: CprLevels | null; weekly: CprLevels | null };
  camarilla: Record<string, number | string | null>;
  adr: Record<string, number | string | null>;
  adr_usage_percent: number | null;
  ema20: number | null;
  ema_direction: string | null;
  market_regime: string | null;
  condition_labels: Record<string, string | null>;
  [key: string]: unknown;
}

export interface Decision {
  candle_ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  action: "BUY" | "SELL" | "HOLD";
  reason_codes: string[];
  explanation: string;
  long_permission: boolean | null;
  short_permission: boolean | null;
  reversal_state: { signals?: { code: string; side: string }[]; entry_signal?: Json | null };
  trade_engine_state: { trade_direction?: Json; execution_notes?: string[] };
  trade_opened: boolean;
  position_closed: boolean;
  position_state: string;
  market_context: DecisionContext;
}

export interface Report {
  id: string;
  backtest_job_id: string;
  category: string;
  format: string;
  status: JobStatus;
  file_size_bytes: number | null;
  sha256: string | null;
  report_metadata: Json;
  error: string | null;
  created_at: string;
  generated_at: string | null;
}

export interface AiDatasetVersion {
  id: string;
  ai_dataset_id: string;
  dataset_name: string;
  version: string;
  backtest_job_id: string;
  generation_parameters: Json;
  content_hash: string | null;
  record_count: number;
  label_distribution: Record<string, Record<string, number>>;
  split_statistics: Record<
    string,
    { records: number; sessions: number; first_session: string | null; last_session: string | null }
  >;
  validation_report: { passed?: boolean; checks?: { check: string; passed: boolean; count: number }[] } & Json;
  status: JobStatus;
  error: string | null;
  created_at: string;
}

export interface AiDatasetExport {
  id: string;
  format: string;
  split: string;
  file_size_bytes: number;
  sha256: string;
  record_count: number;
  exported_at: string;
}
