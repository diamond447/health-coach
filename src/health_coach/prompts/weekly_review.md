Run my weekly review. Work only from the tools; do not ask me anything, I am not
reading along. Write in the language set in the project instructions
(English if none is set).

1. Call get_context_snapshot, then get_weekly_summary (last full week) and
   estimate_tdee. Read the decisions and reviews of the last 4 weeks with
   read_coach_log(kind="decision") and read_coach_log(kind="review", limit=4).
2. Weight: compare the weekly trend rate with the target band of the current
   phase. Change calories by 100-150 kcal only if the rate was outside the band
   for 2 consecutive weeks (check last week's review) and logging is reliable
   (TDEE confidence medium or high, nutrition logged on at least 5 of 7 days).
   If you change targets, use set_targets with the reason.
3. Check protein adherence, average sleep, the readiness trend
   (get_recovery_status) and hard sets per muscle against 10-20 per week,
   counting other sports as extra load.
4. Check progression of the main lifts with get_exercise_progress. Plan next
   week's loads where a lift progressed or stalled (the Fit connector writes them to openGym).
   Schedule a deload (write_coach_log kind="plan", and lower loads in openGym)
   only if performance dropped on 2+ lifts together with red readiness.
5. Save the review with write_coach_log(kind="review", title="Weekly review
   <ISO week>", related_from/related_to = the week), listing numbers, what you
   changed and why, and what to watch next week.
6. Send me a short summary with send_notification (title "Weekly review",
   at most 6 lines: weight rate vs band, kcal and protein adherence, sleep,
   training highlights, changes made).

If data is missing or stale (warnings), say so in the review and the
notification instead of guessing, and do not change targets that week.
