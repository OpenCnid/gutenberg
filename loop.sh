#!/bin/bash
# Usage: ./loop.sh [plan] [max_iterations]
# Examples:
#   ./loop.sh              # Build mode, unlimited iterations
#   ./loop.sh 20           # Build mode, max 20 iterations
#   ./loop.sh plan         # Plan mode, unlimited iterations
#   ./loop.sh plan 5       # Plan mode, max 5 iterations

set -euo pipefail

RALPH_CLI="${RALPH_CLI:-openclaw}"
RALPH_MODEL="${RALPH_MODEL:-}"
RALPH_THINKING="${RALPH_THINKING:-high}"
RALPH_TIMEOUT="${RALPH_TIMEOUT:-1800}"
OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-$HOME/.openclaw/openclaw.json}"
RALPH_ARTIFACT_ROOT="${RALPH_ARTIFACT_ROOT:-.ralph/artifacts}"
CLI_BASENAME="$(basename "$RALPH_CLI")"
if [ -z "$RALPH_MODEL" ]; then
    case "$CLI_BASENAME" in
        codex*)
            RALPH_MODEL="gpt-5.5"
            ;;
        *)
            RALPH_MODEL="lil-dario/claude-opus-4-6"
            ;;
    esac
fi
ARTIFACT_ITERATION_DIR=""

sanitize_fragment() {
    printf '%s' "$1" \
        | tr '[:upper:]' '[:lower:]' \
        | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-{2,}/-/g'
}

default_openclaw_agent_id() {
    local repo_slug path_hash
    repo_slug="$(sanitize_fragment "$(basename "$PWD")")"
    [ -n "$repo_slug" ] || repo_slug="repo"
    path_hash="$(printf '%s' "$PWD|$RALPH_MODEL" | cksum | awk '{print $1}')"
    printf 'ralph-%s-%s' "${repo_slug:0:40}" "$path_hash"
}

default_session_prefix() {
    local repo_slug
    repo_slug="$(sanitize_fragment "$(basename "$PWD")")"
    [ -n "$repo_slug" ] || repo_slug="repo"
    printf 'ralph-%s' "${repo_slug:0:24}"
}

normalize_agent_id() {
    local normalized
    normalized="$(sanitize_fragment "$1")"
    if [ -z "$normalized" ]; then
        echo "Error: Unable to derive a valid OpenClaw agent id from '$1'." >&2
        exit 1
    fi
    printf '%s' "$normalized"
}

artifact_iteration_dir() {
    local cli_slug
    cli_slug="$(sanitize_fragment "$CLI_BASENAME")"
    [ -n "$cli_slug" ] || cli_slug="cli"
    printf '%s/iterations/%s-%s-%04d' "$RALPH_ARTIFACT_ROOT" "$MODE" "$cli_slug" "$((ITERATION + 1))"
}

prepare_iteration_artifacts() {
    ARTIFACT_ITERATION_DIR="$(artifact_iteration_dir)"
    mkdir -p "$ARTIFACT_ITERATION_DIR"
}

capture_iteration_metadata() {
    local file_path="$1"
    local phase="$2"

    PHASE="$phase" \
    MODE_VALUE="$MODE" \
    ITERATION_NUMBER="$((ITERATION + 1))" \
    PROMPT_PATH="$PROMPT_FILE" \
    CLI_VALUE="$RALPH_CLI" \
    CLI_NAME="$CLI_BASENAME" \
    MODEL_VALUE="$RALPH_MODEL" \
    THINKING_VALUE="$RALPH_THINKING" \
    TIMEOUT_VALUE="$RALPH_TIMEOUT" \
    BRANCH_VALUE="$CURRENT_BRANCH" \
    WORKSPACE_VALUE="$PWD" \
    AGENT_VALUE="$RALPH_AGENT_ID" \
    SESSION_PREFIX_VALUE="$RALPH_SESSION_PREFIX" \
    ARTIFACT_DIR_VALUE="$ARTIFACT_ITERATION_DIR" \
    TIMESTAMP_VALUE="$(date -Iseconds)" \
    node - "$file_path" <<'NODE'
const fs = require("fs");

const filePath = process.argv[2];
const data = {
  phase: process.env.PHASE,
  mode: process.env.MODE_VALUE,
  iteration: Number(process.env.ITERATION_NUMBER),
  promptFile: process.env.PROMPT_PATH,
  cli: process.env.CLI_VALUE,
  cliBasename: process.env.CLI_NAME,
  model: process.env.MODEL_VALUE,
  thinking: process.env.THINKING_VALUE,
  timeoutSeconds: Number(process.env.TIMEOUT_VALUE),
  branch: process.env.BRANCH_VALUE,
  workspace: process.env.WORKSPACE_VALUE,
  agentId: process.env.AGENT_VALUE || null,
  sessionPrefix: process.env.SESSION_PREFIX_VALUE || null,
  artifactDir: process.env.ARTIFACT_DIR_VALUE,
  capturedAt: process.env.TIMESTAMP_VALUE,
};
fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`);
NODE
}

capture_repo_state() {
    local file_path="$1"
    local phase="$2"
    local head_sha current_branch_value status_short tags_at_head dirty

    head_sha="$(git rev-parse HEAD 2>/dev/null || true)"
    current_branch_value="$(git branch --show-current 2>/dev/null || true)"
    status_short="$(git status --short 2>/dev/null || true)"
    tags_at_head="$(git tag --points-at HEAD 2>/dev/null | paste -sd ',' -)"
    if [ -n "$status_short" ]; then
        dirty="true"
    else
        dirty="false"
    fi

    PHASE="$phase" \
    HEAD_SHA_VALUE="$head_sha" \
    BRANCH_VALUE="$current_branch_value" \
    STATUS_SHORT_VALUE="$status_short" \
    TAGS_AT_HEAD_VALUE="$tags_at_head" \
    DIRTY_VALUE="$dirty" \
    TIMESTAMP_VALUE="$(date -Iseconds)" \
    node - "$file_path" <<'NODE'
const fs = require("fs");

const filePath = process.argv[2];
const tags = (process.env.TAGS_AT_HEAD_VALUE || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const statusShort = process.env.STATUS_SHORT_VALUE || "";
const data = {
  phase: process.env.PHASE,
  head: process.env.HEAD_SHA_VALUE || null,
  branch: process.env.BRANCH_VALUE || null,
  dirty: process.env.DIRTY_VALUE === "true",
  tagsAtHead: tags,
  statusShort,
  statusLines: statusShort.length > 0 ? statusShort.split(/\r?\n/).filter(Boolean) : [],
  capturedAt: process.env.TIMESTAMP_VALUE,
};
fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`);
NODE
}

validate_openclaw_response() {
    local response_file="$1"
    local expected_agent_id="$2"
    local expected_session_id="$3"
    local expected_session_key="$4"
    local expected_model="$5"
    local expected_workspace="$6"

    node - "$response_file" "$expected_agent_id" "$expected_session_id" "$expected_session_key" "$expected_model" "$expected_workspace" <<'NODE'
const fs = require("fs");
const path = require("path");
const [responseFile, expectedAgentId, expectedSessionId, expectedSessionKey, expectedModel, expectedWorkspace] = process.argv.slice(2);

function fail(message) {
  console.error(`Error: Invalid OpenClaw Gateway agent response. ${message}`);
  process.exit(1);
}

(() => {
  let raw = "";
  let response;
  try {
    raw = fs.readFileSync(responseFile, "utf8");
    response = JSON.parse(raw);
  } catch (error) {
    fail(`Response was not valid JSON: ${error.message}`);
  }

  if (!response || typeof response !== "object" || Array.isArray(response)) {
    fail("Expected a JSON object.");
  }

  if (response.error) {
    const message = typeof response.error === "string"
      ? response.error
      : JSON.stringify(response.error);
    fail(`Gateway returned error: ${message}`);
  }

  if (response.status && String(response.status) !== "ok") {
    fail(`Expected top-level status ok, got ${response.status}.`);
  }

  if (!response.runId || String(response.runId) !== `ralph-${expectedSessionId}`) {
    fail(`Expected runId ralph-${expectedSessionId}, got ${response.runId ?? "(missing)"}.`);
  }

  const result = response.result;
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    fail("Missing object response.result from gateway RPC.");
  }

  if (!Array.isArray(result.payloads)) {
    fail("Missing array result.payloads from gateway RPC.");
  }

  const report = result?.meta?.systemPromptReport;
  if (!report || typeof report !== "object") {
    fail("Missing result.meta.systemPromptReport. This does not look like the expected strict gateway-final response shape.");
  }

  if (String(report.sessionKey ?? "") !== expectedSessionKey) {
    fail(`Expected systemPromptReport.sessionKey ${expectedSessionKey}, got ${report.sessionKey ?? "(missing)"}.`);
  }

  if (String(report.workspaceDir ?? "") !== path.resolve(expectedWorkspace)) {
    fail(`Expected systemPromptReport.workspaceDir ${path.resolve(expectedWorkspace)}, got ${report.workspaceDir ?? "(missing)"}.`);
  }

  const actualModel = [report.provider, report.model].filter(Boolean).join("/");
  if (actualModel && actualModel !== expectedModel) {
    fail(`Expected provider/model ${expectedModel}, got ${actualModel}.`);
  }

  const fallbackUsed = result?.meta?.executionTrace?.fallbackUsed;
  if (fallbackUsed === true) {
    fail("Gateway executionTrace reported fallbackUsed=true.");
  }

  const finalText = result?.meta?.finalAssistantRawText;
  if (typeof finalText !== "string" || finalText.length === 0) {
    fail("Missing final assistant text in result.meta.finalAssistantRawText.");
  }
})();
NODE
}

write_openclaw_response_summary() {
    local response_file="$1"
    local file_path="$2"

    node - "$response_file" "$file_path" <<'NODE'
const fs = require("fs");
const [responseFile, filePath] = process.argv.slice(2);

(() => {
  const raw = fs.readFileSync(responseFile, "utf8");
  const response = JSON.parse(raw || "{}");
  const result = response?.result ?? {};
  const payloads = Array.isArray(result.payloads) ? result.payloads : [];
  const report = result?.meta?.systemPromptReport ?? {};
  const trace = result?.meta?.executionTrace ?? {};
  const data = {
    runId: response?.runId ?? null,
    status: response?.status ?? null,
    agentId: result.agentId ?? null,
    sessionId: result.sessionId ?? report.sessionId ?? null,
    sessionKey: result.sessionKey ?? report.sessionKey ?? null,
    provider: report.provider ?? null,
    model: report.model ?? null,
    workspaceDir: report.workspaceDir ?? null,
    fallbackUsed: trace.fallbackUsed ?? null,
    runner: trace.runner ?? null,
    payloadCount: payloads.length,
    payloadKinds: payloads.map((payload) => payload?.type ?? payload?.kind ?? null),
    textPayloadCount: payloads.filter((payload) => typeof payload?.text === "string" && payload.text.length > 0).length,
    mediaPayloadCount: payloads.filter((payload) => typeof payload?.mediaUrl === "string" || Array.isArray(payload?.mediaUrls)).length,
    summary: typeof response?.summary === "string" ? response.summary : null,
    capturedAt: new Date().toISOString(),
  };
  fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`);
})();
NODE
}

RALPH_AGENT_ID="${RALPH_AGENT_ID:-$(default_openclaw_agent_id)}"
RALPH_AGENT_ID="$(normalize_agent_id "$RALPH_AGENT_ID")"
RALPH_SESSION_PREFIX="${RALPH_SESSION_PREFIX:-$(default_session_prefix)}"
RALPH_SESSION_PREFIX="$(sanitize_fragment "$RALPH_SESSION_PREFIX")"
[ -n "$RALPH_SESSION_PREFIX" ] || RALPH_SESSION_PREFIX="ralph"

# Parse arguments
if [ "${1:-}" = "plan" ]; then
    MODE="plan"
    PROMPT_FILE="PROMPT_plan.md"
    MAX_ITERATIONS=${2:-0}
elif [[ "${1:-}" =~ ^[0-9]+$ ]]; then
    MODE="build"
    PROMPT_FILE="PROMPT_build.md"
    MAX_ITERATIONS=$1
else
    MODE="build"
    PROMPT_FILE="PROMPT_build.md"
    MAX_ITERATIONS=0
fi

ITERATION=0
CURRENT_BRANCH=$(git branch --show-current)

inspect_openclaw_agent() {
    node - "$OPENCLAW_CONFIG_PATH" "$RALPH_AGENT_ID" "$PWD" "$RALPH_MODEL" <<'NODE'
const fs = require("fs");
const path = require("path");

const [configPathRaw, agentIdRaw, workspaceRaw, modelRaw] = process.argv.slice(2);
const configPath = configPathRaw.replace(/^~(?=$|\/)/, process.env.HOME || "~");
const wantedAgentId = String(agentIdRaw || "").trim().toLowerCase();
const wantedWorkspace = path.resolve(workspaceRaw);
const wantedModel = String(modelRaw || "").trim();

if (!fs.existsSync(configPath)) {
  console.log("absent");
  process.exit(0);
}

const cfg = JSON.parse(fs.readFileSync(configPath, "utf8"));
const agents = cfg?.agents?.list ?? [];
const entry = agents.find((agent) => String(agent?.id ?? "").trim().toLowerCase() === wantedAgentId);

if (!entry) {
  console.log("absent");
  process.exit(0);
}

const actualWorkspace = entry?.workspace ? path.resolve(String(entry.workspace)) : "";
const actualModel = String(entry?.model ?? "").trim();
const workspaceMatches = actualWorkspace === wantedWorkspace;
const modelMatches = actualModel === wantedModel;

if (workspaceMatches && modelMatches) {
  console.log("ok");
  process.exit(0);
}

if (!workspaceMatches && !modelMatches) console.log("workspace-and-model-mismatch");
else if (!workspaceMatches) console.log("workspace-mismatch");
else console.log("model-mismatch");
console.log(actualWorkspace);
console.log(actualModel);
NODE
}

ensure_openclaw_agent() {
    local agent_state=()
    mapfile -t agent_state < <(inspect_openclaw_agent)

    case "${agent_state[0]:-absent}" in
        absent)
            echo "Bootstrapping OpenClaw agent: $RALPH_AGENT_ID"
            "$RALPH_CLI" agents add "$RALPH_AGENT_ID" \
                --workspace "$PWD" \
                --model "$RALPH_MODEL" \
                --non-interactive \
                >/dev/null
            mapfile -t agent_state < <(inspect_openclaw_agent)
            if [ "${agent_state[0]:-absent}" != "ok" ]; then
                echo "Error: OpenClaw agent bootstrap did not converge to the expected workspace/model." >&2
                echo "Wanted workspace: $PWD" >&2
                echo "Actual workspace: ${agent_state[1]:-(unknown)}" >&2
                echo "Wanted model: $RALPH_MODEL" >&2
                echo "Actual model: ${agent_state[2]:-(unset)}" >&2
                exit 1
            fi
            ;;
        ok)
            ;;
        *)
            echo "Error: OpenClaw agent '$RALPH_AGENT_ID' already exists with different settings." >&2
            echo "Wanted workspace: $PWD" >&2
            echo "Actual workspace: ${agent_state[1]:-(unknown)}" >&2
            echo "Wanted model: $RALPH_MODEL" >&2
            echo "Actual model: ${agent_state[2]:-(unset)}" >&2
            echo "Set RALPH_AGENT_ID to a different agent, or delete/update the existing agent before rerunning." >&2
            exit 1
            ;;
    esac
}

build_openclaw_params() {
    node - "$@" <<'NODE'
const [message, agentId, sessionId, sessionKey, thinking, timeoutRaw, idempotencyKey] = process.argv.slice(2);
const timeout = Number.parseInt(timeoutRaw, 10);
const payload = {
  message,
  agentId,
  sessionId,
  sessionKey,
  idempotencyKey
};
if (thinking) payload.thinking = thinking;
if (!Number.isNaN(timeout)) payload.timeout = timeout;
process.stdout.write(JSON.stringify(payload));
NODE
}

print_openclaw_response() {
    node -e '
const fs = require("fs");
const raw = fs.readFileSync(process.argv[1], "utf8");
(() => {
  const response = JSON.parse(raw || "{}");
  const payloads = response?.result?.payloads ?? [];
  if (payloads.length === 0) {
    if (response?.summary) console.log(response.summary);
    return;
  }
  for (const payload of payloads) {
    if (typeof payload.text === "string" && payload.text.length > 0) process.stdout.write(`${payload.text.trimEnd()}\n`);
    if (typeof payload.mediaUrl === "string" && payload.mediaUrl.length > 0) process.stdout.write(`MEDIA:${payload.mediaUrl}\n`);
    if (Array.isArray(payload.mediaUrls)) {
      for (const url of payload.mediaUrls) {
        if (typeof url === "string" && url.length > 0) process.stdout.write(`MEDIA:${url}\n`);
      }
    }
  }
})();' "$1"
}

run_openclaw_lane() {
    local prompt_content session_seq session_id session_key idempotency_key params gateway_timeout_ms raw_response response_file

    ensure_openclaw_agent
    prompt_content="$(cat "$PROMPT_FILE")"
    session_seq="$(printf '%04d' "$((ITERATION + 1))")"
    session_id="${RALPH_SESSION_PREFIX}-${MODE}-${session_seq}-$(date +%s)"
    session_key="agent:${RALPH_AGENT_ID}:explicit:${session_id}"
    idempotency_key="ralph-${session_id}"
    params="$(build_openclaw_params "$prompt_content" "$RALPH_AGENT_ID" "$session_id" "$session_key" "$RALPH_THINKING" "$RALPH_TIMEOUT" "$idempotency_key")"

    if [ "$RALPH_TIMEOUT" -eq 0 ]; then
        gateway_timeout_ms=2147000000
    else
        gateway_timeout_ms=$(( (RALPH_TIMEOUT + 30) * 1000 ))
    fi

    printf '%s\n' "$params" > "$ARTIFACT_ITERATION_DIR/gateway-request.json"
    echo "OpenClaw lane: invoking gateway call agent directly (no openclaw agent fallback path)."
    response_file="$ARTIFACT_ITERATION_DIR/gateway-response.json"

    raw_response="$("$RALPH_CLI" gateway call agent \
        --expect-final \
        --json \
        --timeout "$gateway_timeout_ms" \
        --params "$params")"

    printf '%s\n' "$raw_response" > "$response_file"
    validate_openclaw_response "$response_file" "$RALPH_AGENT_ID" "$session_id" "$session_key" "$RALPH_MODEL" "$PWD"
    write_openclaw_response_summary "$response_file" "$ARTIFACT_ITERATION_DIR/gateway-response-summary.json"

    print_openclaw_response "$response_file"
}

case "$CLI_BASENAME" in
    codex*)
        EFFORT_LABEL="xhigh"
        THINK_LABEL="Codex reasoning override"
        ;;
    openclaw*)
        EFFORT_LABEL="gateway-native"
        THINK_LABEL="fresh explicit session, thinking=$RALPH_THINKING"
        ;;
    claude*)
        echo "Error: Raw claude execution is no longer supported in this skill." >&2
        echo "Use the OpenClaw-native Claude lane with RALPH_CLI=openclaw, or switch to RALPH_CLI=codex for the Codex lane." >&2
        exit 1
        ;;
    *)
        echo "Error: Unsupported RALPH_CLI '$RALPH_CLI'. Supported executors: openclaw, codex." >&2
        echo "If you want another CLI, update the command block in loop.sh and the matching docs in RALPH.md." >&2
        exit 1
        ;;
esac

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Mode:   $MODE"
echo "Prompt: $PROMPT_FILE"
echo "Branch: $CURRENT_BRANCH"
echo "CLI:    $RALPH_CLI"
echo "Model:  $RALPH_MODEL"
if [[ "$CLI_BASENAME" == openclaw* ]]; then
    echo "Agent:  $RALPH_AGENT_ID"
    echo "Think:  $THINK_LABEL"
    echo "Time:   ${RALPH_TIMEOUT}s"
else
    echo "Effort: $EFFORT_LABEL"
    echo "Think:  $THINK_LABEL"
fi
[ $MAX_ITERATIONS -gt 0 ] && echo "Max:    $MAX_ITERATIONS iterations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ ! -f "$PROMPT_FILE" ]; then
    echo "Error: $PROMPT_FILE not found"
    exit 1
fi

while true; do
    if [ $MAX_ITERATIONS -gt 0 ] && [ $ITERATION -ge $MAX_ITERATIONS ]; then
        echo "Reached max iterations: $MAX_ITERATIONS"
        break
    fi

    prepare_iteration_artifacts
    capture_iteration_metadata "$ARTIFACT_ITERATION_DIR/iteration-metadata.json" "started"
    capture_repo_state "$ARTIFACT_ITERATION_DIR/repo-state-before.json" "before-run"

    # Default build lanes:
    # - OpenClaw gateway-native Claude lane on lil-dario/claude-opus-4-6, with a
    #   dedicated per-repo agent and a fresh explicit session every iteration
    # - Codex on gpt-5.5 in xhigh, with the outer Ralph sandbox as the safety boundary
    # - Other CLIs still require adapting this command block and the matching RALPH.md docs
    case "$CLI_BASENAME" in
        openclaw*)
            run_openclaw_lane
            ;;
        codex*)
            PROMPT_CONTENT="$(cat "$PROMPT_FILE")"
            "$RALPH_CLI" exec \
                --yolo \
                --json \
                --model "$RALPH_MODEL" \
                -c model_reasoning_effort='"xhigh"' \
                -C "$PWD" \
                "$PROMPT_CONTENT"
            ;;
    esac

    git push origin "$CURRENT_BRANCH" || {
        echo "Failed to push. Creating remote branch..."
        git push -u origin "$CURRENT_BRANCH"
    }

    capture_iteration_metadata "$ARTIFACT_ITERATION_DIR/iteration-metadata.final.json" "completed"
    capture_repo_state "$ARTIFACT_ITERATION_DIR/repo-state-after.json" "after-push"

    ITERATION=$((ITERATION + 1))
    echo -e "\n\n======================== LOOP $ITERATION ========================\n"
done
