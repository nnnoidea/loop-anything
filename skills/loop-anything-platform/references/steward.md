# The current Agent is the Run steward

Any server Agent with the platform Skill can converse, inspect information and
work. The Agent that actually calls start_run becomes that Run's steward.
There is no mandatory named-agent selection or new conversation for startup.

See [persistent work](work.md) for session registration, start_run, claim_run,
Timeline changes, interruption recovery and cross-Run waits.

The business handbook and node instructions remain authoritative for methods.
Business node completion returns to the bound session by default. Explicit
rules/routes retain their progression. Claim pending management work using the
same session identity; complete its decision output and finish. Current session
tokens are distinct from a Run's scoped execution tokens.

submit_run_request can deliver subsequent questions or authorized requests to
the bound session. It persists the request and returns a receipt; read it with
read_run_request. Reply to a question with reply_run_request. Do not use a
request as a shortcut to start a separately selected named steward.

Timeline objective/constraints changes use update_timeline, not change_settings.
Follow its check notice and report the result to the user; no automatic
scheduling freeze or unrequested task changes.

Named agents remain available for capability sharing and assistance. They are
not a prerequisite to becoming a Run steward.
