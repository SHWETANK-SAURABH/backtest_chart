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
