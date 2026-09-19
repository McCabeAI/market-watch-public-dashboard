#!/bin/sh
set -eu

DEFAULT_MODELS="composer-2.5 grok-4.6 grok-4.5"

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

deny() {
  msg=$(json_escape "$1")
  printf '{"permission":"deny","user_message":"%s"}\n' "$msg"
  exit 2
}

allow() {
  printf '{"permission":"allow"}\n'
  exit 0
}

if [ "$#" -gt 0 ] && [ -n "${1:-}" ]; then
  INPUT=$1
else
  INPUT=$(cat)
fi

MODEL=$(printf '%s' "$INPUT" | sed -n 's/.*"subagent_model"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
[ -n "$MODEL" ] || deny "Subagent blocked: Cursor did not provide subagent_model."

TRANSCRIPT=$(printf '%s' "$INPUT" | sed -n 's/.*"transcript_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
if [ -z "$TRANSCRIPT" ] && [ -n "${CURSOR_TRANSCRIPT_PATH:-}" ]; then
  TRANSCRIPT=$CURSOR_TRANSCRIPT_PATH
fi

POLICY=""
if [ -n "$TRANSCRIPT" ] && [ -r "$TRANSCRIPT" ]; then
  POLICY=$(head -c 65536 "$TRANSCRIPT" 2>/dev/null \
    | sed 's/\\"/"/g' \
    | grep -o 'ACP_SUBAGENT_POLICY={"version":1,"allowed_models":[^}]*}' \
    | head -n 1 || true)
fi

if [ -n "$POLICY" ]; then
  case "$POLICY" in
    *'"allowed_models":null'*) ;;
    *'"allowed_models":[]'*)
      deny "Subagent blocked by ACP policy: this run allows no subagent models."
      ;;
    *)
      if printf '%s' "$POLICY" | grep -Fq "\"$MODEL\""; then
        allow
      fi
      deny "Subagent model '$MODEL' is not in this run's ACP allowed_subagent_models list."
      ;;
  esac
fi

TR_POLICY=""
if [ -n "$TRANSCRIPT" ] && [ -r "$TRANSCRIPT" ]; then
  TR_POLICY=$(head -c 65536 "$TRANSCRIPT" 2>/dev/null \
    | sed 's/\\"/"/g' \
    | grep -o 'TRADER_ROOM_MODEL_POLICY={"version":1,[^}]*}' \
    | head -n 1 || true)
fi

PM_POLICY=""
if [ -n "$TRANSCRIPT" ] && [ -r "$TRANSCRIPT" ]; then
  PM_POLICY=$(head -c 65536 "$TRANSCRIPT" 2>/dev/null \
    | sed 's/\\"/"/g' \
    | grep -o 'PM_MODEL_POLICY={"version":1,[^}]*}' \
    | head -n 1 || true)
fi

if [ -n "$PM_POLICY" ]; then
  case "$MODEL" in
    grok-4.6|composer-2.5) allow ;;
    cursor-grok-4.6-*)
      deny "PM routing blocked runtime slug '$MODEL'. Launch principals via .cursor/agents/{swinger,pragmatist,grinder}.md (frontmatter grok-4.6[]), not Task model grok-4.6/inherit."
      ;;
    *) deny "PM model policy allows only grok-4.6 principals and grok-4.6/composer-2.5 subagents. Refusing '$MODEL'." ;;
  esac
fi

if [ -n "$TR_POLICY" ]; then
  case "$MODEL" in
    grok-4.6|composer-2.5) allow ;;
    *) deny "Trader Room model policy allows only grok-4.6 (advocates/aggregators) and composer-2.5 (internal advocate subagents). Refusing '$MODEL'." ;;
  esac
fi

case " $DEFAULT_MODELS " in
  *" $MODEL "*) allow ;;
  *) deny "Subagent model '$MODEL' is outside the repository default Cursor-model allowlist (composer-2.5, grok-4.6, grok-4.5). Use an allowed model or launch a new ACP run with an explicit allowed_subagent_models override." ;;
esac
