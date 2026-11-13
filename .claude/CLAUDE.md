# CLAUDE.md

Guía para trabajar en este repositorio con Claude Code.

## Qué es

Un generador, no una aplicación: `construir.py` produce `dist/examen-cpp.tar.gz`, el
paquete que los profesores descomprimen en las máquinas del examen para preparar las
cuentas de los alumnos con `preparar.sh`. Las máquinas del examen son Ubuntu 24.04 **sin
red** durante el examen: todo lo que el alumno usa tiene que ir dentro del paquete, salvo
la extensión C/C++, que `preparar.sh` descarga del Marketplace (hay red al preparar).

**Todo en español:** prosa, comentarios, mensajes de los scripts, nombres de funciones.

## Comandos

```bash
uv run construir                                  # construye en dist/ (caché en .cache/)
uv run construir --apuntes ../ssoo-practica-backup  # sin clonar los apuntes
uv run construir --refrescar                      # ignora la caché
```

Dependencias del sistema: `mandoc` (obligatoria), `git`, y `bsdtar` solo para el respaldo
de openSUSE de cppreference. Para probar `preparar.sh` hace falta VS Code (`code`).

## Estructura

- `config.toml`: todo lo que cambia entre cursos. Cualquier valor nuevo va aquí, no
  escrito en el código.
- `construir.py`: un solo módulo con un paso por sección (apuntes, páginas, manual,
  cppreference, empaquetado). Cada descarga se cachea en `.cache/`.
- `plantilla/`: lo que acaba en el paquete. En los `.sh`, `.json`, `.html` y `.md` se
  sustituyen `@COMPILADOR@`, `@ESTANDAR@` y `@PDF@`. `preparar.sh` y `LEEME.md` se colocan
  en la raíz del paquete; el resto queda en `datos/plantilla/`.
- `.github/workflows/construir.yml`: construye en cada push y publica releases.

Estructura del paquete generado:

```
examen-cpp/
├── preparar.sh, LEEME.md
└── datos/
    ├── VERSION                       # de dónde sale cada cosa
    ├── docs/{cppreference,man}/
    └── plantilla/{examen/,config/settings.json}
```

## Decisiones que no hay que deshacer

- **Las páginas del manual se descubren en los `.qmd`**, no en el PDF: el libro enlaza
  cada función a `manpages.debian.org/.../<pagina>.<sec>.es.html`. Se recorren primero los
  apéndices y luego las unidades del perfil, y cada página va al grupo (título del `.qmd`)
  que la enlaza primero.
- **Español de manpages.debian.org, inglés de los paquetes de Debian.** Los paquetes
  `manpages-es` actuales ya no traen traducciones como `open(2)` o `read(2)`, pero
  manpages.debian.org las conserva y son las que enlaza el libro. Muchas son de
  1996-2001, por eso cada página enlaza también a la inglesa actual. Una respuesta de
  manpages.debian.org solo cuenta como traducción si tiene `.SH NOMBRE`; si no, sirve la
  inglesa.
- **La página principal es la española** (`open.2.html`) y la inglesa va aparte
  (`open.2.en.html`). Los alias (`fstat.2`) se agrupan con la canónica en inglés (`stat.2`)
  y tienen una redirección.
- **Nada de cppreference en español:** no existe versión offline y la wiki está desfasada.
- **Firefox snap no lee fuera de `$HOME`**, por eso `preparar.sh` copia la documentación
  en cada cuenta en vez de enlazarla desde `/opt`.
- **`preparar.sh` instala la extensión como el propio usuario** (`runuser`), siempre
  del Marketplace: el paquete no lleva `.vsix`. No crees a mano `extensions.json`: VS Code exige el
  campo `location` y sin él ignora la extensión.
- **Sin arranque automático de VS Code**: lo pidió el profesor. Solo hay lanzadores en el
  menú de aplicaciones.
- **Sin política del sistema** (`/etc/vscode/policy.json`): no se necesita.

## Comprobar un cambio

1. `uv run construir` sin avisos inesperados; revisa el resumen final (páginas y cuántas en
   español).
2. Abre `datos/docs/man/index.html` del paquete y alguna página en los dos idiomas.
3. Con VS Code instalado: crea una cuenta de prueba, ejecuta `sudo ./preparar.sh prueba`,
   comprueba `su - prueba -c 'code --list-extensions'`, y luego `--desinstalar`.
