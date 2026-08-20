# Managed by ltsp-setup: puts the shared Rust toolchain on everyone's PATH.
export RUSTUP_HOME="$RUSTUP_HOME"
if [ -d "$CARGO_BIN" ]; then
    case ":$${PATH}:" in
        *":$CARGO_BIN:"*) ;;
        *) PATH="$CARGO_BIN:$${PATH}" ;;
    esac
    export PATH
fi
