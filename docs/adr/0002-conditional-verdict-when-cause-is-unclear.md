---
status: accepted
---

# When the cause is unclear, the verdict is conditional

Whether a travel-inconvenience claim is paid often turns on how the incident's cause is classified, and the clauses use terms such as 不可抗力 (force majeure) without defining them. When a scenario does not state the cause clearly, or the clause leaves the classification open, the system does not pick a cause. It returns an undetermined verdict that lists the outcome under each reading and names the clause the outcome turns on. An undetermined verdict always carries one of three reasons: the cause is ambiguous, the scenario lacks a fact, or the clauses are silent.

## Considered options

- **Have the model choose the most likely cause and give one verdict.** Rejected because this is exactly the subjective step the customer wanted removed, and it hides the point of disagreement.
- **Have the model rate its own confidence and escalate below a threshold.** Rejected because a small model's self-rated confidence is not a dependable signal, and "low confidence" tells the user nothing about what to check.
- **Pause and ask the user for the cause.** Deferred. It is a reasonable extension, and leaving it out keeps a question to a single pass.

## Consequences

- Evaluation needs a third outcome. Against a ruling from the ombudsman, a conditional verdict counts as "conditionally correct" when one branch matches the ruling and the clause it names is the one the ruling turned on. This is reported separately from accuracy.
- The share of undetermined verdicts is reported alongside accuracy, so the system cannot score well by declining to judge.
