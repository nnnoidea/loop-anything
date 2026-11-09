---
title: Loop workflow
subtitle: Replace with this Loop's goal
template: sheet
cols: 1
theme: paper
lang: en
---

## Workflow overview

```flow TB
(Clarify goal) -> Plan work: exploration needed
Clarify goal -> Execute work: plan already known
Plan work -> Execute work: submit parameters
Execute work -> Analyze results: results ready
Analyze results -> Plan work: another round
Analyze results -> (Done): goal achieved
```

## Continuation and completion

Replace the example with real business nodes and relationships. Show every declared node, including initialization, optional branches, and recovery. Never replace several real nodes with one aggregate box. Explain how later rounds are arranged, what ends the Run, and who handles exceptions.
