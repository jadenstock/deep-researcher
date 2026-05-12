# Jaden's Thoughts — Phase 0 Review

Captured while reading through the research sub-docs. Lightly cleaned, grouped by theme (thinking cross-cuts the sub-doc boundaries). Iteration happens at the end, not mid-stream.

---

## Theme 1: Planning & Intake

_(thoughts on 01-planning-as-commitment-or-suggestion, 02-vague-to-concrete-intake)_

### Plan as suggestion — strong preference

- Firmly in the plan-as-suggestion camp.
- Reference point: current research agent he's worked on spins up a set of tasks (with dependencies), then executes. Mid-execution it can delete tasks that are no longer relevant, edit them, or add new ones. That's the baseline behavior he wants.
- **Gap in current system:** no explicit "re-evaluate the plan" loop. Tasks get mutated reactively when something obviously changes, but nothing periodically checks whether the plan as a whole is still serving the goal.
- **Wants for this design:** a dedicated replanning step that runs periodically (cadence TBD) — an agent whose job is to review the current plan against the original goal and decide whether the decomposition still holds. Dynamic replanning throughout the session, anchored to the declared goal.

### Intake should extend into mid-research, not just pre-execution

- Agent should be able to ask the user questions — not all up front, also mid-research.
- Motivating example: agent is running, hits a branch point where there are 5 plausible directions. It should pause and ask the user: "narrow to one, or trace all five?" — rather than silently picking one or fanning out expensively.
- **Configurable interactivity as a design primitive.** Reference pattern from prior work:
  - Level 0 — "just do it," the agent decides everything.
  - Level 5 — ask the user frequently, check in at every branch point.
  - (intermediate levels between)
- Point is to let the user dial in how much oversight they want. Critical moment is "before it starts going off in directions that aren't useful" — the intake question isn't only at t=0, it's at every meaningful branch.

---

---

## Theme 2: Agent Boundaries & Communication

_(thoughts on 03-what-agents-should-share, 04-when-another-agent-helps)_

### Sub-agents are ephemeral, not personas

- Agrees with the core "share the plan" claim, nothing controversial there.
- **Shape of multi-agent he's imagining:**
  - A main/lead agent drives the research.
  - It spins out sub-agents on demand — "go investigate X" or "trace Y" — and those sub-agents are **ephemeral**, not long-lived personas (explicitly not the "Researcher-Reviewer-Writer-as-permanent-roles" pattern).
  - Sub-agents are task-scoped. They exist to do a thing and return.

### Shared workspace for sub-agent findings

- There should be a shared notes / workspace where sub-agents can write their findings, sources, etc.
- Not purely "return a summary to the parent" — there's a place that accumulates across sub-agent runs.
- This combines well with forked sub-agents / forked context as an isolation pattern — fork for clean context, write back to shared notes for persistence.

### Forked-context pattern is appealing — conditional on context management

- Likes the forked sub-agents / forked context pattern.
- Conditional clause: "**especially if we have good context management**" — suggesting the fork-and-summarize boundary is load-bearing, and if that fails the whole pattern doesn't pay off.

### No agent explosion — but verification is mandatory

- Explicitly opposed to agent explosion.
- Aligned with the **single-agent + isolated-context sub-agents** framing (from the research sub-doc).
- **Verification is a must-have pattern.** Even when there's only one primary generator, a second agent exists to fact-check or argue a counter-position.
- Adversarial framing is welcome — verifier's job could be "give me the best argument against this claim." Rounds of iteration are on the table.
- The two things he's committing to as mandatory: **(a) a verification layer, (b) slightly adversarial framing** inside that layer.

---

---

## Theme 3: Staying Honest — Verification, Conflicts, Hallucination

_(thoughts on 05-staying-honest)_

**This is the most interesting doc so far.** Likes both the documented failure modes and the countermeasures.

### Meta-orchestration: countermeasures as selectable patterns

- Key insight: **the failure modes and countermeasures described in doc 5 are effectively a menu of agent-orchestration patterns.**
- Rather than the system committing to one pattern globally, he wants **the system to be robust enough to select the right pattern for the current situation.**
- Example: one agent observes "this research is running into two competing claims" → spins up a specific agent pattern (e.g., debate, multi-perspective retrieval, adversarial critique) to resolve that specific conflict.
- Implication: there's a layer above individual agents whose job is **pattern selection** — picking the orchestration mode to match the current problem shape. Not fixed at system-design time.

### Source confidence tiering is load-bearing

- Strong interest in **source-tier / source-confidence scoring** as a core component.
- Repeatedly emerging as a theme. He sees it as an important part of the system — not an afterthought.
- Aligns with the corpus gap called out in the research: no existing source documents objective source-credibility algorithms, so this is also a design-novelty hook.

---

---

## Theme 4: Compute Allocation & Stopping

_(thoughts on 06-work-difficulty-and-compute, 07-stopping-criteria)_

### Rejects hard budgets (tool calls, rounds)

- Budgets like "max tool calls" or "max rounds" have never been useful in his experience.
- **Heuristic he actually uses:** if the agent is making progress and not hitting context limits, let it run.
- Hitting the context limit is not a stopping signal — it's a signal that **more context engineering work is required** (better summarization, better sub-agent offloading, better masking).
- Corollary: the stopping question becomes "are we making progress?" not "have we exhausted budget?" — which means the system needs a reliable progress signal. (Novelty-decay / new-claim-rate was proposed in the research doc; he hasn't commented on that mechanism specifically yet.)

### Loves difficulty-tiering — but for model selection, not for budgets

- The intake-time difficulty classification (lookup / synthesis / contested / sparse) lands well — **but repurposed.**
- Use it to assign **different model tiers** to different tasks, not different compute budgets.
- Cost + latency win: cheap models for the work that doesn't need frontier reasoning; expensive models where quality actually matters.
- **Explicit examples from him:**
  - Cheap model: summarizing tool call results.
  - Cheap model: straightforward lookups.
  - Expensive model: merging / synthesis across evidence.
  - Expensive model: generating claims / final report output.

### Concrete architectural vision: three-tier agent hierarchy

A specific hierarchy he's imagining, top-down:

- **Top tier — Manager agent.** Writes the overall roadmap. Receives only high-quality, synthesized results from below. Generates the final report.
- **Mid tier — "Sub-managers."** Take each subtask from the manager and assign it to a pool of researchers. Do the verification, synthesis, and merging of what comes back. Send results either back down to researchers (for more work) or up to the manager (when ready).
- **Bottom tier — Researchers.** Ephemeral. Go out, fetch literature, summarize results, produce citations. Pure data/claim/evidence gathering — no judgment, no synthesis.

Flow: user query → manager decomposes → sub-managers orchestrate researchers → sub-managers verify/synthesize → results bubble up → manager generates final report.

**Framing note:** he called this "just one idea" — offered as a concrete proposal, not a locked commitment. Worth probing in iteration whether the mid-tier is permanent-role (conflicting with his earlier "ephemeral sub-agents" preference) or ephemeral-per-subtask.

### Stopping is a progress-measurement problem

- Consistent with the budget-rejection position: stopping criteria are tricky precisely because "making progress" is the real signal and no one knows how to measure it cleanly.
- **Direction he likes:** marginal gain. If research agents stop finding new directions or novel/useful evidence, that's a stop signal.
- Stop decision is **collaborative between sub-agents and the main agent** — neither alone has enough information. Sub-agents know whether their current thread is still productive; the main agent knows whether the overall research goal is getting closer.
- System will need a concrete mechanism for measuring progress. (Novelty-decay on retrieved claim content was proposed in the research sub-doc; not yet endorsed or rejected here — worth probing.)

---

---

## Theme 5: Evaluation Without Ground Truth

_(thoughts on 08-evaluating-without-ground-truth)_

### Deferred — revisit after working product

- Generally agrees with the PQR / orthogonal-axes framework.
- **Explicit decision:** defer this until after there's a working MVP. Doesn't want to spend design time on LLM-as-judge mechanics right now.
- Evaluation design becomes a later iteration — probably informed by what actually breaks when the MVP runs on the assessment's test cases.

---

---

## Theme 6: Observability, Degradation, Continual Improvement

_(thoughts on 09-debugging-multi-agent, 10-graceful-degradation, 11-improving-without-retraining)_

### Debugging (doc 9) — mostly out of scope, one idea retained

- Full multi-agent observability as described in the research doc feels like "too much" for this scope.
- **One interesting idea surfaced:** a Git-like system for tracking changes to sources and state — appeals to him, not pursued yet.
- **Idea he's actually excited about: self-reflection loop.** After a run completes, an agent re-examines the entire trace and identifies which parts were dead ends, which tools were useful, etc. Could feed either the current report's confidence signals or the next run's prompt construction.
- Otherwise: not a priority for initial design.

### Graceful degradation (doc 10) — out of scope for initial design

- Sees the failure-class → response table as "fine and somewhat obvious."
- **His prior:** agents are pretty resilient in practice. Explicit degradation architecture can wait until something actually breaks.
- Revisit after a working system exists.

### Continual improvement without retraining (doc 11) — explicitly out of scope

- Out of scope for initial design and MVP.
- **Possibly worth discussing in the final presentation** as "what we'd build next" — not as something to implement.

---

---

## Cross-Cutting Thoughts

_(observations across the full pass — architectural instincts, scope decisions, MVP constraints)_

### Decision-making is per-context, not global

A consistent pattern across themes: he wants decisions to be made **at the right level for the specific situation**, not as fixed policies baked in at system-design time.

- **Model selection** — per-task, by difficulty class (doc 6).
- **Orchestration pattern selection** — per-conflict-shape, chosen at runtime by a higher-level agent (doc 5).
- **Replanning** — periodic, not reactive-only (doc 1).
- **Stopping** — collaborative judgment by main + sub-agents, based on progress signals (docs 6, 7).
- **User interaction** — at branch points throughout, not only at intake (doc 2).

This is the architectural north star: a system that makes intelligent decisions *in context*, rather than committing to one global policy.

### Trust the agent more than the scaffolding

- Rejects hard budgets ("let it run if making progress").
- Thinks graceful-degradation engineering is mostly unnecessary ("agents are pretty resilient").
- Doesn't want heavy observability infra.
- Leans toward "fewer guardrails, smarter agents" — opposite of the defensive-architecture position in the research.

### User is a first-class collaborator, not an escape hatch

- Configurable interactivity (L0-L5).
- Mid-research clarifying questions, not just at intake.
- The user isn't just a consumer of the final report — they're part of the loop when the agent faces meaningful branch points.

### Claim quality over system sophistication

Things he keeps returning to:
- Source confidence tiering.
- Verification with optional adversarial framing.
- Separating claims from evidence.
- Mid-tier agents do the verification/synthesis/merging work.

Contrast: he's less interested in orchestration-framework questions (which framework, which coordination pattern as a global choice) and more interested in **output trust**.

### MVP scope is clarifying

After this pass, the MVP cleanly targets **docs 1-7**: planning, intake, agent boundaries, verification, compute allocation, stopping. Docs 8-11 (evaluation, debugging, degradation, continual improvement) are explicitly deferred or descoped. This is a real scope win.

---

## Tensions & Open Questions (to resolve during iteration)

### T1: Ephemeral sub-agents vs. three-tier hierarchy

- Earlier position (Theme 2): sub-agents should be **ephemeral**, not long-lived personas.
- Later position (Theme 4): concrete three-tier hierarchy — manager / sub-manager / researchers.
- **Question:** Are the mid-tier "sub-managers" persistent role-holders (which contradicts ephemeral) or ephemeral per-subtask (consistent, but then why call them a tier)?
- **Possible resolution:** sub-managers are roles spawned per subtask and live only as long as that subtask, but the *role exists* in the system at all times. Worth making this explicit.

### T2: Budget rejection needs a concrete progress signal

- "Let it run if making progress" is clear, but the system has to detect "making progress" to operationalize it.
- Novelty-decay on retrieved claim content was proposed in the research. Not endorsed or rejected yet.
- **Question:** What does the progress signal actually compute on? New claims? New sources? Change in confidence on existing claims? The mechanism isn't specified.
- Without a concrete signal, "stop when progress stalls" collapses back into subjective LLM judgment — which is the weak mechanism the research called out.

### T3: Where does orchestration-pattern selection live?

- Wants the system to pick orchestration patterns at runtime based on problem shape (Theme 3).
- **Question:** Which tier makes this choice? If the manager agent picks patterns, it needs to know enough about the sub-task shape to choose. If sub-managers pick, the manager tier becomes light. Not specified.
- Related: is the list of available patterns a closed set (debate / maker-checker / multi-perspective / verifier-convergence) chosen by the selector, or can the selector compose patterns?

### T4: Interactivity slider — mechanics unspecified

- L0-L5 framing is clear in intent, mechanics are not.
- **Questions:**
  - Does the slider gate every branch decision, or only certain classes of branch?
  - When the agent asks the user, is it synchronous (block and wait) or asynchronous (queue question, continue on safe work)?
  - What happens if the user doesn't respond in a reasonable time?

### T5: Source confidence tiering — deterministic or learned?

- Clearly load-bearing; mentioned multiple times across themes.
- **Question:** Is it a deterministic rule table (peer-reviewed > preprint > engineering-blog > etc.) or learned from feedback?
- For MVP, deterministic is simpler and defensible. But he hasn't committed.

### T6: Verification rounds — termination criterion

- "Some amount of rounds of iteration" for adversarial verification.
- **Question:** When does the verification loop itself stop? Same progress-signal problem as the outer loop, now inside a verification sub-loop. Could be confidence delta, could be convergence on a verdict.

### T7: Self-reflection loop scope

- Likes the idea of end-of-run self-reflection on the trace.
- **Question:** Is this part of the MVP or a future enhancement? What minimum trace instrumentation does it require? If we need a Git-like source history for it to work, that's actually a lot of infrastructure that he otherwise descoped.

### T8: What observability is the minimum viable?

- He rejected heavy debugging infra but wants self-reflection.
- Self-reflection requires *some* structured trace.
- **Question:** What's the smallest set of logged artifacts (structured claims with provenance, agent call records, final report) that supports self-reflection without becoming "too much"?

---

## Tension Resolutions (Jaden, second pass)

- **T1:** All agents are ephemeral. Tiering is a property of **tasks** (low-level vs. mid-level), not of agent roles. A central agent spins up whatever it needs, including mid-tier agents, and those agents can themselves spin up sub-tasks / sub-agents. Persistent memory/context is deferred as an exploration after baseline.
- **T2:** Stopping is LLM judgment at the agent level, anchored on **task completion** as the progress signal. If research keeps pulling in more tasks/directions without closing any, that's scope creep → pause and escalate to the user ("keep looking, or narrow and list follow-ups?"). Mix of LLM-judgment + user-in-the-loop.
- **T3:** Patterns are a **closed set.** Task management is the unifying abstraction — agents spin up lower-level tasks, higher-level agents instantiate pattern-tasks (debate, maker-checker, etc.). Sync/async: prefer async when safe work can continue. User non-response → model always falls back to a default.
- **T4:** (Subsumed by T3's resolution.) Async-preferred; always a default fallback.
- **T5:** **Deterministic** source tiering. Simple ladder — random blog (low) / published preprint (pretty good) / peer-reviewed (very high). Rule-based.
- **T6:** Defer. Don't build for a problem that doesn't exist yet.
- **T7:** Self-reflection — out of MVP; revisit as follow-up.
- **T8:** Observability — build on top of a working baseline, not before it.

## Additional design requirement (surfaced here)

- **Search layer must be explicit in the TDD.** Low-level detail but load-bearing — needs concrete treatment, not hand-waving.
