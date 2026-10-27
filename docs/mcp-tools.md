# MCP tools

**health-coach**

| Area | Tools |
| --- | --- |
| Orientation | `get_context_snapshot`, `get_schema`, `get_data_coverage` |
| Overviews | `get_daily_overview`, `get_weekly_summary`, `get_weight_trend`, `get_scores`, `get_healthspan` |
| Analytics | `estimate_tdee`, `get_nutrition_summary`, `get_recovery_status`, `get_sleep_analysis`, `get_training_load`, `get_exercise_progress`, `get_personal_records`, `compare_periods` |
| SQL | `query_sql`: one read-only `SELECT`, checked by sqlglot, run as `coach_ro` with a timeout and row cap |
| Logging | `search_food`, `save_food`, `log_meal`, `update_nutrition_entry`, `delete_nutrition_entry`, `log_body_metric`, `log_checkin`, `log_exercise_session` |
| Journal & settings | `log_journal`, `get_journal`, `delete_journal_entry`, `get_journal_insights`, `set_sleep_settings`, `get_sleep_settings`, `set_profile`, `get_profile` |
| Training (read) | `search_exercises`, `get_workout_log` |
| Coaching state | `get_targets`, `set_targets`, `read_coach_log`, `write_coach_log`, `manage_goal` |
| Notifications | `send_notification` |

Prompts: `coach_instructions`, `weekly_review`.

**fit**: `link_opengym`, `unlink_opengym`, `get_account`, `search_exercises`,
`get_training_history`, `get_routines`, `get_routine`, `get_planned`, `plan_session`,
`update_routine`, `schedule_week`, `delete_planned`, `log_session`.
