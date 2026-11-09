# How different AI models cooperate without sharing a chat session
1. **Read:** GitHub `main` + canonical docs, then current assigned branch and member-specific instructions.
2. **Identify:** The human selects member 1–4. Never infer from the laptop account name or a previous pasted conversation.
3. **Plan:** AI lists exact files in scope, endpoints, typed inputs/outputs, risks, and tests. Human approves.
4. **Implement:** One small, bounded task; AI can inspect approved reference repositories after explicit permission. Do not autonomously fetch every repo or install entire agent frameworks.
5. **Verify:** run tests, record failures truthfully, inspect Git diff, lint/typecheck, review security and privacy invariants.
6. **Handoff:** PR with exact interface changes, logs, blocker and any changes required from teammates.
7. **Merge:** core contract review by Komal and Adish; Jira/project management optional. Other models re-read latest docs before future tasks.

## Session start question
"Which team member are you? 1 Komal, 2 Adish/Atish, 3 Gowtham/Gautam, 4 Jeevan/Jivan?"
Then say: "I will act only within your team's role and won't assume your project files are accessible unless you provide a local workspace or a connected repository. Here is my understanding of your assigned scope...".

## AI autonomy policy
AI can *propose* open-source source code and request approval to retrieve it, but must inspect and record its license, commit SHA and integration risk. Do not execute third-party setup scripts, grant broad permissions, disable security checks, use `curl | bash`, or access billing/production systems automatically.

## Portability
Antigravity: project `.agents/rules` and `AGENTS.md` on workspace. OpenCode: use same docs and explicit role prompt; its own agent discovery may differ. ChatGPT: paste or attach kit, share chat for narrative only; individual new chats don't automatically inherit other people's updates.
