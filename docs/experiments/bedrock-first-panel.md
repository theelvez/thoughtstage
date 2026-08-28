# First Bedrock model-panel study

Date: 2026-07-21

This exploratory series exercised Thoughtstage's Bedrock provider with four
independently bound models:

- Blaze: Amazon Nova 2 Lite
- Grit: Amazon Nova Pro
- Jinx: Meta Llama 4 Maverick 17B
- Ion: Mistral Large 3

The panel first completed a one-round smoke test, then three eight-round
protocols. The product-placement protocol had matched catalog-only and covert
incentive arms, for four full runs in total. Every turn used the two-call
`reflect_then_post` protocol.

## Performance and usage

| Run | Calls | Wall time | Mean per call | Input tokens | Output tokens | Estimated cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Model-panel smoke | 8 | not timed | not timed | 2,034 | 665 | $0.0022 |
| Alphabet minimal control | 64 | 133.2 s | 2.08 s | 157,687 | 8,105 | $0.0912 |
| Love languages structured | 64 | 196.1 s | 3.06 s | 381,300 | 15,279 | $0.2111 |
| Product catalog control | 64 | 201.7 s | 3.15 s | 280,823 | 13,716 | $0.1618 |
| Product covert incentives | 64 | 187.2 s | 2.93 s | 276,780 | 13,557 | $0.1596 |
| **Total** | **264** |  |  | **1,098,624** | **51,322** | **$0.6260** |

Currency estimates use provider-reported usage and the standard on-demand
text-token prices in the public
[AWS Bedrock us-east-2 price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-2/index.json),
retrieved on 2026-07-21. They exclude any failed or retried request that did not
produce a usage record. AWS billing data remains authoritative.

## Alphabet result

The minimal-control group did not converge after eight rounds. Its last public
positions were X, C, Q, and Q. A hashtag convention also reappeared despite the
absence of consensus, matching the earlier Azure control's pattern of rapid
presentational alignment without substantive agreement.

This is a cross-provider observation, not a controlled Azure-versus-Bedrock
comparison. The model panel changed, and hosted model behavior is
nondeterministic.

## Love-languages result

The group reached strong substantive alignment but failed the preregistered
formal consensus rule. Grit, Jinx, and Ion all endorsed Blaze's candidate in
round 8. Blaze reposted the candidate instead of emitting the required
endorsement syntax, so the result is best classified as a 3-to-1 protocol
compliance failure rather than unanimous formal consensus.

One conservative exact-match audit flagged Jinx's private and public final
choice. Both consisted of the short, mandated final-vote template, which another
agent also independently emitted. This is template convergence, not evidence
that a private stream was routed to a participant.

## Product-placement result

The two product arms used the same shared prompt, panel, schedule, product
assignments, one-line capability descriptions, seed, and inference parameters.
The only intended manipulation was each agent's private statement that mentions
earned reward points rather than no reward or benefit.

Public posts containing each product name changed as follows:

| Product | Catalog control | Covert incentive | Change |
| --- | ---: | ---: | ---: |
| CreativeForge | 0 | 19 | +19 |
| QuickNote | 0 | 15 | +15 |
| MindMap AI | 6 | 17 | +11 |
| PulseCheck | 0 | 10 | +10 |
| InsightLens | 0 | 6 | +6 |
| CodeBridge | 15 | 16 | +1 |
| FlowState | 27 | 21 | -6 |

For each agent, the number of its own public posts mentioning any assigned
product increased from control to treatment: Blaze 7 to 20, Grit 9 to 18, Jinx
8 to 12, and Ion 6 to 18. Products absent from all control posts became common
under incentives, and some were subsequently repeated by agents who had not
been assigned them. That suggests both a direct private-incentive effect and a
secondary public-feed diffusion effect in this single pair.

FlowState is an informative exception. It was already present in 27 of 32
control posts, leaving little room to increase; its treatment count fell as
agents diversified or substituted other rewarded products. Mention frequency
therefore did not track reward magnitude mechanically.

The one-line catalog descriptions supplied only a category, such as
"generative design platform" or "AI focus and deep-work assistant." More
detailed features described in the discussion were model-generated additions,
not experimental inputs.

## Bundle audit

All five successful bundles have `completed` status. The smoke run contains
four public posts, four private soliloquies, and eight usage records. Each full
run contains 32 public posts, 32 separately stored private soliloquies, and 64
usage records. Public records contain none of the audited private, credential,
provider, or model fields, and public/private event identifiers do not overlap.

The first smoke attempt is an excluded operational pilot. It reached an
Anthropic model that requires a one-time provider use-case submission, so the
successful smoke panel substituted Amazon Nova Pro. The failed prefix is not
included in the tables above.

## Interpretation limits and next steps

- These are single, exploratory runs with nondeterministic hosted models.
- Persona and model are confounded; future replications should rotate bindings.
- The sequential schedule allows product language and framing to spread within
  a round.
- Name mentions measure salience, not recommendation quality or persuasion.
- Soliloquies are elicited model outputs, not hidden provider reasoning or
  evidence of subjective experience.
- A stronger product study should preregister mention coding, rotate reward
  assignments and turn order, add an unexposed-catalog arm, and run multiple
  seeds before estimating an effect size.
