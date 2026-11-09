# Call another Loop from a node

Reuse an existing Loop as a node implementation. Find an installed version's `key` on the same service with `list_loops`, then configure `set_implementation`:

```json
{
  "draft_id":"CURRENT_DRAFT_ID",
  "revision":1,
  "node_id":"analyze",
  "kind":"loop",
  "loop":{
    "key":"TARGET_LOOP_KEY",
    "inputs":{"dataset":{"$":"inputs.dataset"}},
    "result":{"outputs":{"analysis":{"$":"records.analysis"}}}
  }
}
```

When changing another kind to loop, retain the editing contract: use `clear:["lifecycle", ...]` to remove the old lifecycle and incompatible fields such as command/observe, selecting the Loop-call lifecycle template. No startup or polling script is needed.

- `loop.key` identifies an installed version on the current service. Child nodes can still use remote executors or named agents.
- `inputs` uses existing `$`/template expansion over parent-node `inputs`, `parameters`, and `settings`. Omission passes the parent input object. Expansion happens when the execution first connects to its child Run, not repeatedly as settings change during waiting.
- `result` is the parent completion-report envelope, mapped from child `records` (latest committed values), `settings`, `inputs`, and `run_id`. Usually provide only `outputs`; explicitly map `settings` when initializing the parent Loop. Other report fields retain their contracts. Omission means `{"outputs":{}}`; every declared output port needs a mapping.

The platform creates the child Run and executes its own entry implementation. An agent entry uses its configured command; without one, it waits for an agent just like an ordinary Run. The child must reach completed through its own completion condition. A result record or agent `finish` is not Run completion.

The service scheduler durably waits for the child without a waiting script, agent, or occupied worker thread. On completion, it expands `result`, validates the parent output contract, then triggers existing lifecycle transitions, routes, and dependencies. A paused child leaves the parent waiting; termination reports failed; startup/mapping errors report process_error. Existing lifecycle handling applies.

## Associations, recovery, and control

One Task retains one child Run; creation and association commit atomically. Restarts, repeated ticks, and parent retries reuse it rather than repeating completed work. Retrying cannot change the child key or inputs; create a new Task for another invocation. For a bad result mapping, choose an already-configured corrected candidate and retry the Task without rerunning the child. Draft edits do not change an existing Run's implementations.

Parent and child controls are independent. Pausing the parent does not pause the child. Cancelling the parent Task or ending the parent Run stops waiting, not the child. Use `command` on the child's ID to stop it explicitly. Ancestor recursion into the same Loop version is unsupported; use existing Tasks/plans for iteration.

`read_task.execution_state` provides `child_run_id`, the latest observed `child_status`, and `child_revision` when consuming the result; `task.child_call` retains the association. The child's `read_run` includes `parent_call`, and web details link to it. Authorization text and notification origin inherit from the parent. The child supplies its business handbook, implementations, communication team, and completion condition.

`test_loop` remains isolated scenario simulation: scenario steps provide submitted/completed/failed reports without actually creating or running child Loops. Real integration runs parent and child and verifies association, results, and completion conditions. Do not maintain another child-Run mapping table, assemble a separate start_run initializer, or write long polling.
