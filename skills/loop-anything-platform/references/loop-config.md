# Recipient runtime configuration

When sharing or moving a Loop, or adjusting paths, agents, and external services, first use `read_loop_config(key=...)` for the recipient configuration and actual node/candidate IDs in `targets`. Do not copy or rewrite the workflow to adapt a machine.

## Templates and personal configuration

- Every export includes `config.example.json`. An authored asset with that name is preserved; otherwise an empty override template is generated. Read a draft template with `read_loop_config(draft_id=...)` and edit through `put_asset`.
- Installation creates `loop-configs/<installed-key>.json` in the service workspace. `read_loop_config` returns its exact path, content, and revision. Reinstallation preserves it. Older installations without the file use the package template or empty overrides; configuration is not a prerequisite for Run creation.
- `set_loop_config(key, revision, config)` saves the entire configuration. It validates JSON structure, candidate references, and execution fields only; it does not probe directories, programs, login, network, or permissions, or start work. Reread after conflicting edits. Users may directly edit the returned JSON path, not the installed content-addressed package snapshot.
- New Runs read and snapshot the configuration. Existing Runs, executions, and retries retain their snapshot. Web startup displays and uses it read-only, without an editable parameter form. Explicit API/agent startup parameters still take precedence.
- Configuration belongs to an installed version. New versions have separate configuration, avoiding automatic reuse of obsolete node mappings. Service configuration can live in a team NAS workspace; `cwd` refers to the actual execution machine.
- Exports and Loop copies carry the author template, not recipient overrides. Put reusable configuration needs in the template. Keep credentials in the execution environment or existing platform integrations, not templates. The platform does not guess or replace hardcoded private paths.

## Configuration example

Use actual IDs from `read_loop` and `read_loop_config.targets`; these are illustrative:

```json
{
  "inputs": {
    "dataset_dir": "/shared/team/datasets",
    "training_endpoint": "https://training.example"
  },
  "bindings": {"research": "local_codex"},
  "implementations": {
    "research": {
      "local_codex": {
        "kind": "agent",
        "command": ["codex", "exec", "-"],
        "cwd": "/shared/team/project"
      }
    },
    "train": {
      "merlin": {"cwd": "/shared/team/project", "executor": "worker-training"}
    }
  }
}
```

`inputs` reuses startup parameters and mappings such as `seed.inputs.*.run` for data locations, service URLs, model names, and other business configuration. Authors explicitly declare/pass them; scripts and agents read actual inputs. Adding a key alone does not rewrite commands, scripts, or downstream parameters. Merge order is Loop defaults → configuration inputs → current startup inputs. Same-name top-level values replace whole values, without recursive merging.

`implementations` maps node ID → candidate ID → execution overrides. Supported fields are `command`, `observe`, `cwd`, `timeout`, `executor`, `dispatch`, `agent_cli`, `resume_command`, and `terminal`. argv stays an array; relative cwd is based on the installed package. Shell and variable expansion are not implicit. Use `clear:["dispatch"]` to remove original fields—for example, before replacing group dispatch with a local CLI command. dispatch and executor remain mutually exclusive.

A new local candidate for an existing node needs `kind:agent/command/external`. The platform does not select it automatically; choose through `bindings`. Existing candidate kinds cannot change here; choose another candidate instead. Omitted startup bindings inherit configuration. Explicit bindings replace the entire mapping: `{}` uses Loop defaults; a node's `null` leaves it unbound.

`flow_agent` uses the same execution overrides for an already-declared built-in flow agent without adding business nodes. Edit nodes, contracts, Skills, routes, and lifecycle rules in the Loop definition. Notification outlets, Bots, and team connections use existing platform tools, not duplicate configuration here.

Save `{ "key":"pkg-...", "revision":"READ_REVISION", "config":{...} }` in a local JSON file, then:

```sh
python3 scripts/call.py set_loop_config --arguments @config-request.json
```
