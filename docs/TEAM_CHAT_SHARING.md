# How four teammates can use ChatGPT with shared context

## Preferred: a shared ChatGPT Project (when available)
1. Create a ChatGPT Project for `VantaWard — PauseGuard V2`.
2. Upload the latest canonical files from this kit (AGENTS, PRD, architecture, API contract, payment states, roles, decisions) to that project; never upload private secrets, real transactions or API keys.
3. Invite members through the product's sharing controls if that feature is available to your account; project members may be able to see shared chats/files. Only share appropriate project data.
4. Every teammate starts a **new conversation inside the shared project**, with the prompt below. Chats may branch; the shared repo, not chat, remains code authority.
5. After merging a new PR, update versioned project files in the shared Project or ask members to consult the new GitHub commit.

## If you only share this individual chat
A shared conversation link provides context from the conversation as of its shared snapshot, but it doesn't turn every teammate's subsequent chat into one synchronized live thread. Each member must upload/link the current canonical docs and say who they are. ChatGPT cannot automatically read their local Antigravity files.

## First message to use in every member's chat
> We are Team VantaWard building PauseGuard V2 from the uploaded Markdown architecture. Before continuing, ask me: Which member are you? 1 Komal, 2 Adish (Atish), 3 Gowtham (Gautam), 4 Jeevan (Jivan)? Then read `AGENTS.md`, V2 API and states and my member prompt. Explain my scope, the current project workflow, the next small approved step and required tests. Do not implement code, fetch external GitHub repositories or change our contracts until I approve a specific task. If you cannot access any file, say which file is missing. The GitHub repo and current PR—not this chat—are the source of code truth.

## Human control
This cannot make the model reliably act as a shared central manager without files, a repo connector, and human decisions. Keep signed-off architecture decisions in GitHub rather than relying on model memory.
