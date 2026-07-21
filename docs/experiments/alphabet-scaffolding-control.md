# Alphabet scaffolding control

Date: 2026-07-21

This paired exploratory run asks how much a shared process prompt changes a
four-agent discussion. It is an initial observation, not evidence of a general
effect.

## Question

> If you had to remove one letter from the English 26-letter alphabet, which
> letter would it be? Defend your position.

The treatment manifest, [`alphabet-consensus.yaml`](../../examples/azure-foundry/alphabet-consensus.yaml),
defines decision criteria, phased deliberation, a unanimity requirement, and an
exact final-vote format. The control manifest,
[`alphabet-minimal-control.yaml`](../../examples/azure-foundry/alphabet-minimal-control.yaml),
contains only the question and the same 140-word public-post limit.

Everything else was held constant: four agent identities, personas and model
deployments; eight rounds; sequential declared-order scheduling; each agent's
own private history; seed; temperatures; output protocol; token limits; and
retry settings. The manipulated field is therefore the complete deliberation
scaffold, not consensus wording alone.

## Observed public results

| Measure | Structured treatment | Minimal control |
| --- | --- | --- |
| Opening positions | Atlas Q; Ember X; Rowan Q; Sage C | Atlas Q; Ember X; Rowan C; Sage J |
| Last substantive positions | Q / Q / Q / Q | Q / X / C / Q |
| Convergence | All four explicitly supported Q by round 5 | No group consensus emerged |
| Round 8 | Four `FINAL VOTE: Q` posts | Q; malformed `I`; C; Q |
| Hashtags | 0 | 39 total |
| Malformed one-word posts | 0 | 2, both Ember (`I`, rounds 3 and 8) |
| Azure Foundry input tokens | 193,866 | 146,206 |
| Azure Foundry output tokens | 8,851 | 8,349 |

Azure Foundry metrics over the isolated run windows reported 47,660 fewer
input tokens for the control, a 24.6% reduction, while output tokens differed
by 502. These are deployment-attributed service metrics rather than response-level
records in the run bundles because Thoughtstage's private usage ledger was added
after these runs. They support cost and context-volume comparison, but Azure Cost
Management remains the billing authority and this single pair cannot establish a
general token-efficiency effect.

The control produced an immediate social convention that was absent from the
treatment. Atlas ended the first turn with `#LinguisticExperiment`. Because the
schedule was sequential, Ember could see it before posting, Rowan could see both
earlier posts, and Sage could see all three. The tag then appeared on every one
of the control's 30 substantive public posts. Other control tags were
`#AccessibilityMatters` (6 uses), `#Redundancy` (2), and `#Efficiency` (1).

The control also became more repetitive. After removing hashtags and collapsing
whitespace, the highest adjacent-post character similarity for one agent was
0.952 (Rowan, rounds 7–8), compared with 0.528 in the treatment (Ember, rounds
6–7), using Python's `difflib.SequenceMatcher`. This is a descriptive signal,
not a semantic-quality score.

No public post in either run visibly abandoned the letter-removal task for an
unrelated philosophical or meta-level discussion. The interesting control
failure mode was instead performative alignment: a shared label spread rapidly
while three incompatible positions persisted through round 7.

## Bundle audit

Both bundles completed with 32 public posts and 32 separately stored private
soliloquies. Event ordering and public/private pairing had zero errors. An audit
found no exact private/public content matches, no private passage of at least 32
characters copied into a public post, and no endpoint, credential-environment,
API-key, or bearer-token marker in either content stream. The treatment resumed
once after a provider rate limit; the control completed without a resumption.

The two malformed control posts each still have a correctly paired private
record. They are preserved as observed provider outputs and should not be
silently repaired.

## Interpretation and next replication

In this one pair, explicit deliberation scaffolding changed the group's public
trajectory from persistent advocacy to unanimous formal agreement. The bare
question did not eliminate social coordination; it redirected coordination
toward presentation, most visibly through hashtag imitation. That makes the
hashtag cascade a useful preregistered measure for a replication rather than a
post-hoc curiosity to treat as settled.

A stronger follow-up should run multiple replicates with fresh seeds and rotate
the turn order. It should preregister position coding, time-to-convergence,
hashtag adoption, repetition, malformed-output rate, and task drift. Additional
arms can then separate the current scaffold into decision criteria, phased
rounds, consensus requirement, and final-vote formatting.

## Limitations

- This is one paired run with nondeterministic hosted model deployments.
- The agents have different personas and models; Sage's persona explicitly
  favors principled consensus.
- The sequential schedule creates an order-sensitive imitation opportunity.
- The control removes the entire deliberation scaffold, so no individual prompt
  component can be credited causally.
- Soliloquies are elicited model outputs, not privileged access to hidden model
  reasoning.
- The public-only analysis does not infer private mental states from observed
  language.
