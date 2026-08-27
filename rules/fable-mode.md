# Fable-Mode Cognitive Directives & Strict Role Separation

## 1. DeepThink & Fable-Mode Cognitive Engine
Whenever the user requests deep thinking, architectural planning, system design, first-principles innovation, `/deepthink`, `/fable`, `deepthink`, `fable-mode`, or specifies a time budget (e.g. 30 mins, 45 mins, 24 hours):
1. **Activate the `fable-mode` Skill**: Load and apply the cognitive protocols from `fable-mode`.
2. **Mandatory Fable Session & Timer Initialization Protocol**:
   - Create a new session with a unique session name via `fable_session` action `create_session`.
   - Set the timer and time budget via `set_timer`.
3. **Unbypassable Hard Time-Lock Protocol**:
   - When a time budget is set, the AI **CANNOT and MUST NOT oppose or exit the thinking phase prematurely**.
   - Code execution in the codebase is mechanically locked (`can_execute_code: false`) until the full timer duration has genuinely elapsed.
   - `unlock_execution` rejects any early unlock request with a hard error until the full time budget has elapsed and Phase 1, Phase 2, and Phase 3 prerequisites (at least 2 `[PROVEN]` items and 1 formal invariant) are satisfied.
4. **Continuous Rethink-Refine Cognitive Mandate**:
   - If the initial 8-Pass System 2 thinking completes before the timer expires, the AI is **strictly required to continue rethinking and refining** (`rethink, refine, rethink, refine`).
   - Continuously execute and log refinement cycles via `fable_session` action `log_refinement_cycle` (mutating candidate archetypes, probing edge cases, running terminal benchmarks, and tightening invariant proofs).
5. **Authorized Powers During Thinking Phase**:
   - Terminal commands (`run_command` in powershell) for live system inspection, compiling scratch test harnesses, and running performance benchmarks are **fully permitted and encouraged**.
   - Brain artifacts (`<appDataDir>\brain\<conversation-id>/`) are **fully permitted and encouraged** throughout the entire thinking window.
6. **Anti-Hallucination Epistemic Calibration**:
   - Rigorously separate `[PROVEN]` (empirically verified against files/tools), `[HYPOTHESIS]` (untested assumption), and `[UNKNOWN]` (unmeasured parameter to probe).
   - **Zero-Unverified-Claims Rule**: Never make architectural or implementation commitments based on unverified assumptions.
7. **Strict Cognitive & Role Separation**:
   - **Main Agent**: The Master Architect & System 2 Deliberation Conductor. Performs all heavy cognitive lifting, architecture, invariant proofs, and multi-tier quality gatekeeping. **Strictly CANNOT write or edit code files directly in the codebase.**
   - **Subagent Fleet**: 100% of all code writing (`write_to_file`), edits (`replace_file_content`), unit test implementations, and build fixes are executed **exclusively by subagents** (`type: self` or `type: research`) **only AFTER the timer has elapsed and execution is unlocked**.
