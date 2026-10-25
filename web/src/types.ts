/**
 * TypeScript types matching healthstats API responses.
 */

export interface DayResponse {
  date: string;
  weekday: string;
  scores: {
    recovery: number | null;
    recovery_zone: string | null;
    components: {
      hrv_rmssd?: number | null;
      resting_hr?: number | null;
      sleep_performance?: number | null;
      breathing_rate?: number | null;
      skin_temp_delta?: number | null;
      spo2?: number | null;
    } | null;
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
    start_time: string | null;
    end_time: string | null;
    duration_min: number | null;
    calories: number | null;
    distance_km: number | null;
    avg_hr: number | null;
    max_hr: number | null;
    strain: number | null;
    hard_sets: number | null;
    volume_kg: number | null;
    mean_rpe: number | null;
  }[];
  as_of: string | null;
}

export interface RecoveryResponse {
  date: string;
  recovery: number | null;
  zone: string | null;
  recovery_z: number | null;
  summary: string;
  components: {
    name: string;
    weight: string;
    deviation: string;
    raw: string;
    status: "good" | "bad" | "neutral";
  }[];
  flags: string[];
  current_hrv: number | null;
  current_rhr: number | null;
  hrv_band: {
    lo: number;
    hi: number;
  } | null;
  rhr_band: {
    lo: number;
    hi: number;
  } | null;
  hrv_series: {
    date: string;
    val: number | null;
    band_lo: number;
    band_hi: number;
  }[];
  rhr_series: {
    date: string;
    val: number | null;
    band_lo: number;
    band_hi: number;
  }[];
  as_of: string | null;
}

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
    stage: "awake" | "rem" | "light" | "deep";
    duration_sec: number;
    start_ts: string | null;
    end_ts: string | null;
  }[];
  stage_totals: {
    stage: "awake" | "rem" | "light" | "deep";
    label: string;
    color: string;
    min: number;
    formatted: string;
    percentage: number;
  }[];
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
    perf: number | null;
  }[];
  tonight_plan: {
    target_sleep_min: number;
    target_bed_min: number;
    bedtime: string;
    wake_time: string;
    reminder_time: string;
    efficiency_assumed: number;
    strain_bonus_min: number;
  } | null;
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
    zone: number;
    name: string;
    range: string;
    min_bpm: number;
    max_bpm: number;
    minutes: number;
    pct: number;
    color: string;
  }[];
  hr_points: {
    time: string;
    hour: number;
    bpm: number;
  }[];
  workout_windows: {
    start_hour: number;
    end_hour: number;
    name: string;
  }[];
  activities: {
    type: string;
    name: string;
    start_time: string | null;
    end_time: string | null;
    duration_min: number | null;
    avg_hr: number | null;
    max_hr: number | null;
    strain: number | null;
    distance_km: number | null;
    hard_sets: number | null;
    volume_kg: number | null;
    mean_rpe: number | null;
  }[];
  week_strain: {
    date: string;
    weekday: string;
    strain: number | null;
  }[];
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
    target: number;
    unit: string;
    color: string;
  }[];
  meals: {
    meal_type: string;
    name: string;
    time: string | null;
    kcal: number;
    items: {
      name: string;
      protein_g: number;
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
  start: string;
  end: string;
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
    series: { date: string; val: number | null }[];
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
    series: { date: string; val: number | null }[];
  };
  as_of: string | null;
}

export interface CalendarResponse {
  month: string;
  month_label: string;
  cells: {
    date: string | null;
    day: number | null;
    recovery: number | null;
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
    workouts_breakdown: string;
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
    label: string;
    present: boolean;
  }[];
  insights: {
    behavior: string;
    label: string;
    diff_recovery: number;
    diff_recovery_pct: number;
    days_present: number;
    days_absent: number;
    n_days: string;
  }[];
  insufficient: {
    behavior: string;
    label: string;
    count: number;
    text: string;
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
    sleep_min: number | null;
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
    name: string;
    sets: number;
    pct: number;
  }[];
  workouts_count: number;
  coach_review: {
    title: string | null;
    body: string | null;
    ts: string | null;
  } | null;
  as_of: string | null;
}
