# Platform connection and tool calls

This installed Skill contains the complete operating guide, call scripts, and platform address. Clients need not install or run the full platform. Use generic tools directly or author-provided package wrappers around the same interfaces, without searching platform source or internal modules.

If wake-up context supplies `tool_url`, read the [scoped entry](scoped-entry.md) and retain its address and bound identity. Otherwise run at this Skill root, or use absolute script paths from another working directory:

```sh
python3 scripts/call.py check
python3 scripts/call.py list
python3 scripts/call.py read_capabilities
python3 scripts/call.py TOOL --arguments @arguments.json
```

Scripts use only the Python standard library and work with compatible local Python 3.9+, independently of the platform installation's Python path. Windows may use `py -3`.

See [team runtime](team-runtime.md) for NAS/HTTP and lightweight executors. `connection.json` can use `nas:///locally-mounted-team-directory`. A timed-out NAS call returns `pending` plus an ID; use `call.py result --request-id ID` for the same receipt. Timeout does not cancel or redispatch.

`connection.json` holds the platform address. Use `--url ACTUAL_ADDRESS` for another endpoint or a `platform_url` supplied by wake-up context. Source, installed resources, and exported Skills use the same script.

Loop editing, runtime operations, and communication require no passphrase or unlock. Historical edit-protection metadata is ignored. Definition edits still check revisions; tasks still validate scope, versions, and execution identity.

First check the connection, then read the directory and its instructions. `read_capabilities` reports service version, capability-to-tool mappings, references, and supported schema keywords. `restart_required` means disk source and the running version differ; disk additions are not yet service capabilities. The directory describes the currently exposed mechanisms/parameters. If documentation mentions an absent field, check service versions rather than bypassing tools through the database or internal modules. Arguments accept JSON or `@UTF8_FILE`; retain returned IDs, revisions, and tokens. Obtain Loop keys through `list_loops`. Connection checks do not invoke models or create business Runs.

Check `ok` on every call and `accepted` on reports; failures exit 2. Script/monitor reporting uses the bundled client described in [reporting](run.md#unified-event-and-result-reporting). Scheduling later work does not complete the current task, and a text reply is not a submission receipt. Author wrappers may submit and finish for you; direct tool use follows the relevant run.md section.

To continue work, find the existing Run with list_runs, then read_timeline. Ordinary workspace operations may omit token; the platform manages an internal operation identity. Managed nodes retain the scoped identity in their prompt. Explicit invalid/expired tokens do not widen scope automatically. WeChat, Feishu, and terminals share the same platform/Timeline; switching entry does not create a Run or change notification targets.

## Installation and update entry

Export Skills with the current platform Python during installation or upgrade:

```sh
"<PLATFORM_PYTHON>" -m loop_anything skills --install-dir "<AGENT_SKILL_DIRECTORY>" --url "<ACTUAL_PLATFORM_URL>"
# Update generated Skill files, retaining the actual URL and other personal files.
"<PLATFORM_PYTHON>" -m loop_anything skills --install-dir "<AGENT_SKILL_DIRECTORY>" --url "<ACTUAL_PLATFORM_URL>" --replace
```

Platform and Skill updates are separate steps. Use the target agent's supported Skill directory, not a guessed location. Reload the Skill and run check afterward. New Skill instructions do not grant old services new capabilities; trust the live tool schema. Before platform installation, follow the source/distribution README. Installation and read-only discovery do not start models or create Runs.
