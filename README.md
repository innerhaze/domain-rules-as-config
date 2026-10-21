# Domain rules as configuration

Design notes on where operational knowledge about a specific domain lives inside a data pipeline. Written up from field experience building and maintaining an audit pipeline for geospatial point-of-interest data at a location-data company. The pipeline accumulated, over roughly two years, a body of rules that any new operator would otherwise have to learn by making the same mistakes the first ones made. The question these notes answer is: where should those rules live.

The focus is the pattern, not the specific rules. The same architecture applies to any pipeline whose correctness depends on domain knowledge that outsiders would not have, and that keeps growing as the pipeline encounters new cases.

## The problem

Operational pipelines accumulate knowledge in the form of corrections. A record is flagged as a false positive and an analyst spends ten minutes confirming the correction and writing it down. A country starts enforcing a new identifier format and existing records need re-parsing. A specific industry category is being used in two different ways by two upstream vendors and the pipeline has to pick one.

Each of those corrections is a sentence of operational knowledge. In isolation they are trivial. In aggregate they are the thing that separates a reliable pipeline from one that works only when its original author is present.

The reflex places this knowledge in one of three locations: an onboarding document; the model's prompt; or the operator's head. None of the three holds up over time.

**Onboarding documents rot.** Every rule written in prose has to be re-read by every new operator and re-applied to every new case. The rule is only enforced if the operator remembers it at the right moment, which over hundreds of records is a losing proposition.

**Prompts drift.** A rule added as a few-shot example to a language-model prompt becomes one more signal among many. The model may or may not apply it on a given record. The sampling audit from the companion write-up catches drift at the batch level but not at the per-rule level.

**Operator heads are a single point of failure.** The rule works until the operator who holds it leaves or forgets. The next person starts over.

The pattern that works is a fourth location: a registry of executable rules, each carrying with it the reasoning that caused the rule to be written, consulted by the pipeline before the language model is called.

## Executable registries

A registry is a module whose public interface is one function: does any rule in this registry apply to this record. For each rule the module knows the following things:

- the predicate that decides whether the rule applies to a given record
- the correction the rule prescribes if it does
- a short natural-language rationale: why the rule exists and what it is correcting for

A fuller version of the pattern also stamps each rule with the identifier and date of the incident that produced it, and [`example.py`](example.py) implements it that way to show the shape. The registry these notes come from did not go that far. It carried the rationale, and incident references lived in operator notes outside the repository. The scope note below says exactly where each kind of rule falls.

The registry is called before the language model. If a rule matches, the pipeline applies the correction, writes the rule's identity and rationale to the audit log, and does not call the model for that record. If no rule matches, the record proceeds to the model.

Two kinds of registry appeared in the pipeline these notes come from.

**Known miscategorisations.** A registry of chains and categories that had been mis-tagged a specific way by upstream classifiers, with the corrected classification. The rationale records what the mis-tagging looked like and the reasoning for the correction.

**Known false-positive patterns.** A registry of chains for which an earlier false-positive filter had been too aggressive, and had been removing records that should have been kept. The rationale records the shape of record that was being removed and why it should be kept.

Here is an actual entry from the registry's universal section, copied verbatim:

```yaml
universal_keeps:
  # Credit unions are a legitimate sub-category, not a miscat of bank/atm.
  - business_category_id: credit_union
    rationale: "credit_union is a legitimate sub-category under bank/atm/financial_institution; not miscat"
```

Three lines plus a one-line rationale and a one-line comment above the block. The rationale is terse on purpose: its job is to explain the keep-decision at reading time so a reviewer who did not write the rule can tell whether to trust it.

Scope note on this format: this is the universal-rules section, where each entry carries its own rationale. Per-brand entries are grouped under the brand key and share a group-level comment rather than an entry-level one. Specific incident references with dates and the record that caused the rule live in separate operator notes, not in the YAML or git history.

## Rules carry their rationale

The structural property that makes a registry pay off is that most rules carry their rationale alongside them, so a reader who encounters the rule later can tell whether it is still right. In the registry these notes come from, that rationale lives in two shapes: a one-line comment above each group of rules, and a per-entry `rationale` field in the universal section. Specific incident references, the record that caused the rule, the operator who caught it, the date, live in separate operator notes outside the YAML and the git history, so a reader who needs them has to go look rather than scroll.

This matters more than it sounds. A pipeline whose rules are opaque is a pipeline whose rules decay. An operator who does not know why a rule is there is one small refactor away from removing it as "unused" and reintroducing the defect the rule was there to prevent. A pipeline whose rules carry their intent, even just a short comment per group, makes that intent durable in a way bare rules do not.

The alternative, a changelog or a wiki with no link back to the code, fails because the connection between a rule and its justification is implicit. Six months later nobody remembers the wiki page exists.

## Market context as structured input, not as prompt

Pipelines that span multiple countries or regions encounter per-market rules that cannot be ignored and cannot be generalised: a country whose address format inverts street-first and number-first; a market where "holding entity" records masquerade as retail records; a region where upstream data coverage is weak enough that provisional records are a legitimate signal rather than noise.

The reflex is to put those rules in the model's prompt as a long multi-section preamble. That has the two failure modes already discussed: the model drifts, and the preamble grows past the point of usefulness.

The alternative is to carry market context as structured input. The pipeline looks up the country code of the record it is processing, loads the context record for that country, and hands the record and the context together to whichever layer needs them. The layer sees the market rule explicitly and the operator can read what the layer is doing per market.

The context record is a configuration file, not a sentence embedded in a prompt. It can be audited, versioned, and modified without re-tuning anything else.

## When the system must stop and ask

Not every record can be resolved by a registry and not every record should be handed to a language model. Some records require a human judgement call that no amount of local knowledge can shortcut.

The pattern that worked is an archetype attached to the record at intake time. A record whose archetype is "requires human review" skips every automation layer and goes straight to a punch-list for the operator to look at by hand. The archetype is derived from signals that are deterministic: the presence of specific metadata, the absence of required fields, the collision with a known structural pattern. Once set, no later layer may override it.

Example archetypes from the pipeline these notes come from:

- **Container with tenant collision**: a record that geometrically overlaps multiple records with incompatible names. Routing: human review.
- **Explicit holding-entity marker**: a record whose name matches a known holding-entity naming pattern. Routing: human review.
- **Novel cross-language name**: a record whose name uses a script the pipeline has not previously seen for this country. Routing: human review and registry addition for the new script.

The archetype is not a verdict. It is a declaration that this specific shape of record is one that the automated layers are not qualified to resolve, and that pushing it through them would lose information. The archetype routes the record and preserves the reason for routing in the audit log.

## What is not in a registry

A registry is a storage format for rules learned from past cases. It is not a format for rules that will apply to future cases that are novel in some way. New patterns go through the language model and the sampling audit. The registry grows when a pattern recurs often enough to be worth hand-coding, and when the case that would motivate the rule has actually occurred. Writing a rule in anticipation of a case that has not happened is premature; the registry fills with speculative rules that decay the way onboarding documents do.

A good indicator that a rule should move from "model-handled" to "registry-handled" is that the same correction has been applied by different operators across different runs on different records of the same chain or category. At that point the pattern is specific enough to encode.

## Limits of this approach

A registry is as good as its coverage of the cases it has seen. A new case the registry has not seen will still require the language model, and the language model is still what the companion write-up describes.

A rule in the registry that becomes wrong, because the upstream data source changed, because the real-world pattern changed, has to be retired. The rationale helps: a reader who can see why the rule was written can tell whether the correction still applies to the data as it exists today.

Registries also need their own form of review. A rule that fires on a record is a decision; a rule that fires on many records has an outsized effect. The pipeline logs every rule hit, and a periodic audit counts hits per rule and flags rules whose hit rate has jumped suddenly, which usually indicates an upstream change rather than a true pattern.

## Example

[`example.py`](example.py) implements a registry on a small synthetic dataset. A set of records is loaded. A registry of two rules, a known miscategorisation and a known false-positive pattern, is consulted before any language-model stand-in runs. Rules that fire write to an audit log that includes the originating incident identifier. Records that no rule matches proceed to a dummy LLM stand-in that routes some to accept and some to needs-review based on a signal the registry does not know about.

The example is deliberately small. The structure matches the production pattern.
