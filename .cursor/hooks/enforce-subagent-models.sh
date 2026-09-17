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

case " $DEFAULT_MODELS " in
  *" $MODEL "*) allow ;;
  *) deny "Subagent model '$MODEL' is outside the repository default Cursor-model allowlist (composer-2.5, grok-4.6, grok-4.5). Use an allowed model or launch a new ACP run with an explicit allowed_subagent_models override." ;;
esac
