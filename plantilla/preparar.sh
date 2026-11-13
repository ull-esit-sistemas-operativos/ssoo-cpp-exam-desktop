#!/usr/bin/env bash
# Prepara cuentas de Linux (Ubuntu) ya existentes para un examen de C++ sin conexión.
#
# En cada cuenta deja:
#   ~/Escritorio/examen/           carpeta de trabajo (o ~/Desktop/examen según el idioma)
#        @PDF@  apuntes de la práctica
#        cppreference/             cppreference offline
#        man/                      manual del sistema en HTML
#        LEEME.html                índice de toda la documentación
#   ~/.vscode/extensions/          extensión C/C++ (del .vsix sin red, o del Marketplace si no está)
#   ~/.config/Code/User/settings.json   IA desactivada, @ESTANDAR@ con @COMPILADOR@, sin actualizaciones
#   ~/.local/share/applications/   lanzadores "Examen C++" y "Documentación del examen"
#
# Uso:
#   ./preparar.sh                         prepara la cuenta actual
#   sudo ./preparar.sh alumno1 alumno2    prepara esas cuentas y además instala
#                                         la política del sistema (/etc/vscode/policy.json)
#   sudo ./preparar.sh                    con sudo y sin nombres: la cuenta que ejecutó sudo
#   [sudo] ./preparar.sh --desinstalar [cuentas...]

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATOS="$DIR/datos"
COMPILADOR=@COMPILADOR@

info()  { printf '\e[1;34m==>\e[0m %s\n' "$*"; }
aviso() { printf '\e[1;33mAVISO:\e[0m %s\n' "$*" >&2; }
error() { printf '\e[1;31mERROR:\e[0m %s\n' "$*" >&2; exit 1; }

DESINSTALAR=0
if [[ ${1:-} == --desinstalar ]]; then DESINSTALAR=1; shift; fi

# --- Cuentas a preparar ------------------------------------------------------------
if (( $# )); then
    [[ $EUID -eq 0 ]] || error "para preparar otras cuentas ejecútalo con sudo"
    CUENTAS=("$@")
elif [[ $EUID -eq 0 ]]; then
    [[ -n ${SUDO_USER:-} && $SUDO_USER != root ]] \
        || error "indica las cuentas: sudo $0 alumno1 alumno2 ..."
    CUENTAS=("$SUDO_USER")
else
    CUENTAS=("$(id -un)")
fi

# Ejecuta un comando como la cuenta indicada (directamente si ya somos ella)
como() {
    local u=$1; shift
    if [[ $(id -un) == "$u" ]]; then "$@"; else runuser -u "$u" -- "$@"; fi
}

# Carpeta de escritorio de la cuenta (Escritorio, Desktop...)
escritorio() {
    local u=$1 home=$2 d=""
    d=$(como "$u" env HOME="$home" xdg-user-dir DESKTOP 2>/dev/null || true)
    if [[ -z $d || $d == "$home" ]]; then
        for c in Escritorio Desktop; do [[ -d $home/$c ]] && { d=$home/$c; break; }; done
    fi
    echo "${d:-$home/Desktop}"
}

desinstalar_cuenta() {
    local u=$1 home=$2 desk=$3
    rm -rf "$desk/examen"
    como "$u" code --uninstall-extension ms-vscode.cpptools >/dev/null 2>&1 || true
    rm -rf "$home"/.vscode/extensions/ms-vscode.cpptools-*
    rm -f "$home/.local/share/applications/examen-vscode.desktop" \
          "$home/.local/share/applications/examen-docs.desktop"
    local s="$home/.config/Code/User/settings.json"
    if [[ -f $s.antes-examen ]]; then mv -f "$s.antes-examen" "$s"; else rm -f "$s"; fi
}

preparar_cuenta() {
    local u=$1 home=$2 desk=$3 ex="$3/examen"

    # Carpeta del examen en el escritorio
    info "[$u] Carpeta del examen en $ex"
    mkdir -p "$desk"
    rm -rf "$ex"
    cp -r "$DATOS/plantilla/examen" "$ex"
    cp -r "$DATOS/docs/cppreference" "$DATOS/docs/man" "$ex/"

    # Configuración de VS Code (se guarda copia de la que hubiera)
    info "[$u] Configuración de VS Code"
    local cfg="$home/.config/Code/User"
    mkdir -p "$cfg"
    if [[ -f $cfg/settings.json && ! -f $cfg/settings.json.antes-examen ]] \
       && ! cmp -s "$cfg/settings.json" "$DATOS/plantilla/config/settings.json"; then
        cp "$cfg/settings.json" "$cfg/settings.json.antes-examen"
    fi
    cp "$DATOS/plantilla/config/settings.json" "$cfg/settings.json"
    chmod 644 "$cfg/settings.json"
    chmod 644 "$cfg/settings.json"

    # Lanzadores en el menú de aplicaciones (con la ruta real del escritorio)
    mkdir -p "$home/.local/share/applications"
    cat > "$home/.local/share/applications/examen-vscode.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Examen C++ (VS Code)
Comment=Abre Visual Studio Code en la carpeta del examen
Exec=code --new-window "$ex"
Icon=vscode
Terminal=false
Categories=Development;
EOF
    cat > "$home/.local/share/applications/examen-docs.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Documentación del examen
Comment=cppreference, manual del sistema y apuntes
Exec=xdg-open "$ex/LEEME.html"
Icon=help-browser
Terminal=false
Categories=Documentation;
EOF

    # Todo lo creado pertenece a la cuenta (por si se ejecuta con sudo)
    chown "$u": "$desk"
    chown -R "$u": "$ex" "$home/.config/Code" "$home/.local/share/applications"
    chown "$u": "$home/.config" "$home/.local" "$home/.local/share"

    # Extensión C/C++, instalada como la propia cuenta: desde el .vsix si está,
    # si no, desde el Marketplace (hace falta red solo durante la preparación)
    info "[$u] Extensión C/C++ (desde ${EXTENSION##*/})"
    como "$u" code --install-extension "$EXTENSION" --force 2>&1 \
        | grep -v -i -e deprecat -e trace-deprecation || true
    como "$u" code --list-extensions 2>/dev/null | grep -qx ms-vscode.cpptools \
        || error "[$u] la extensión no se ha instalado"
    # La extensión da permiso de ejecución a sus binarios al arrancar; lo adelantamos
    local e
    for e in "$home"/.vscode/extensions/ms-vscode.cpptools-*; do
        find "$e/bin" "$e/debugAdapters/bin" "$e/LLVM/bin" -maxdepth 1 -type f \
             -exec chmod u+x {} + 2>/dev/null || true
    done
}

# --- Política del sistema (solo con sudo): el alumno no puede cambiarla -----------
# Solo permite la extensión C/C++; desactiva modo agente, MCP, telemetría y actualizaciones
politica() {
    mkdir -p /etc/vscode
    if (( DESINSTALAR )); then
        if [[ -f /etc/vscode/policy.json.antes-examen ]]; then
            mv -f /etc/vscode/policy.json.antes-examen /etc/vscode/policy.json
        else
            rm -f /etc/vscode/policy.json
        fi
        return
    fi
    if [[ -f /etc/vscode/policy.json && ! -f /etc/vscode/policy.json.antes-examen ]] \
       && ! cmp -s /etc/vscode/policy.json "$DATOS/plantilla/policy.json"; then
        cp /etc/vscode/policy.json /etc/vscode/policy.json.antes-examen
    fi
    cp "$DATOS/plantilla/policy.json" /etc/vscode/policy.json
    chmod 644 /etc/vscode/policy.json
}

# --- Programa principal ------------------------------------------------------------
if (( ! DESINSTALAR )); then
    [[ -d "$DATOS/docs/cppreference" ]] \
        || error "no encuentro $DATOS (¿has movido preparar.sh fuera de su carpeta?)"
    if [[ -f "$DATOS/cpptools-linux-x64.vsix" ]]; then
        EXTENSION="$DATOS/cpptools-linux-x64.vsix"
    else
        EXTENSION=ms-vscode.cpptools
        aviso "no está datos/cpptools-linux-x64.vsix: la extensión se descargará del Marketplace (hace falta red)"
    fi
    command -v code >/dev/null || error "VS Code no está instalado (comando 'code')"
    [[ -x $COMPILADOR ]] || aviso "no existe $COMPILADOR: IntelliSense no encontrará las cabeceras"
fi

umask 022
for u in "${CUENTAS[@]}"; do
    home=$(getent passwd "$u" | cut -d: -f6) || true
    [[ -n $home && -d $home ]] || { aviso "la cuenta '$u' no existe o no tiene home; la salto"; continue; }
    desk=$(escritorio "$u" "$home")
    if (( DESINSTALAR )); then
        info "[$u] Quitando la preparación del examen"
        desinstalar_cuenta "$u" "$home" "$desk"
    else
        preparar_cuenta "$u" "$home" "$desk"
    fi
done

if [[ $EUID -eq 0 ]]; then
    info "Política del sistema de VS Code (/etc/vscode/policy.json)"
    politica
elif (( ! DESINSTALAR )); then
    aviso "sin sudo no se instala /etc/vscode/policy.json (impide que el alumno añada extensiones)"
fi

if (( DESINSTALAR )); then info "Hecho."; exit 0; fi

cat <<EOF

Listo. Para comprobarlo, SIN RED, abre «Examen C++ (VS Code)» desde el menú de
aplicaciones (o «code ~/Escritorio/examen»): no debe preguntar nada, IntelliSense
debe funcionar en un .cpp y LEEME.html debe abrir la documentación.

Para deshacerlo:  [sudo] $0 --desinstalar [cuentas...]
EOF
