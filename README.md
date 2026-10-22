# Orchestrator

A local browser app for working with files through an AI agent. Connect a project folder, describe a task, and follow the agent's commands and results in a persistent chat. The backend uses FastAPI and SQLite, the interface uses React, and agent commands run in a Docker sandbox.

Orchestrator supports Login with ChatGPT, OpenAI API keys, and configured Azure OpenAI deployments. Available models and tools depend on the selected connection.

**The agent edits your original project files.** Docker shares the selected folder as `/workspace`; changes are visible on the host immediately. Checkpoints provide per-run diffs and Undo for supported files, but are not a replacement for backups or version control.

## Requirements

- macOS or Linux. Native Windows is not supported.
- Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), and Git on the host.
- Node.js 20 or newer and npm.
- Docker Desktop or Docker Engine, installed and running.
- An eligible ChatGPT connection, an OpenAI API key, or an Azure OpenAI deployment with credentials.

The sandbox runs CPU workloads. Its default limits are 4 CPUs and 8 GiB of memory; adjust these in `.env` to suit your Docker environment. The initial image build downloads a substantial set of document-processing and analysis tools.

## Quick start

### 1. Get the source and create configuration files

```sh
git clone https://github.com/takumi0shibata/chat-orchestrator.git
cd chat-orchestrator
cp .env.example .env
cp runtime.example.toml runtime.toml
```

Edit `runtime.toml` and replace the example workspace with an **existing absolute directory**:

```toml
[[workspaces]]
id = "project"
label = "My project"
path = "/absolute/path/to/your/project"
```

Use a folder containing files you want the agent to work on. Workspaces must not overlap. Keep this application's source, configuration, credentials, and state outside all registered workspaces. Do not use `~` or a relative path in place of an absolute directory.

`.env` and `runtime.toml` are local configuration files and are excluded from Git. Never commit credentials or application data.

### 2. Install dependencies and build the sandbox

Run these commands from the repository root:

```sh
make setup-backend
make setup-frontend
make sandbox-build
```

Confirm that Docker is accessible with `docker info` if the image build fails. Rebuild with `make sandbox-build` after changing the sandbox image definition.

### 3. Start the app

Keep two terminals open, both in the repository root:

```sh
# Terminal 1
make dev-backend
```

```sh
# Terminal 2
make dev-frontend
```

Open [the chat interface](http://127.0.0.1:5173). The backend's [interactive API documentation](http://127.0.0.1:8000/docs) is available on port 8000.

Use one backend process on the host. Multiple workers and two processes sharing the same data directory are not supported. The frontend uses port 5173 and fails if that port is occupied; moving it to a different port does not update the backend's allowed origins. Restart the backend after changing configuration or credentials, after letting active runs finish.

### 4. Connect a provider

Choose one of these paths:

| Connection | Setup |
| --- | --- |
| Login with ChatGPT | API keys may remain empty. In the app, open **Settings → General → ChatGPT connection → Continue with ChatGPT**. Complete sign-in and plan-access consent in the browser. Then choose **ChatGPT** under **+ → Provider** in a new chat. Eligibility depends on your account and workspace policies. |
| OpenAI API | Set `OPENAI_API_KEY` in `.env`, restart the backend, and select OpenAI in a new chat. API requests are billed to that account. |
| Azure OpenAI | Set `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_API_KEY` in `.env`, register your deployment in `runtime.toml`, and restart the backend. Only configured, available deployments appear in the selector. |

For the default Azure connection, a deployment entry looks like this:

```toml
[[azure_models]]
model = "gpt-6.1-sol"
deployment = "your-actual-deployment-name"
```

`model` identifies a supported underlying model; `deployment` must match the name you deployed on Azure. For multiple Azure resources, use the `azure_connections` and `connection_id` examples in [runtime.example.toml](runtime.example.toml). Store secret values in `.env` or the backend environment, never in the TOML file.

A chat keeps its provider and Azure connection binding after its first run. Start a new chat to change providers or Azure resources. You can change models within the same connection. Orchestrator does not silently switch to another provider when a request fails.

**Title generation has its own provider setting** under Settings → General. If you configure API keys but intend to use only ChatGPT plan usage, select ChatGPT for the title model as well. ChatGPT plan usage and API billing are separate; remote MCP is unavailable on the ChatGPT plan connection. See [ChatGPT connection details](docs/chatgpt-login.md) for capability and authentication details.

### 5. Send your first message

1. Choose your project in the sidebar and click **New chat**.
2. Select a model and reasoning effort using the combined model control in the composer. Set optional tools from the **+** menu.
3. Start with a read-only request, such as: “List the files in this project and summarize what you find. Do not edit any files.”
4. Send with **Enter** or the send button. Use **Shift+Enter** for a newline.
5. Expand the activity entry to inspect commands, output, timing, and exit status. The answer appears below the activity.

When you want an edit, name the file and the result you need. Review the answer and any changed-file card before using the result. Refresh **Files** to see the current contents of the project folder.

## Everyday use

### Chats, files, and attachments

- Switch chats without stopping an active run. Runs continue on the backend if you close the browser; reopen the chat to reconnect to its history.
- Draft text and attachments are kept separately for each chat while the page remains open. They are cleared after a successful send or chat deletion. Reloading or closing the page discards unsent drafts.
- Search titles, user messages, and answers from the sidebar. Search terms are combined with AND; quotes preserve a phrase. Matching ignores case, full-width variations, and common Markdown formatting. Command output is not searched.
- Pin a chat to keep it near the top. Deleting a chat removes its app history, not its project files. Its stored attachments remain available for orphan cleanup in Settings → General → Storage.
- Open **Files** to browse the workspace, download results, or edit supported UTF-8 text files up to 1 MiB. **Save** writes to the original file; revision checks reject stale saves. You cannot save while an agent run holds that workspace.
- Drag a workspace file or folder into the message box to insert its relative path. Drag external files into the chat, or use the attachment control, to upload them.
- Uploaded originals are read-only under `/input/<attachment-id>/<filename>`. The upload limit defaults to 50 MiB per file. Direct model attachments are available for supported PNG, JPEG, WebP, and PDF files, up to 20 MiB each and 40 MiB per turn; direct attachment sends that content to the provider.
- Download result links from an answer, such as `[Report](<sandbox:/workspace/my report.docx>)`. Results must actually exist in the project folder. The file APIs reject paths outside the workspace and symbolic links.

Markdown answers support inline and display mathematics using bundled KaTeX assets. This renders equations in chat; it does not compile complete LaTeX documents into PDFs.

### Stop, changes, and Undo

**Stop** cancels the run and stops its sandbox. Changes already written remain on disk; stopping or failing a run does not automatically roll them back. Runs in the same workspace are serialized, while different workspaces can run concurrently.

When checkpoints are available and a run changes covered files, its answer includes a changed-file card. Expand a file to inspect the diff, or use **Undo** to restore the files changed by that run. Files created by the run are removed during Undo. If a covered file changed again afterward, Orchestrator asks before overwriting it. Undo newer runs before older ones when reverting several runs.

A run with no recorded file differences has no changed-file card. Separate checkpoint warnings can still appear: an excluded file's contents may not have been captured, even when the run was read-only.

Checkpoint limits:

- Files over `CHECKPOINT_MAX_FILE_BYTES` (50 MiB by default), symbolic links, and generated directories such as `.git`, `.venv`, `venv`, `node_modules`, `__pycache__`, `.pytest_cache`, and `.ruff_cache` are excluded.
- `.gitignore` does **not** control checkpoint coverage. Other ignored files can appear in diffs and Undo.
- Files excluded in either the before or after checkpoint are left unchanged by Undo. Older checkpoints with incomplete exclusion records cannot authorize Undo.
- Checkpoints require host Git and can use substantial disk space. They do not change the project's Git index or history.
- On macOS, file events accelerate scanning. If event completeness cannot be established, the app falls back to a full scan. Set `WORKSPACE_WATCH=false` to disable this optimization.

### Skills, resources, and external tools

Registered Skills are available to the agent by name and description. It reads relevant `SKILL.md` bodies as needed. Use `@skill-name` or the **+** menu to request a Skill explicitly. Removing its token removes the explicit request; it does not disable automatic Skill selection.

The built-in **Guild Journal** and **Project Audit** Skills require no registration. Add your own Skill folders and optional read-only resources in `runtime.toml`. Resources are selected per run. All Skills are mounted under `/skills/<id>`; selected resources are mounted under `/resources/<id>`.

The workspace root can provide project instructions in `AGENTS.override.md`, then `AGENTS.md`, then configured fallback filenames. The first nonempty file is read each run, up to `project_doc_max_bytes` (32 KiB by default). Nested folders and host configuration directories are not searched for these instructions.

Web search and remote MCP use provider-side network connections, independently of the offline Docker sandbox. Remote MCP servers must use HTTPS, be reachable by the provider, and have an explicit `allowed_tools` list. Approve or deny external-tool requests in chat. Skill instructions cannot enable tools or resources you did not select.

### Guild Board and project audits

**Guild Board** displays projects that contain `.chat-orchestrator/` Markdown records. Ask the agent to register a project or record work with `@guild-journal`, then press **Sync** on the board. Sync reads records; the board does not create files, call a model, or continuously monitor changes. See [the record format](docs/guild-board.md).

Open **Audit** beside a project to view its charter, findings, and reports. Actions such as **Create charter**, **Recheck**, and **Request fix** put a draft in chat for you to review and send; they do not immediately modify files. Evidence quotes are checked against project files. Existing record text is displayed as written, regardless of language. See [audit records](docs/project-audit.md).

### Settings and usage

Settings opens on **Dashboard**. It shows monthly estimated spending, budget usage and pace, token totals, cache hit rates, model breakdowns, and a daily activity grid. Activity dates use the browser's timezone; budget months use UTC. ChatGPT plan tokens and tool fees are excluded from the API-cost ledger. A budget notice does not block runs.

The **General** tab contains the title model, new-chat defaults, ChatGPT connection, monthly budget, cost history, storage, and theme color. The interface follows the operating system's light or dark appearance.

Use **Storage** to inspect app-managed disk use and prune old checkpoints or attachments belonging to deleted chats. Pruned checkpoints lose their diffs and Undo capability. Cleanup is unavailable while runs are active and does not delete workspace files.

### Host terminal

The terminal button opens a host login shell for the selected workspace, separate from the agent's Docker sandbox. It has your host user's file and network access. Open up to eight tabs; closing the panel or switching projects keeps the tabs running, while closing a tab or reloading the browser ends its session. **⌘J** toggles the panel. A workspace-mismatch notice helps avoid running commands in the wrong project.

The app does not store terminal input or output in chat history. Your shell's own history settings still apply. Avoid concurrent terminal and agent edits to the same files.

## Configuration and local data

[.env.example](.env.example) and [runtime.example.toml](runtime.example.toml) are the configuration reference. Restart the backend after editing them. Useful controls include:

| Setting | Purpose |
| --- | --- |
| `SANDBOX_IMAGE`, `SANDBOX_CPUS`, `SANDBOX_MEMORY`, `SANDBOX_PIDS` | Container image and resource limits. |
| `COMMAND_TIMEOUT`, `COMMAND_TIMEOUT_MIN`, `RUN_TIMEOUT` | Command ceiling, model-requested timeout floor, and overall run limit. |
| `MAX_MODEL_ROUNDS`, `MAX_MODEL_OUTPUT_TOKENS`, `MAX_TITLE_OUTPUT_TOKENS` | Model-call and output limits. |
| `MAX_OUTPUT_CHARS`, `MAX_UPLOAD_BYTES` | Captured command output and upload limits. |
| `CHECKPOINTS`, `CHECKPOINT_MAX_FILE_BYTES`, `WORKSPACE_WATCH` | Checkpoint storage and scanning. |
| `COMPACT_TOKEN_THRESHOLD`, `REASONING_SUMMARY` | Automatic history compaction and visible reasoning summaries. |
| `RUNTIME_CONFIG`, `DATA_DIR` | Optional paths for runtime configuration and app-managed state. |

The app stores conversations, events, provider context, uploads, credentials, and checkpoints locally under `backend/data/agent/` by default. Treat that directory as sensitive. The SQLite database is `agent.db`, and ChatGPT credentials are in `chatgpt-auth.json`. Stopping or restarting the backend does not delete them. The old `backend/data/chat.db` is not automatically migrated.

## Security and limitations

Orchestrator is for a trusted local user. It binds to loopback and validates hosts and origins, but does not implement authentication for a public or multi-user deployment. Do not expose its ports to the internet.

Agent containers run without network access, as a non-root user, with a read-only root filesystem and restricted capabilities. `/workspace` remains writable. Host API keys are not passed into the container. The host terminal is not subject to the sandbox's restrictions.

**Local execution is not fully offline:** prompts, file excerpts returned by tools, and direct attachments are sent to the selected model provider. Provider calls, web search, and remote MCP can access external services. Review what a task will disclose before selecting private files or external tools.

The sandbox includes document and CPU-analysis tools, including LibreOffice, Poppler, scientific Python libraries, and preinstalled model tooling. It does not provide GPU/Metal acceleration, interactive commands, or network downloads. Put required inputs and models in the workspace or configured resources before running a task. Host-terminal installations do not add packages to the sandbox image.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Backend or image build cannot reach Docker | Start Docker and verify `docker info` from the same host environment. Install the CLI if it is missing, and run `make sandbox-build` if the image is missing. |
| Workspace blocked after a cleanup failure | Restore Docker connectivity, confirm that the run's container is stopped, and restart the backend after active work has finished. Do not remove containers belonging to other runs or projects. |
| No usable models | Complete ChatGPT sign-in or configure API credentials and matching Azure deployments. Restart the backend after `.env` or TOML changes. |
| ChatGPT sign-in does not finish | Allow the sign-in popup, finish consent in the browser, and check account eligibility. Use the connection page to reconnect if needed; never paste tokens into chat. |
| A provider or Azure connection cannot be changed | Start a new chat for that provider or resource. Existing chats retain their original binding. |
| Port 5173 or 8000 is occupied | Identify and stop the existing app process you own before starting another. Do not use multiple backend workers or silently move the frontend to another port. |
| Files look stale | Use **Refresh files**. The file list is not a live filesystem view. |
| Text save reports a conflict or busy workspace | Keep your draft, wait for the active run, and reload the file before saving again. |
| Undo is absent | The run may have no covered differences, checkpoints may be disabled or pruned, or an exclusion warning may explain incomplete coverage. |
| A command times out | Inspect Activity and the reported limit. Command and overall-run limits are separate; adjust `.env` only if the task needs a larger limit. Written changes remain. |
| Git reports a stale lock | End all Git operations, including IDE and agent activity, and confirm the lock is not in use before removing only that stale lock. The app does not delete Git locks automatically. |

## Development

```sh
make test          # Backend unit tests, frontend tests, TypeScript check, production build
make test-docker   # Real sandbox integration tests; requires Docker and the built image
```

Normal tests exclude paid live-provider tests. Live tests are opt-in, may incur charges, and require separate credentials and authorization; do not enable them for ordinary validation.

The app version is tracked in [VERSION](VERSION), with changes in [CHANGELOG.md](CHANGELOG.md). The sandbox's Python environment has its own lockfile and version. Interface icons use [Lucide](https://lucide.dev), licensed under ISC.
