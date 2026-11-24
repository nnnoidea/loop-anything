# Using Run facts for a Loop review

Start when the user asks, a managed plan reaches its agreed trigger, or a schedule the user configured is due. The Agent decides what the measurements mean. The same tools answer one-off follow-up questions.

## Select the Runs

Use `list_runs` with `loop_id` across versions, or `loop_key` for a specific currently installed method on a Run. For a creation period set `created_from` (inclusive) and `created_to` (exclusive) in Unix seconds. Include archived Runs with `archived:"include"`. Page in a stable creation order. For “all this week” follow every `next_offset`; for “the latest five” stop at five. The list and its facts describe current outcomes for the selected cohort. For a hot-updated Run filter its **attempts** by their executed version when comparing methods.

Use `view:"revisions"` for a compact inventory: each item contains its Run ID, revision and observation stamp. Keep the inventory alongside reusable per-Run counts or references when continuing a long-running analysis. On the next check pass the last complete inventory for the same selection as `known_revisions` to list_runs. Its pages contain changed or new Run stamps and `removed_run_ids` identifies former members. Merge those rows and removals into the saved inventory. For a latest-N sample, select the N first, then compare using those exact IDs. Reuse unchanged measurements, replace those of changed Runs, and remove Runs outside the new scope. A changed stamp invites inspection; only the relevant evidence decides whether an update is worth reporting. Use live start times for elapsed waits. Medians over multiple Runs cannot be reconstructed by averaging batch medians.

## Collect only what answers the question

Pass the selected IDs to `query_run_facts`. The server filters and aggregates across the entire ID set **before** paginating the result. Omit `group_by` for individual facts, use `[]` for totals, or supply any combination of fields from the chosen source. The response lists its field names. Copy a group's key values into `filters` to read its rows. For the slowest nodes, group attempts by node, set `order_by:"median_run_wall_seconds"` and `descending:true`. Follow `next_offset` and disclose missing Runs. Each row has a Run ID and a source-local fact ID.

| Source | Facts available |
| --- | --- |
| runs | Current status, creation time and Run attention error |
| tasks | Node and version, current state, budget error, current execution |
| attempts | Execution identity, node/version, attempt number and status, current task status, timestamps and reported errors |
| history | Recorded events, their times, transitions, messages, error reasons and diagnostic snapshots. Each occurrence counts. |
| diagnostics | Current Run diagnostics, affected task and recorded details |
| notifications | Delivery states, errors and related task or execution |
| observations | Latest saved observation summaries and outstanding jobs, including failed or interrupted jobs. The history also records failures and recoveries. Read the latest produced metrics with read_observations, or read_monitor_history for a registered monitor. |

For a complete review, look across these sources. Start with counts by state or event kind, inspect the underlying groups and report all problems in the cohort, including previously reported ones still relevant. Distinguish past incidents, active failures and automatic pauses from manual pauses. Use a follow-up's narrower selection only for that question.

For “did the new version get slower or retry more?”, for example:

```json
{"source":"attempts","run_ids":["RUN_A","RUN_B"],"group_by":["node","version","status"]}
```

Each group contains its fact count and distinct Run count. Attempt groups also include retries (attempt number above one), measured durations, median and maximum seconds, median submission-to-finish seconds, and median per-Run wall time across measured, possibly overlapping attempts. Missing endpoints are unknown. Use all selected IDs in one grouped request for cohort-wide statistics. Filter the raw attempts to compare failures and successes or inspect timings. `read_execution_attempt(run_id,execution_id)` retrieves a particular attempt's error, progress and result references even after retry. Keep conclusions conditional when timestamps cannot separate queueing from execution.

## Report or arrange another check

Use [ReadableDocs](https://github.com/nnnoidea/ReadableDocs/tree/main/readable-docs) for the user's final report. Read the installed `readable-docs/SKILL.md` and follow its writing, figure, export and review instructions. Write in the user's language. Start with the scope and conclusions the user needs, use figures to make patterns and their magnitude easy to see, and keep the evidence and limitations needed to act. Save the editable source package in the assignment's working directory or the review workspace. Export and check the standalone HTML using ReadableDocs. Its figures and styles must work without any other report files.

Save the review through `append_timeline` on the chosen optimization Timeline. Use a stable key, `review:{"loop_id":"TARGET_LOOP","run_count":N}`, and evidence refs such as `{"run_id":"…","task_id":"…","execution_id":"…","label":"失败样本"}`. Put the scope, findings, evidence and reusable analysis details in `text` for the next Agent. Use the execution ID with `read_execution_attempt` for historical evidence. Put the contents of the final HTML file in the separate `review_html` field (up to 1 MiB). To avoid shell argument limits, build the JSON arguments file by reading HTML as UTF-8, then call the platform client with `--arguments @arguments.json`. The returned `report_url` is relative to the selected platform and RSI for loop opens it through 查看报告.

Manual, managed and scheduled reviews use the same publication step. If HTML export is blocked, retain the Agent-readable findings and disclose the blocker. Keep previous findings available when incorporating incremental evidence. Subsequent discussion uses ordinary notes or decisions. Change the Loop only at the user's request.

For a managed plan register the user's trigger with `wait_for` and exit. For a recurring review use the existing local scheduler to invoke an Agent with the chosen cohort, question and destination Timeline. If the user only wants updates on change, its script check can run `loop-anything client tool list_runs --arguments @selection-with-known-revisions.json --if-changed`. The client exits 0 for change, 1 for unchanged, 2 on error. Use a selection file with the same Loop/time scope and the saved known_revisions array (initially empty); advance the saved inventory only after the action succeeds. A manual read remains possible even with unchanged data.
