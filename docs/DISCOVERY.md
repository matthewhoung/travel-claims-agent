# Discovery

This document records where the project's requirements came from. It was written on 2026-09-30 from notes of an informal conversation with a property and casualty actuary. It is not a transcript, and the actuary's employer and working documents are deliberately left out.

## Who has the problem

A property and casualty (產險) actuary who works on travel-inconvenience insurance (旅遊不便險). Part of the job is market research: collecting the claim conditions that different insurers offer, comparing them, and using the result as input to a pricing model.

## What the work looks like today

The actuary reads each insurer's clause document, works out what each product pays and under what circumstances, and lines the products up by hand. Two questions come up again and again:

- For a given situation, which products pay and which do not?
- Where do the products' conditions differ, and where do two conditions pay for the same event?

## Why it is hard

- **It is slow.** Clause documents are long, several products are often bundled in one file, and the same article number means different things in different products.
- **It is subjective.** Whether a situation is paid often depends on how the cause of the incident is classified, such as the traveller's own fault versus force majeure (不可抗力). Two readers can classify the same incident differently and reach different answers. The actuary wanted a comparison that does not depend on one person's reading.

## The constraint

The actuary's working documents are unpublished drafts. They cannot be uploaded to a cloud service or sent out through any API. Whatever is built has to run entirely on a local machine with no outbound traffic.

This is why the project is local. It is the customer's constraint, not a design preference.

## What was asked for

An agent that can take clause documents, help compare the claim conditions in them, and answer what is and is not paid in a described situation. The actuary agreed that the work could be published as a portfolio project, provided the real documents stay private.

## What the request turned out to mean

Two words in the original request needed unpacking.

| Word used | What it meant | How the project handles it |
|---|---|---|
| 相依 (dependency) | The answer depends on how the incident's cause is classified, and that classification is open to interpretation. It did not mean one condition depending on another. | The system does not pick a cause on the user's behalf. When the cause is unclear, it shows the outcome under each reading and names the clause the outcome turns on. |
| 重疊 (overlap) | Two things: the same benefit differing between insurers, and one incident triggering more than one condition in the same product. | These are treated as two separate relationships, called Alignment and Overlap in [CONTEXT.md](../CONTEXT.md). |

## What the public documents showed

Because the real drafts cannot be used, the project works on public clause documents from Taiwanese insurers. Reading them changed the problem in four ways.

1. **Insurers share one template.** The regulator publishes reference clauses for overseas travel-inconvenience insurance, and the industry association's Q&A states that each insurer's cover and clause text must match them. Products differ much less in wording than expected.
2. **The wording changed in 2026.** An old version took effect on 2022-09-01 and a new one on 2026-04-01. The new flight-delay exclusions add, for example, a sea typhoon warning already issued when the policy was bought. Old and new differ more than insurers do.
3. **Amounts are not in the clauses.** Clauses say only that the insurer pays "the amount stated in the policy". Amounts are published per plan on insurers' websites, in a different layout at each insurer, and only four of the eight insurers surveyed publish them at all.
4. **Flight delay does not list covered causes.** A delay of four hours or more is paid whatever the reason, and the term 不可抗力 is used without being defined. Cause appears in the exclusions, and in the old wording also in the rule for measuring the delay: if force majeure prevented the traveller from taking the first replacement flight, the delay runs to the next one. That is where the subjectivity lives.

The project therefore compares along two axes: old versus new wording, and benefit amounts across insurers.

## What is not yet known

These points have not been confirmed with the actuary.

- **How long the manual comparison takes.** Without this number the project can report technical accuracy, not time saved.
- **Whether the two comparison axes are the ones that matter most.** They were chosen from the public documents, not confirmed by the actuary.
- **Whether plans sold offline matter.** Only online plans publish their amounts.
- **The hardware it will finally run on.** The project is developed and measured on one laptop with an 8 GB GPU.

## How the actuary is involved

The actuary described the problem and will be the first user. The actuary does not label data or grade results. Expected answers in the evaluation come from public third-party sources, which are listed in [data/SOURCES.md](../data/SOURCES.md).
