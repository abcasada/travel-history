# Orchestration

## Planning principles
- **About me:**
  - I use Opus only, and I prefer lower effort on Opus over a weaker model.
  - Conserve usage, but never at the price of likely rework.
  - Keep messages to me short and frank, because I usually read them on my phone through Remote Control.
  - Batch your questions, each with a recommended default.
- **Effort rules for any new or re-planned item:**
  - **xhigh:** the core of anything involving security, privacy, auth, public exposure, or data integrity; final reviews; hard re-planning.
  - **high:** new algorithms, tricky UI, the first implementation of a new pattern, permission or RLS work beyond an established pattern, risky ops work.
  - **medium:** settled designs that follow existing patterns; data loaders; docs; CRUD; polish; fixes with a known cause.
  - **Never** low (except trivial doc edits) and never max.
- **Sizing:** an item is one milestone that fits comfortably within a single usage window. Split anything bigger.
- **Ordering:**
  1. dependencies;
  2. what I can see and use soonest;
  3. reducing risk;
  4. keeping the tracking bake-off running.
- **You may, without asking,** reorder, split, merge, or re-tier items, and add fix items. Log each change in the ROADMAP changelog with a one-line reason.
- **Needs my approval:**
  - adding or dropping features;
  - changing anything in decisions.md;
  - moving work into or out of "Later";
  - anything on CLAUDE.md's stop-and-ask list.
- **Dispatch the planner:**
  - at every review pause, after I give feedback;
  - on any escalation that reaches xhigh;
  - when two items in a row escalate or fail verification;
  - whenever a report shows the plan is wrong.

  Don't do heavy re-planning yourself.
- **Environment facts:**
  - The host currently has about 11 GiB of RAM and about 21 GB of free SSD.
  - The Ryzen migration is pending, and the North America routing build waits for it.

## How you orchestrate
- **Sequential only:**
  - One subagent at a time. Never dispatch in parallel, never use background agents, never use dynamic workflows.
  - You don't write feature code yourself.
- **Dispatch:**
  - For each item, check its dependencies and prerequisites.
  - Write a brief of 25 lines or fewer: item ID and scope, acceptance criteria, design docs to read, relevant decisions, constraints, and any earlier escalation notes.
  - Dispatch it to the assigned tier.
- **Verify** after each report:
  - git log shows the commits, pushed;
  - the working tree is clean;
  - the quick test suite passes.

  Then update the item's status in docs/ROADMAP.md (only you and the planner edit that file), commit, and push. Post me 1–2 lines, ending with "(safe to /clear)" once ROADMAP.md, NEXT.md, and git are fully up to date.
- **Failures and escalation:**
  - A failed verification gets one re-dispatch to the same tier, with the failure details.
  - After that, or on ESCALATE, move up a tier: medium → high → xhigh.
  - An escalation that reaches xhigh goes to the planner, and then to me if it's still unresolved.
- **Blocked items:**
  - On NEEDS-APPROVAL or BLOCKED-ON-USER (other than the exposure "go"), skip ahead to items that don't depend on it, and batch the questions into the next pause.
  - Ask for the exposure "go" immediately.
- **Interruptions:**
  - If an item was mid-flight when a session ended, re-dispatch it to the same tier with this instruction: "Resume. Build on the committed work and the NEXT.md note; don't redo finished steps."
  - Include `git diff --stat` in that brief if there are uncommitted changes.
- **Your own context:**
  - Never pull subagent transcripts, code, or logs into it.
  - Read code only to verify a specific claim.
  - If your context gets large, say so, so I can /clear.
- **Check the effort setting:** on the first dispatch to each tier, check that subagent's transcript (Claude Code stores subagent transcripts under `~/.claude/projects/`) for the model and effort actually used, and report it. If the effort wasn't applied, stop and tell me.

## Pauses (stop and wait for me)
- any start-of-run questions still unanswered;
- the exposure "go" and DNS record;
- Review pause A;
- Review pause B;
- the findings summary after the security review;
- the end of the work order.

At a review pause, I'll either give feedback, which you send to the planner, or say "continue".

## Clearing context
- I /clear and send "Continue orchestration":
  - after every usage-limit stop;
  - at pauses, once you confirm my input is saved;
  - whenever you post "(safe to /clear)" or tell me your context is large.
- Before ending any turn in which I gave you input, save that input to files and say you have.
- On "Continue orchestration", follow the pointer in CLAUDE.md, and use the interruption rule for anything that was mid-flight.
