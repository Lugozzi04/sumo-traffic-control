#!/usr/bin/env bash
set -euo pipefail

# Installa le dipendenze LaTeX necessarie per compilare la tesi.
# Supporta Linux Debian/Ubuntu e macOS.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS_NAME="$(uname -s)"

install_linux() {
    if ! command -v apt-get >/dev/null 2>&1; then
        echo "Errore: questo script richiede apt-get su Linux."
        echo "Usalo su Ubuntu/Debian o su una derivata compatibile."
        exit 1
    fi

    if [[ "${EUID}" -eq 0 ]]; then
        SUDO=""
    else
        SUDO="sudo"
    fi

    echo "Aggiorno l'indice dei pacchetti..."
    ${SUDO} apt-get update

    echo "Installo dipendenze LaTeX per la tesi..."
    ${SUDO} apt-get install -y \
        latexmk \
        biber \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-bibtex-extra \
        texlive-fonts-recommended \
        texlive-fonts-extra \
        texlive-pictures \
        texlive-science \
        texlive-lang-italian \
        poppler-utils
}

install_macos() {
    local brew_bin=""

    if command -v brew >/dev/null 2>&1; then
        brew_bin="$(command -v brew)"
    else
        for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
            if [[ -x "$candidate" ]]; then
                brew_bin="$candidate"
                break
            fi
        done
    fi

    if [[ -z "$brew_bin" ]]; then
        echo "Errore: Homebrew non trovato."
        echo "Installa Homebrew da https://brew.sh/ e rilancia questo script."
        exit 1
    fi

    eval "$("$brew_bin" shellenv)"

    echo "Aggiorno Homebrew..."
    brew update

    echo "Installo MacTeX (senza GUI)..."
    brew install --cask mactex-no-gui

    echo "Installo poppler..."
    brew install poppler

    echo "Se il terminale non vede ancora i comandi TeX, riaprilo o esegui:"
    echo '  eval "$(/usr/libexec/path_helper)"'
}

case "$OS_NAME" in
    Linux)
        install_linux
        ;;
    Darwin)
        install_macos
        ;;
    *)
        echo "Errore: sistema operativo non supportato da questo script."
        echo "Usa Linux, macOS oppure il file install_latex_deps.ps1 su Windows."
        exit 1
        ;;
esac

echo
echo "Dipendenze installate."
echo "Per compilare la tesi completa:"
echo "  cd \"$SCRIPT_DIR/tesi\" && latexmk -pdf -synctex=1 -interaction=nonstopmode -halt-on-error tesi.tex"
