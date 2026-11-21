# Observe work without changing its business graph

A Loop can declare a map of named observations with set_loop(observations=...). A running Loop can acquire an observation even if its author did not declare one. Read the Timeline via read_observations(timeline_id); the Timeline page shows the same saved view and its arrangements. Imported business progress does not start any commands.

## Example: score comparison

With an authorized Run editing scope, call update_run_method with the run_id, execution token and the following observations patch. For a Loop default, use the same named definition on the draft, add the script as a package asset and publish it. For a new Run-local script use a path accessible on the executing machine.

~~~json
{
  "Score comparison": {
    "description": "Compare evaluation metrics within the same dataset",
    "on": {"kind": "state", "type": "experiment_result"},
    "steps": [{"kind": "command", "command": ["python3", "scripts/score_view.py"]}],
    "daily": "18:00",
    "timezone": "Asia/Shanghai",
    "notify_on": ["schedule"]
  }
}
~~~

Define the extraction script for the user's question. It can live in the Loop package or belong to the current Run. A single platform step can both select data and return a view. To render or analyze it on another machine, use the same observation with two steps. For example:

~~~json
{
  "steps": [
    {"kind": "command", "command": ["python3", "scripts/select_measurements.py"]},
    {"kind": "command", "executor": "team-worker", "command": ["python3", "scripts/draw.py"]}
  ]
}
~~~

These script names illustrate a user-authored arrangement. The platform step (no executor) receives the Timeline intent, trigger reference and a bound platform_client on stdin. Its script calls the service for the records it needs. For example, to select trial records:

~~~python
import json, subprocess, sys

context = json.load(sys.stdin)
args = {"timeline_id": context["timeline_id"], "type": "trial", "limit": 50}
points = []
while True:
    response = subprocess.check_output([sys.executable, context["platform_client"],
                                        "read_business_state", "--arguments", json.dumps(args)])
    page = json.loads(response)
    points.extend([r["id"], r["value"]["latency"]] for r in page["records"])
    if page["next_offset"] is None:
        break
    args["offset"] = page["next_offset"]
print(json.dumps({"points": points}))
~~~

Use read_work_results to page through formal result versions, or read_work_result for a known result ID. The bound client pins reads of this Timeline to the enqueue-time snapshot, including paging and first generation. Direct API callers can supply the corresponding as_of cutoff from context. A result/state trigger carries subject and revision (and type); request that exact revision to handle each event individually.

The executor receives package files referenced directly by command arguments. Declare additional imports or resources in the remote step's asset_manifest as package-relative files or directories. For a file needed conditionally, call read_loop(key, asset_path) through platform_client on the receiver. This requests one named file from the original platform.

The remote command or Agent reads that object under previous. Its other input fields identify the original Run, Timeline, Loop, platform and trigger reason (initial/manual/event/schedule); the receiver also supplies the package path when applicable. The full snapshot stays on the platform. A remote step placed first receives only execution metadata and can use data available on its own machine. Conditions run on the platform. On receipt or restart the workflow continues from its saved step output.

Each step writes one JSON object. An Agent step can use a prompt containing {{context}}. The final step returns the view:

~~~json
{"summary":"The candidate improved on dataset A. Dataset B is still pending.","series":[{"label":"A · candidate","points":[[1,72.1],[2,75.4]]}]}
~~~

Each point is [numeric x,numeric y]. Alternatively return image_png containing the base64 bytes of your own PNG, and/or summary text. Use the script to group comparable measurements. The platform imposes no research metric. Return notify=false to suppress an otherwise requested alert for this result.

## Triggers and delivery

- on matches fields of a committed fact. Omit it to watch result commits or use null for manual/time-only operation. Available kinds: result (node, type, subject=result ID, revision), state (type, subject=business ID, revision), task (node, subject=Task ID, status, previous), run (status, previous), current_run, run_deleted, monitor (subject=monitor ID), signal (subject=Hook name). A monitor may be explicitly selected from outside this Timeline on the same platform. A signal Hook uses action=signal, name, target, phase and frequency. The existing send_event is the directed input for a waiting Task.
- Use every (seconds) or daily plus timezone for scheduled refreshes. Event, schedule and manual triggers share the same steps. condition optionally uses the existing deterministic expression syntax against the observation input. each=true processes each matching event individually; by default outstanding event refreshes can be combined.
- notify_on selects event and/or schedule. The optional route field selects an existing notification outlet, such as a configured team Feishu channel. The default is the Run outlet. It sends the summary and, when configured, the Timeline web link. Set web_url to a team-accessible platform web address if the service has no public web URL. Initial generation and manual refresh do not send.
- Use refresh_observation(run_id, token, name) or the current-arrangement button to generate now. A failed generation leaves the last good view in place. After an unknown process outcome inspect it before explicitly confirming it stopped. Reading a Timeline never launches an observation.

## Update scope

update_run_method(run_id, token, observations={name: patch}) changes just this Run. A field patch overrides that field of the Loop default. An interval replaces a daily schedule and vice versa. If a published Loop removes a default arrangement, a Run still keeps its own arrangement when it has its own steps. Pass null for a name to stop that arrangement; inherit=[name] restores the Loop default. Publish reusable defaults with set_loop and publish_loop. Use key to apply an installed version of the same Loop once; follow=true opts into future explicit publications and follow=false pins the version. All preserve the Run ID. Existing tasks keep their original output contracts and routes; newly arranged business tasks use the effective method. To apply draft business changes only to this Run, export the draft, import the package on the original platform, then apply its key to this Run. Publishing is the step that also updates followers.

Publishing a metadata-only change keeps an observation's cursor, pending work and next scheduled time. When its steps or bundled assets change, the new view can render immediately. Deliveries already triggered for that arrangement finish with their original steps and notification route, even if the original executor replies late. Only the current generation updates the view. Explicitly disabling or removing the arrangement cancels its remaining generation work. A Run's disabled fallback or global Agent node stays disabled across method updates.

For an authorized Run-local edit, use acquire_run and call update_run_method with its token. Finish after the edit.
