# Weekly review and alerts

## In the worker

| Job | When | What |
| --- | --- | --- |
| Data-quality check | daily 09:00 | ntfy message "Data check" when a source has not synced for 24 h, a sync keeps failing, nutrition was logged on fewer than 5 of the last 7 days, or there were fewer than 3 weigh-ins |
| Morning recovery | every 10 min 05:00–11:50 | ntfy push with recovery %, zone, strain target, and sleep duration once scores and main sleep exist |
| Bedtime reminder | every 5 min | ntfy reminder starting 30 min before planned bedtime with bedtime, sleep need, and alarm/wake time |
| Failure alerts | on failure | ntfy alert after 3 failures in a row of one sync; a revoked Google grant alerts at once with the re-auth command |

Notifications need `HC_NTFY_TOPIC` (and `HC_NTFY_URL` if not ntfy.sh, plus `HC_NTFY_TOKEN` if the server requires auth). Message language is set via `HC_NOTIFY_LANG` (`en` default, `cs`).

## Weekly review in Claude (recommended runner)

The review itself is done by Claude through the connector, so it runs where Claude
runs. The MCP server ships the procedure as the prompt `weekly_review`
(`src/health_coach/prompts/weekly_review.md`) and the coach instructions as
`coach_instructions`.

1. In claude.ai create a project "Coach", paste `coach_instructions.md` into the project
   instructions, fill in its placeholders (including the language for reviews), and
   enable the health-coach connector for it.
2. Create a scheduled task in that project: weekly, Sunday 19:00, with the text of
   `weekly_review.md` as the prompt (or "Use the weekly_review prompt of the
   health-coach connector").
3. The task ends with `send_notification`, so the summary arrives on the phone.

Instead of a scheduled task you can run the same prompt headless from any machine that
has a Claude login and the connector configured, for example
`claude -p "Use the weekly_review prompt of the health-coach connector"` from cron.

The optional morning brief works the same way: a daily 07:30 task asking for
`get_recovery_status` and today's planned session (`get_planned` of the fit connector), sent with
`send_notification`.
