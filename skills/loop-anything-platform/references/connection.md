# Platform connection and tool calls

This installed Skill contains the complete operating guide and call scripts. Clients need not install or run the full platform. Use generic tools directly or author-provided package wrappers around the same interfaces, without searching platform source or internal modules.

Managed wake-ups automatically bind the [scoped entry](scoped-entry.md) when needed. Run at this Skill root, or use absolute script paths from another working directory:

```sh
python3 scripts/call.py check
python3 scripts/call.py list
python3 scripts/call.py read_capabilities
python3 scripts/call.py TOOL --arguments @arguments.json
```

Scripts use only the Python standard library and work with compatible local Python 3.9+, independently of the platform installation's Python path. Windows may use `py -3`.

See [team runtime](team-runtime.md) for NAS/HTTP and lightweight executors. Team tool addresses can use `nas:///locally-mounted-team-directory`. A timed-out NAS call returns `pending` plus an ID; use `call.py result --request-id ID` for the same receipt. Timeout does not cancel or redispatch.

Personal addresses live in `~/.config/loop-anything/spaces.json` (override with `LOOP_ANYTHING_SPACES` for isolation). New profiles use `default_space:auto` and contain no inferred addresses. The default installer records its actual local URL. Automatic selection uses the one recorded address, or team when both are recorded. `--default local|team` pins a preference; `--default auto` restores automatic selection. No recorded address produces a configuration error. Source, installed clients, and exported Skills share this configuration; `platform-source.json` only identifies an export's origin.

```sh
python3 scripts/call.py spaces
python3 scripts/call.py spaces --team-url nas:///local-mount/team --team-web-url https://team.example
python3 scripts/call.py spaces --default local
python3 scripts/call.py list --space team
```

The script stores immutable work, resource and request origins in `spaces.routing.sqlite3` beside the personal spaces configuration. Do not calculate or remember platform URLs for continuing work. Creating/discovering resources records their origins; later calls resolve known resource IDs automatically, even after the default or configured address changes. Every response carries `work_id` and `routing_request_id`. If names exist on multiple platforms, or a platform-wide follow-up has no resource selector, pass the returned `--work WORK_ID`. This selects the existing work, not a new destination. Read-only queries can look up resources directly on the verified platform for the task, including IDs this client has not seen. Known references that identify one common verified platform also determine the destination. A Run snapshot also records the origin of its continuation references, so later reads can follow them by ID alone. Without a binding or known origin, discover the resource in the intended platform. Do not scan other platforms to guess where an ID belongs.

Managed Agent startup, native-session resume and wait wake-up inject the work binding into the child process. Its calls need no `--url`, `--space` or manually constructed environment. Explicit `--work` must agree with the injected origin; it cannot override it with another platform. A separate Agent on the same machine shares the durable ledger; use the returned work reference when necessary. References are local to this installation; a different machine must first discover resources through its configured platform connection. Receiver execution gets a fresh binding after explicit NAS mount adaptation.

`--url` and `--space` select new work/discovery; they cannot override an existing resource or request origin. Resource origins retain their actual work reference and platform identity, not just a URL. An unverified record at the same URL cannot replace that origin. The saved platform identity is checked before tool calls, and HTTP writes carry that identity for server validation. Unavailable, unknown, ambiguous or conflicting origins stop with an error. No endpoint failure falls back to another platform. The old address environment selector is not used.

A request is reserved locally **before** network submission. Retain `routing_request_id` (also printed to stderr before submission) and use `retry --request-id ID` to retry the saved operation, or `result --request-id ID` for a receipt. retry reuses saved arguments and rejects unknown IDs; do not reconstruct the operation as new work. For business creation tools, the pair of tool name and `arguments.request_id` identifies the operation independently of transport IDs. The first submission fixes its original work, arguments and `routing_request_id` before network I/O. Omitting or changing `--request-id` later still resolves to that first saved operation and returns its original `routing_request_id`; use the returned ID for receipts. An already-used transport ID for another operation, conflicting arguments or ambiguous saved attempts is rejected. Reusing an ID with different arguments or tool is rejected. Successful HTTP receipts are cached; after a lost HTTP import_timeline response, retry reuses the original platform and deduplicated import request. Read-only HTTP tools may be retried on their original platform and return a fresh observation. Other unconfirmed HTTP mutations return `outcome_unknown`. Inspect original work before deciding on a new operation. NAS retries reuse the original mailbox and receipt. New independent work must use a new request ID.

The local webpage edits personal addresses/defaults only; it does not navigate to the team webpage. A team webpage cannot read or write personal settings. Current pages, task execution, independently configured receivers and local schedules keep their own platform/registry; changing the default never migrates them.

Loop editing, runtime operations, and communication require no passphrase or unlock. Definition edits still check revisions; tasks still validate scope, versions, and execution identity.

First check the connection, then read the directory and its instructions. `read_capabilities` reports service version, capability-to-tool mappings, references, and supported schema keywords. `restart_required` means disk source and the running version differ; disk additions are not yet service capabilities. The directory describes the currently exposed mechanisms/parameters. If documentation mentions an absent field, check service versions rather than bypassing tools through the database or internal modules. Arguments accept JSON or `@UTF8_FILE`; retain returned IDs, revisions, and tokens. Obtain Loop keys through `list_loops`. Connection checks do not invoke models or create business Runs.

Check `ok` on every call and `accepted` on reports; failures exit 2. Script/monitor reporting uses the bundled client described in [reporting](run.md#unified-event-and-result-reporting). Scheduling later work does not complete the current task, and a text reply is not a submission receipt. Author wrappers may submit and finish for you; direct tool use follows the relevant run.md section.

To continue work, find the existing Run with list_runs, then read_timeline. Ordinary platform operations may omit token; the platform manages an internal operation identity. Managed nodes retain the scoped identity in their prompt. Explicit invalid/expired tokens do not widen scope automatically. WeChat, Feishu, and terminals share the same platform/Timeline; switching entry does not create a Run or change notification targets.

## Fixed HTTP health URL

For a lightweight connectivity test, use `GET http://SERVER:PORT/api/health`. It returns HTTP 200 and `{"ok":true,"service":"loop-anything","version":"..."}` without credentials or custom headers. This checks the HTTP service, not Agent execution or external backends; it is optional and does not gate any operation.

```sh
curl -fsS --max-time 5 http://SERVER:PORT/api/health
# When testing through an HTTPS proxy, skip certificate and hostname checks on the caller:
curl -kfsS --max-time 5 https://SERVER/api/health
```

The platform's HTTP listener uses no TLS, certificate validation, or external verification requests. An HTTPS proxy's certificate is checked by the caller; the endpoint cannot disable that check. Use the real listening port and a reachable host address; other machines need the server to listen beyond loopback. NAS-only `--no-web` services have no HTTP endpoint. For full platform/tool discovery, use the existing `call.py check`.

## Installation and update entry

Export Skills with the current platform Python during installation or upgrade:

```sh
"<PLATFORM_PYTHON>" -m loop_anything skills --install-dir "<AGENT_SKILL_DIRECTORY>" --url "<ACTUAL_PLATFORM_URL>"
# Update generated Skill files, retaining the actual URL and other personal files.
"<PLATFORM_PYTHON>" -m loop_anything skills --install-dir "<AGENT_SKILL_DIRECTORY>" --url "<ACTUAL_PLATFORM_URL>" --replace
```

Platform and Skill updates are separate steps. Use the target agent's supported Skill directory, not a guessed location. Reload the Skill and run check afterward. New Skill instructions do not grant old services new capabilities; trust the live tool schema. Before platform installation, follow the source/distribution README. Installation and read-only discovery do not start models or create Runs.
