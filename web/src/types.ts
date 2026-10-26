/**
 * TypeScript types matching healthstats API responses.
 */

export interface RecoveryComponent {
  signal: string;
  value: number | null;
  z: number;
  weight: number;
  points: number;
}

export interface DayResponse {
  date: string;
  weekday: string;
  scores: {
    recovery: number | null;
    recovery_zone: string | null;
    components: RecoveryComponent[] | null;
    flags: string[];
    strain: number | null;
    strain_target_low: number | null;
    strain_target_high: number | null;
    sleep_need_min: number | null;
    sleep_actual_min: number | null;
    sleep_debt_min: number | null;
    sleep_performance: number | null;
    sleep_efficiency: number | null;
    planned_bedtime: string | null;
    planned_wake: string | null;
  };
  vitals: {
    resting_hr: number | null;
    hrv_rmssd_ms: number | null;
    breathing_rate: number | null;
    skin_temp_delta: number | null;
    spo2_avg: number | null;
  };
  activity: {
    steps: number | null;
    active_minutes: number | null;
    calories_out: number | null;
  };
  activities: {
    type: string;
    name: string;
    start_ts: string | null;
    end_ts: string | null;
    strain: number | null;
    // Strength sessions only
    hard_sets?: number | null;
    volume_kg?: number | null;
    // Other exercise only
    duration_min?: number | null;
    calories?: number | null;
    distance_km?: number | null;
    avg_hr?: number | null;
  }[];
  as_of: string | null;
}

export interface RecoveryResponse {
  date: string;
  recovery: number | null;
  zone: string | null;
  recovery_z: number | null;
  summary: string;
  components: RecoveryComponent[];
  flags: string[];
  current_hrv: number | null;
  current_rhr: number | null;
  /** [low, high] of the personal normal range, from the latest baseline. */
  hrv_band: [number, number] | null;
  rhr_band: [number, number] | null;
  hrv_series: {
    date: string;
    val: number | null;
    band_lo: number | null;
    band_hi: number | null;
  }[];
  rhr_series: {
    date: string;
    val: number | null;
    band_lo: number | null;
    band_hi: number | null;
  }[];
  as_of: string | null;
}

export type SleepStage = "awake" | "rem" | "light" | "deep";

export interface SleepResponse {
  date: string;
  session: {
    start_ts: string | null;
    end_ts: string | null;
    duration_min: number | null;
    time_in_bed_min: number | null;
    efficiency: number | null;
    wake_count: number;
  } | null;
  performance: number | null;
  consistency: number | null;
  stages: {
    stage: SleepStage;
    duration_sec: number;
    duration_min: number;
    start_ts: string;
    end_ts: string;
  }[];
  /** Minutes per stage. */
  stage_totals: Record<SleepStage, number>;
  need_breakdown: {
    base_need_min: number;
    debt_min: number;
    prev_strain: number | null;
    strain_bonus_min: number;
    nap_credit_min: number;
    total_need_min: number;
  };
  week: {
    date: string;
    weekday: string;
    actual_min: number | null;
    need_min: number | null;
    performance: number | null;
  }[];
  tonight_plan: {
    planned_bedtime: string | null;
    planned_wake: string | null;
    sleep_need_min: number | null;
    today_strain: number | null;
    today_strain_bonus_min: number;
  };
  as_of: string | null;
}

export interface StrainResponse {
  date: string;
  strain: number | null;
  cardio_load: number | null;
  muscular_load: number | null;
  strain_target_low: number | null;
  strain_target_high: number | null;
  recovery: number | null;
  rest_hr: number;
  hr_max: number;
  peak_hr: number | null;
  zones: {
    key: string;
    name: string;
    min_hr: number;
    max_hr: number;
    minutes: number;
    color: string;
  }[];
  hr_points: {
    time: string;
    /** Minutes since local midnight. */
    minute: number;
    bpm: number;
  }[];
  workout_windows: {
    start_minute: number;
    end_minute: number;
    name: string;
  }[];
  activities: {
    type: string;
    name: string;
    start_time: string | null;
    end_time: string | null;
    strain: number | null;
    // Strength sessions only
    hard_sets?: number | null;
    volume_kg?: number | null;
    mean_rpe?: number | null;
    // Other exercise only
    duration_min?: number | null;
    avg_hr?: number | null;
    max_hr?: number | null;
    distance_km?: number | null;
  }[];
  week_strains: {
    date: string;
    weekday: string;
    strain: number | null;
  }[];
  avg_week_strain: number | null;
  as_of: string | null;
}

export interface NutritionResponse {
  date: string;
  kcal: number;
  target_kcal: number | null;
  remaining_kcal: number | null;
  phase: string | null;
  weekly_rate_target_kg: number | null;
  macros: {
    name: string;
    val: number;
    target: number | null;
    unit: string;
    color: string;
  }[];
  meals: {
    key: string;
    name: string;
    time: string | null;
    kcal: number;
    items: {
      name: string;
      protein_g: number;
      carbs_g: number | null;
      fat_g: number | null;
      fiber_g: number | null;
      kcal: number;
    }[];
  }[];
  meals_count: number;
  last_logged_time: string | null;
  energy_balance: {
    intake: number;
    tdee: number | null;
    balance: number | null;
    mean_14_balance: number | null;
    expected_weekly_change: number | null;
    actual_weekly_change: number | null;
  };
  week: {
    date: string;
    weekday: string;
    kcal: number;
    protein_hit: boolean;
  }[];
  protein_hits_days: number;
  as_of: string | null;
}

export interface TrendsResponse {
  days: number;
  date: string;
  recovery: {
    avg: number | null;
    green_count: number;
    series: { date: string; val: number | null }[];
  };
  hrv: {
    avg: number | null;
    series: { date: string; val: number | null }[];
  };
  rhr: {
    avg: number | null;
    series: { date: string; val: number | null }[];
  };
  sleep: {
    avg_min: number | null;
    avg_perf: number | null;
    series: { date: string; val: number | null; perf: number | null }[];
  };
  strain: {
    avg: number | null;
    acwr: number | null;
    series: { date: string; val: number | null }[];
  };
  weight: {
    last: number | null;
    rate: number | null;
    series: { date: string; raw: number | null; avg: number | null }[];
  };
  kcal: {
    avg: number | null;
    avg_protein: number | null;
    target: number | null;
    series: { date: string; val: number | null; protein: number | null }[];
  };
  as_of: string | null;
}

export interface CalendarResponse {
  month: string;
  month_label: string;
  cells: {
    date: string | null;
    day: number | null;
    has_data: boolean;
    recovery: number | null;
    recovery_zone: string | null;
    sleep_hours: number | null;
    strain: number | null;
  }[];
  stats: {
    avg_recovery: number | null;
    green_days: number;
    yellow_days: number;
    red_days: number;
    avg_sleep_hours: number | null;
    sleep_debt_end_min: number;
    avg_strain: number | null;
    max_strain: number | null;
    max_strain_date: string | null;
    workouts_total: number;
    workouts_breakdown: { name: string; count: number }[];
  };
  as_of: string | null;
}

export interface JournalResponse {
  date: string;
  yesterday_date: string;
  yesterday_weekday: string;
  logged_time: string | null;
  yesterday: {
    behavior: string;
    name: string;
    amount: number | null;
    note: string | null;
    active: boolean;
  }[];
  insights: {
    behavior: string;
    name: string;
    /** Next-day recovery with minus without, in percentage points. */
    difference_pp: number;
    with_count: number;
    without_count: number;
  }[];
  insufficient: {
    behavior: string;
    name: string;
    with_count: number;
    without_count: number;
  }[];
  as_of: string | null;
}

export interface ReportResponse {
  period: "week" | "month";
  start: string;
  end: string;
  tiles: {
    recovery: { val: number | null; delta: number | null };
    strain: { val: number | null; delta: number | null };
    sleep_min: { val: number | null; delta: number | null; debt_min: number };
    consistency: { val: number | null; delta: number | null };
    kcal: {
      val: number | null;
      delta: number | null;
      protein_hit_days: number;
      total_days: number;
    };
    weight: { val: number | null; delta: number | null };
  };
  daily_recovery: {
    date: string;
    weekday: string;
    recovery: number | null;
    zone: string | null;
  }[];
  best_day: {
    date: string;
    weekday: string;
    recovery: number | null;
    sleep_min: number | null;
  } | null;
  worst_day: {
    date: string;
    weekday: string;
    recovery: number | null;
    sleep_min: number | null;
  } | null;
  muscles: {
    muscle: string;
    sets: number;
  }[];
  workouts_count: number;
  coach_review: {
    id: number;
    title: string | null;
    body: string | null;
    ts: string | null;
  } | null;
  as_of: string | null;
}

export interface HealthspanFactor {
  key: string;
  name: string;
  value: number | null;
  unit: string;
  goal: string;
  hr: number | null;
  years: number | null;
  has_data: boolean;
}

export interface HealthspanResponse {
  has_enough_data: boolean;
  latest: {
    week_start: string;
    delta_years: number | null;
    pace: number | null;
    age: number | null;
    biological_age: number | null;
    factors_with_data: number;
    factors: HealthspanFactor[];
    algo_version: number;
  } | null;
  history: {
    week_start: string;
    delta_years: number | null;
  }[];
  as_of: string | null;
}
