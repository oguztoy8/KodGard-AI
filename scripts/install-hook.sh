#!/usr/bin/env bash
set -euo pipefail

UNINSTALL=0
REPO_ARG=""

for arg in "$@"; do
    case "$arg" in
        --uninstall)
            UNINSTALL=1
            ;;
        -*)
            echo "Hata: bilinmeyen seçenek: $arg" >&2
            exit 2
            ;;
        *)
            if [ -z "$REPO_ARG" ]; then
                REPO_ARG="$arg"
            else
                echo "Hata: birden fazla repo yolu verildi." >&2
                exit 2
            fi
            ;;
    esac
done

if [ -z "$REPO_ARG" ]; then
    echo "Kullanım: $0 [--uninstall] <repo-yolu>" >&2
    exit 2
fi

if [ ! -d "$REPO_ARG" ] || ! git -C "$REPO_ARG" rev-parse --git-dir >/dev/null 2>&1; then
    echo "Hata: geçerli bir git reposu değil: $REPO_ARG" >&2
    exit 1
fi

KODGARD_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KODGARD_HOOK="$KODGARD_ROOT/hooks/post-commit"
DEFAULT_API_URL="${KODGARD_API_URL:-http://127.0.0.1:${API_PORT:-8000}}"

HOOKS_PATH_RAW="$(git -C "$REPO_ARG" rev-parse --git-path hooks)"
case "$HOOKS_PATH_RAW" in
    /*) HOOKS_DIR="$HOOKS_PATH_RAW" ;;
    *)  HOOKS_DIR="$(cd "$REPO_ARG" && pwd)/$HOOKS_PATH_RAW" ;;
esac

mkdir -p "$HOOKS_DIR"
HOOK_FILE="$HOOKS_DIR/post-commit"

START_MARK="# >>> kodgard >>>"
END_MARK="# <<< kodgard <<<"
WRAPPER_MARK="# kodgard-standalone-wrapper"

if [ "$UNINSTALL" -eq 1 ]; then
    if [ ! -f "$HOOK_FILE" ]; then
        exit 0
    fi
    if grep -Fq "$WRAPPER_MARK" "$HOOK_FILE"; then
        rm -f "$HOOK_FILE"
        exit 0
    fi
    if grep -Fq "$START_MARK" "$HOOK_FILE"; then
        TMP_FILE="${HOOK_FILE}.kodgard.tmp"
        awk -v s="$START_MARK" -v e="$END_MARK" '
            $0 == s { skip = 1; next }
            $0 == e { skip = 0; next }
            !skip { print }
        ' "$HOOK_FILE" > "$TMP_FILE"
        chmod --reference="$HOOK_FILE" "$TMP_FILE" 2>/dev/null || chmod +x "$TMP_FILE"
        mv "$TMP_FILE" "$HOOK_FILE"
    fi
    exit 0
fi

if [ ! -f "$HOOK_FILE" ]; then
    cat > "$HOOK_FILE" <<EOF
#!/usr/bin/env bash
$WRAPPER_MARK
$START_MARK
export KODGARD_HOME="\${KODGARD_HOME:-$KODGARD_ROOT}"
export KODGARD_API_URL="\${KODGARD_API_URL:-$DEFAULT_API_URL}"
if [ -x "$KODGARD_HOOK" ]; then
    "$KODGARD_HOOK" || true
fi
$END_MARK
EOF
    chmod +x "$HOOK_FILE"
    exit 0
fi

# Hook file already exists
if grep -Fq "$START_MARK" "$HOOK_FILE"; then
    # Already installed (idempotent)
    chmod +x "$HOOK_FILE"
    exit 0
fi

cp -p "$HOOK_FILE" "${HOOK_FILE}.kodgard.bak"

cat >> "$HOOK_FILE" <<EOF

$START_MARK
export KODGARD_HOME="\${KODGARD_HOME:-$KODGARD_ROOT}"
export KODGARD_API_URL="\${KODGARD_API_URL:-$DEFAULT_API_URL}"
if [ -x "$KODGARD_HOOK" ]; then
    "$KODGARD_HOOK" || true
fi
$END_MARK
EOF

chmod +x "$HOOK_FILE"
exit 0
