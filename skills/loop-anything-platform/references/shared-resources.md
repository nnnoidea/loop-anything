# Shared resources

Use `list_resources` to find resources on the connected platform. A registration has a stable ID, name, description, a directory or HTTP(S) URL, and the path or URL of its usage Skill. `read_resource(resource_id=...)` includes its published preview. The platform stores only this metadata. The registry neither opens links nor serves files from a registered directory.

## Register or update a resource

A platform operator with access to the database host runs `loop-anything --db /absolute/path/to/platform.sqlite3 set-resource resource.json`. The JSON file supplies `resource_id`, `name`, `location`, `skill` and `revision`. Readers use the **共享资源** page or the catalog's read tools. Use revision `0` to create, and the returned revision to update. Register paths as seen by the machines that will use them. A remote execution needs its own access to the directory or website and to the Skill entry. The executor maps declared paths inside its NAS team root using the existing mount configuration. Other directories need to resolve as registered.

An optional `preview` object lets the resource author publish selected content for people browsing the workbench. Use `summary` for a brief explanation, `facts` for small label/value pairs, and `sections` for grouped items with `title`, `text` and optional expandable `details`. Include versions or evidence scope where relevant. Omit preview when updating metadata to preserve it. Send an empty preview object to clear it. Refresh it when the source changes and the selected information needs updating.

## Use a resource in a Loop

Discover the resource ID and use `put_node` with `resources`, for example `["team-handbook"]`. The list replaces the node's existing references when supplied. The Loop package carries IDs. The executing platform resolves the current registrations when it prepares the task, and returns the metadata in `read_task.resources` and the execution context. Entries with `status=missing` indicate that the ID needs registering on this platform. An updated registration applies to subsequent reads and launches. The resource Skill can specify a source revision for reproducible analysis.

The node's instructions decide when the lookup matters. Read that resource's Skill and use its own entry points to retrieve relevant material. The original task remains responsible for its decisions and results.
