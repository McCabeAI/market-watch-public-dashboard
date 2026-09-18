#!/bin/sh
set -eu

# Trader Room + ACP subagentStart guard.
# ACP allowed_models is an allowlist, not an immediate grant.
# Standing trader/aggregator/rebuttal invocations must be grok-4.6.
# composer-2.5 is only first-pass trader internal research, max 2 per trader.
# Rebuttals and aggregators get no subagents.
# Keep these tokens for mechanical validation: TRADER_ROOM_MODEL_POLICY grok-4.6|composer-2.5

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

HOOK_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$HOOK_DIR/../.." && pwd)
ENFORCER="$REPO_ROOT/scripts/trader_room/hook_enforce.py"

if [ -f "$ENFORCER" ]; then
  if PYTHONPATH="$REPO_ROOT" python3 "$ENFORCER" "$INPUT"; then
    exit 0
  else
    status=$?
    if [ "$status" -eq 2 ]; then
      exit 2
    fi
    # Fall through to the shell policy if Python cannot import the helper.
  fi
fi

MODEL=$(printf '%s' "$INPUT" | sed -n 's/.*"subagent_model"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
[ -n "$MODEL" ] || deny "Subagent blocked: Cursor did not provide subagent_model."
NORMALIZED=$(printf '%s' "$MODEL" | sed 's/\[\]$//')
case "$NORMALIZED" in
  cursor-grok-4.6-high|cursor-grok-4.6-medium|cursor-grok-4.6-low|cursor-grok-4.6-xhigh)
    NORMALIZED=grok-4.6
    ;;
esac

TYPE=$(printf '%s' "$INPUT" | sed -n 's/.*"subagent_type"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)

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
if [ -z "$POLICY" ]; then
  POLICY=$(printf '%s' "$INPUT" | sed 's/\\"/"/g' | grep -o 'ACP_SUBAGENT_POLICY={"version":1,"allowed_models":[^}]*}' | head -n 1 || true)
fi

if [ -n "$POLICY" ]; then
  case "$POLICY" in
    *'"allowed_models":null'*) ;;
    *'"allowed_models":[]'*)
      deny "Subagent blocked by ACP policy: this run allows no subagent models."
      ;;
    *)
      if ! printf '%s' "$POLICY" | grep -Fq "\"$MODEL\"" && ! printf '%s' "$POLICY" | grep -Fq "\"$NORMALIZED\""; then
        deny "Subagent model '$MODEL' is not in this run's ACP allowed_subagent_models list."
      fi
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
if [ -z "$TR_POLICY" ]; then
  TR_POLICY=$(printf '%s' "$INPUT" | sed 's/\\"/"/g' | grep -o 'TRADER_ROOM_MODEL_POLICY={"version":1,[^}]*}' | head -n 1 || true)
fi

STANDING="perma-bull perma-bear dollar-king cross-merchant carry-is-king rate-hawk rate-dove value-guy trend-follower mean-reverter positioning-cynic catalyst-junkie vol-convexity no-trade-skeptic"
AGGREGATORS="conflict-aggregator final-aggregator"
ROLE=$(printf '%s' "$INPUT" | sed -n 's/.*TRADER_ROOM_SEAT_ROLE=\([a-z0-9-]*\).*/\1/p' | head -n 1)
if [ -z "$ROLE" ] && [ -n "$TRANSCRIPT" ] && [ -r "$TRANSCRIPT" ]; then
  ROLE=$(head -c 65536 "$TRANSCRIPT" 2>/dev/null | sed -n 's/.*TRADER_ROOM_SEAT_ROLE=\([a-z0-9-]*\).*/\1/p' | head -n 1 || true)
fi

is_standing() {
  case " $STANDING $AGGREGATORS " in
    *" $1 "*) return 0 ;;
    *) return 1 ;;
  esac
}

is_aggregator() {
  case " $AGGREGATORS " in
    *" $1 "*) return 0 ;;
    *) return 1 ;;
  esac
}

if [ -n "$TR_POLICY" ] || is_standing "$TYPE" || [ -n "$ROLE" ]; then
  if is_standing "$TYPE" || [ "$ROLE" = "advocate" ] || [ "$ROLE" = "rebuttal" ] || [ "$ROLE" = "conflict-aggregator" ] || [ "$ROLE" = "final-aggregator" ]; then
    case "$NORMALIZED" in
      grok-4.6) allow ;;
      *) deny "Trader Room standing trader/aggregator/rebuttal invocations must be exact grok-4.6. Refusing '$MODEL'." ;;
    esac
  fi
  if [ "$NORMALIZED" = "composer-2.5" ]; then
    if [ "$ROLE" = "rebuttal" ] || [ "$ROLE" = "conflict-aggregator" ] || [ "$ROLE" = "final-aggregator" ] || is_aggregator "$TYPE"; then
      deny "Trader Room rebuttals and aggregators get no internal subagents. Refusing composer-2.5."
    fi
    if [ -n "$ROLE" ] && [ "$ROLE" != "advocate-research" ]; then
      deny "composer-2.5 is only allowed for first-pass trader research. Refusing role '$ROLE'."
    fi
    case "$NORMALIZED" in
      composer-2.5) allow ;;
    esac
  fi
  case "$NORMALIZED" in
    grok-4.6|composer-2.5) allow ;;
    *) deny "Trader Room model policy allows only grok-4.6 (advocates/aggregators) and composer-2.5 (internal advocate subagents). Refusing '$MODEL'." ;;
  esac
fi

case " $DEFAULT_MODELS " in
  *" $NORMALIZED "*) allow ;;
  *) deny "Subagent model '$MODEL' is outside the repository default Cursor-model allowlist (composer-2.5, grok-4.6, grok-4.5). Use an allowed model or launch a new ACP run with an explicit allowed_subagent_models override." ;;
esac
