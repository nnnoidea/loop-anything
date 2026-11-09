# Parameter contracts and stable task references

Read `read_capabilities` for `conditional_contracts` and `task_refs`. The live `list` schemas are authoritative; resolve service/documentation version differences first.

## One parameter contract across entry points

Node `parameter_schema` declares shared parameters; candidate `parameter_schema` declares implementation requirements. Creation, preview, editing, retry, and execution use the same validation. One parameter object must satisfy both contracts. Defaults are not injected, types are not coerced, and fields are not filtered. Implementations translate parameters into actual commands.

The supported JSON Schema subset is returned by `read_capabilities.schema_keywords`:

- `type`: object, array, string, number, integer, boolean, null, or an array of these types.
- `properties`, `required`, `additionalProperties` (boolean or schema), `items`, `dependentRequired`.
- `oneOf` (exactly one match), `anyOf`, `allOf`, `not`, `if/then/else`. Branch schemas may omit type.
- `enum`, `const`, numeric bounds including exclusiveMinimum/exclusiveMaximum, string length/pattern, array length/uniqueItems, and object property counts.
- `title`, `description`, `default`, `examples`, `format` are descriptive. A supplied default is validated but never filled into runtime parameters. Format does not prove a file exists or satisfies a format. The existing nonempty extension remains supported.
- Boolean schemas true/false accept/reject all values. Unlisted keywords, including $ref, $defs, and patternProperties, are rejected explicitly.

For example, `set_implementation.parameter_schema`:

```json
{
  "type":"object",
  "properties":{
    "mode":{"enum":["existing","build"]},
    "source":{"type":"string","minLength":1},
    "preset":{"type":"string"},
    "template":{"type":"string"}
  },
  "required":["mode"],
  "if":{"properties":{"mode":{"const":"existing"}},"required":["mode"]},
  "then":{"required":["source"]},
  "else":{"oneOf":[{"required":["preset"]},{"required":["template"]}]},
  "additionalProperties":false
}
```

This rejects existing without source, build with both or neither preset/template, and undeclared fields. `required` in a condition matters: properties alone does not require presence.

Before creating a Task, call `validate_parameters`:

```json
{"draft_id":"DRAFT_ID","node_id":"work","implementation_id":"local","parameters":{"mode":"build","preset":"small"}}
```

An installed key can replace draft_id. It returns `valid/errors/implementation_id` without creating work. Validation helps fix missing fields; business parameter choices still follow user intent and the author Skill.

## Stable task references

Set step `ref`, such as `"work:{item.id}"`, to an author-chosen name unique across the Run. It is neither a display round nor a scheduling entity. Include the round for repeated work, for example `"{values.round}:work:{item.id}"`.

```json
{
  "node":"work", "each":"jobs", "inputs":{},
  "parameters":{"$":"item.params"}, "ref":"work:{item.id}"
}
```

An aggregation step can reference business items directly:

```json
{
  "node":"review", "ref":"review:{values.id}",
  "after_refs":{"$":"values.members"},
  "inputs":{"results":{"task_refs":{"$":"values.members"},"port":"result"}}
}
```

For values `{"id":"selected","members":["work:A","work:C"]}`, after_refs resolves to actual Task IDs and task_refs to the corresponding result records in members order.

- `task_ref` reads one task's output; `task_refs` collects the same output port from several tasks. Both pin producer-declared output versions by default, avoiding later overwrites of the same record. Explicit path/revision is allowed; explicit revision wins.
- Ordinary records sources can supply a revisions array, one positive integer per record, instead of revision. This requires record_versions support and also represents task-reference collections spanning different versions. Definition and task-relationship views preserve the versions.
- `after` references steps in the same template; `after_refs` references explicit task names. Both resolve to ordinary dependencies, not another task-group state machine.
- Forward references are supported within a plan and across all routes/each batches in one accepted report, independent of rule order.
- Independent build_plan/add_task calls may reference tasks created in that call or already in the Run, not tasks that a future call may create. Use routes on the same report for cross-rule forward references.
- Missing references, duplicate names, unknown ports, and dependency cycles reject the entire submission. Omitted steps create no referencable placeholder; consumers must explicitly reuse valid inputs or also be omitted.
- Resolved references stay bound to Task/record identities. Cancellation does not rebind a name; replacement work uses a new ref.
- `build_plan` and route receipts return name-to-Task/output mappings in references. Query them through read-only `resolve_refs`, e.g. `{"run_id":"RUN_ID","refs":["work:A"]}`; omit refs for all. A supplied token retains scope checks.

Direct `add_task` supports ref, after_refs, and these input sources. For existing Runs, use `edit_tasks(preview=true)` for grouped edits. Atomic groups execute in order; later operations may reference tasks created earlier in the group.

## Expansion preview

`preview_plan` expands a template from a draft or installed version without creating a Run or starting commands:

```json
{"draft_id":"DRAFT_ID","name":"work","batch_key":"preview-1","values":{"jobs":[{"id":"A","params":{"mode":"build","preset":"small"}}]}}
```

It returns tasks, references, and omitted, validating node/effective-candidate parameters and actual dependencies. Optional steps, bindings, and round are accepted. There is no existing Run, so real Run tasks cannot be referenced. Use [scenario testing](testing.md) to verify business expectations.
