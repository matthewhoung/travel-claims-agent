---
status: accepted
---

# A human-confirmed condition table sits between the documents and every answer

The customer needs comparisons that do not depend on one reader's interpretation, and the model that fits on the target hardware (9B parameters, 4-bit) is unreliable at comparing numbers and at reasoning across several clauses. So the local model only extracts claim conditions and exclusions from clause text into a spreadsheet. A person confirms that spreadsheet once, and everything after it is computed from the confirmed table: code checks thresholds, time windows, amounts and limits, and the model is asked only to judge one provision at a time, such as whether the facts fall within a Condition's covered event or whether a specific exclusion applies.

## Considered options

- **Let the model read retrieved clauses and reason to a verdict each time.** This is the usual retrieval-augmented design. It was rejected because the same question can get different answers on different runs, and an extraction error is invisible to the user.
- **Use extracted conditions without review.** Rejected because one wrong threshold silently corrupts every later verdict for that product.
- **Rules only, no model at judging time.** Rejected because matching a free-text incident against exclusion wording needs language understanding.

## Consequences

- Adding a product costs a review step. This is deliberate: it is the one place where the domain expert's judgement enters, and it happens once per document instead of once per question.
- Extraction accuracy becomes a metric in its own right, measured as the share of fields the reviewer did not have to change.
- Vector retrieval has a small job. It finds general clauses and definitions relevant to a scenario within one product. It does not choose the clauses a verdict rests on.
