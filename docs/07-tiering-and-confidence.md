# 07 — Tiering and Confidence

Source quality and calibrated confidence are two separate concerns
joined by a single backstop — the preliminary-anchor cap.

## Tiering

A **tier** is a 1–5 semantic quality score assigned at fetch time. The
tier is *semantic* — it reflects "does this source look and act like a
rigorous piece of evidence?" rather than "is it in a peer-reviewed
venue?" A well-cited rigorous preprint from a top lab can be Tier 1; a
press-release-style post from the same lab is Tier 3.

### The 1–5 scale (from `TIER_CLASSIFIER_SYSTEM`)

| Tier | Description | Examples |
|------|-------------|----------|
| 1 | Peer-reviewed primary research in reputable venues. Empirical data or formal proof. Reproducible methodology. | NeurIPS, ACL, Nature, IEEE S&P |
| 2 | Preprints with real methodology, peer-reviewed surveys, secondary academic writing. | arXiv, bioRxiv |
| 3 | Well-edited journalism, government/industry primary reports, authoritative technical docs, substantive practitioner blogs. | NYT, Reuters, official docs, standards bodies |
| 4 | Corporate blogs, opinion pieces, content marketing with some substance but light on sourcing. | — |
| 5 | Junk: unattributed aggregators, pure SEO, clickbait, social media, unsubstantive marketing. | — |

### Classification pipeline

**File**: `tiering/classifier.py`

Two stages:

1. **Deterministic reject list.** `_reject_list_tier(url)` matches
   against `REJECT_DOMAINS` from `tiering/simple.py`:

   ```python
   REJECT_DOMAINS = {
       "twitter.com", "x.com", "facebook.com", "instagram.com",
       "reddit.com", "tiktok.com", "youtube.com",
       "pinterest.com", "quora.com",
   }
   ```

   A match short-circuits to `Tier 5` with `confidence=1.0`. No LLM
   call, no cost. Tier 5 sources are not loaded into the corpus — the
   QS handler never creates a `source_note` for them (they fall out
   when `fetch.markdown is None`, which is typical for social media
   behind JS).

2. **LLM classifier.** For everything else, call `classify_source(...)`
   on the `cheap_deterministic / LOW` model (Haiku by default):

   ```python
   classify_source(
       title=...,
       url=...,
       snippet=...,
       content=...,                      # trimmed to first 2000 chars
       model_id=...,                     # cheap_deterministic LOW
       local=...,
       tracker=...,                      # per-run token tracker
   ) -> (tier, rationale, confidence, peer_reviewed)
   ```

### Classifier output

`TierClassifierOutput` (Pydantic model):

```python
tier: Literal[1, 2, 3, 4, 5]
rationale: str                 # 1-2 sentences, cites signals
confidence: float              # 0..1
peer_reviewed: bool            # strict
```

The signal the classifier reads is *rigorous*: venue, methodology
section, citations, author credentials, publication date, evidence
density. The prompt is explicit that topical relevance is not the
classifier's job — a rigorous paper on the wrong topic is still
Tier 1. The analyzer's `off_topic` flag handles relevance.

### Failure behavior

LLM failure → default to `Tier 3, "classifier failed; default to
generic web tier"`, confidence 0.2, `peer_reviewed=False`. The source
stays in the corpus, and downstream confidence math treats it as
generic web content with low classifier confidence.

### Caching

The classifier runs per `QUESTION_SYNTHESIZE` call for every usable
source. There is no classifier-level cache — identical URLs seen in
different QS runs re-invoke the classifier. Content fetches above
are cached day-bucketed by `RetrievalCache`; the classifier output
is not.

## Peer-reviewed status

Separate boolean on every `source_note` (`peer_reviewed: bool`). The
classifier is **strict** about this flag:

- `True` ONLY for formally peer-reviewed publications (major journals,
  recognized peer-reviewed conference proceedings).
- `False` for preprints (arXiv), blogs, government reports, journalism.

Independent of tier. A Tier 1 preprint from a top lab is still
`peer_reviewed=False`. This independence is load-bearing for the
confidence formula's cap — see below.

## Confidence formula

**File**: `confidence.py`

Given a `ConfidenceInput`:

```python
@dataclass(frozen=True)
class SourceEvidence:
    tier: Tier
    peer_reviewed: bool
    citation_count: int

@dataclass(frozen=True)
class ConfidenceInput:
    supporting: list[SourceEvidence]
    refuting: list[SourceEvidence]
    triangulation_score: float    # 0..1
```

The math (`compute_confidence`):

```python
base = max(TIER_WEIGHT[s.tier] for s in supporting)
                               # TIER_WEIGHTS = {1:0.90, 2:0.75, 3:0.55, 4:0.30}

agreement_bonus = min(0.10 * (len(supporting) - 1), 0.30)
max_cites = max(s.citation_count for s in supporting)
citation_signal = min(log10(max_cites + 1) / 5.0, 0.10)
contradiction_penalty = 0.20 if refuting else 0.0
triangulation_bonus = triangulation_score * 0.10

raw = base + agreement_bonus + citation_signal
    + triangulation_bonus - contradiction_penalty
raw = clamp(raw, 0.0, 1.0)
```

Individual terms:

- **Base (tier-weighted)**: best supporting tier sets the ceiling.
- **Agreement bonus**: up to +0.30 when many sources agree.
- **Citation signal**: mild log-scaled bonus for well-cited sources,
  capped at +0.10.
- **Triangulation**: up to +0.10 for cross-vector independence (see
  below).
- **Contradiction penalty**: flat −0.20 when any refuting source exists.

### Preliminary-anchor cap

```python
if primarily_preliminary and raw > 0.80:
    raw = 0.80
    capped = True
```

`primarily_preliminary` is True when a majority of supporting sources
have `peer_reviewed=False`. The cap at 0.80 (Moderate ceiling, never
High) is the **load-bearing backstop**: even if the tier classifier
over-tiers a rigorous-but-not-peer-reviewed source, confidence cannot
cross into High. This is the guard that lets tiering be semantic —
the structural guarantee of not overclaiming comes from
`peer_reviewed`, not from the tier.

### Output

```python
@dataclass(frozen=True)
class ConfidenceResult:
    value: float              # 0..1
    band: ConfidenceBand      # "High" / "Moderate" / "Low"
    primarily_preliminary: bool
    capped: bool              # True if the cap was applied
```

### Language ladder

```python
band_of(value):
    v >= 0.80 -> "High"
    v >= 0.55 -> "Moderate"
    otherwise -> "Low"

BAND_QUALIFIERS = {
    "High":     ("almost certainly", "highly likely",
                 "we assess with high confidence"),
    "Moderate": ("likely", "probably", "we assess"),
    "Low":      ("possible", "unlikely", "remote"),
}
```

The report always renders both a numeric value and a standardized
phrase. `render_confidence_tag(result)` produces a short caveat
suitable for appending after a claim:

```text
*(Moderate confidence, 0.74; primarily preliminary evidence.)*
```

The full Analytic Pyramid render is the WRITE_REPORT prompt's
responsibility; `confidence.py` is the single source of truth for the
numbers that feed it.

## Triangulation

The `SynthesisMetadata` carries two proxies for independent
corroboration:

- `triangulation_score`: count of distinct sources that contributed at
  least one claim to the synthesis.
- `distinct_tiers`: number of distinct tiers those sources span.

Both are computed inside the QS handler after analyzer runs and
before the synthesis_note is written. `triangulation_score` is the
count of `enriched` source_notes whose `claims` list is non-empty;
`distinct_tiers` is the size of the set of tier values across those
sources.

The `VALIDATE_COMPLETION` prompt reads both fields alongside the
synthesis body when auditing Gate 6 ("load-bearing claims should have
support from more than one source, or from one exceptionally strong
source e.g. Tier 1 peer-reviewed").

## Flow summary

```
       fetch_and_extract(url)
               │
               ▼
        markdown present?
               │
        (yes)  ▼
     _reject_list_tier(url)
               │
       match? ─┴─ no → LLM classify_source(...)
               │                   │
               │                   ▼
               │        (tier, rationale, conf, pr)
               │
               ▼
     SourceNoteMetadata.tier / tier_rationale /
       classifier_confidence / peer_reviewed

       ... later, synthesis time ...

  ClaimItem.verification_status ∈ {UNVERIFIED, SUPPORTS, REFUTES, INCONCLUSIVE}
       (set by VERIFY_CLAIM cross-family verifier)

       ... later, report time ...

  compute_confidence(supporting, refuting, triangulation_score)
       → (value, band, primarily_preliminary, capped)

  render_confidence_tag(result)
       → "*(Moderate confidence, 0.74; primarily preliminary.)*"
```

The chain is the answer to "how does this system avoid overclaiming":
three orthogonal signals (tier, peer-review, verification verdict)
feed a single formula whose ceiling is capped by the one signal that's
structurally reliable (`peer_reviewed`).
