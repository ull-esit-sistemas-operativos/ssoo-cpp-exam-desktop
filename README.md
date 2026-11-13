# ssoo-cpp-exam-desktop

Genera el paquete para preparar los puestos del examen de C++ de *Sistemas Operativos*
(Universidad de La Laguna) en máquinas Ubuntu **sin conexión a internet**.

Cada cuenta preparada tiene en el escritorio una carpeta `examen/` con:

- el PDF de la práctica (unidades 1-3);
- **cppreference** offline;
- el **manual del sistema** en HTML con las páginas que enlaza la práctica: en español
  cuando hay traducción y siempre con la versión en inglés actualizada;
- VS Code configurado: extensión C/C++, `g++-15` y C++23 en IntelliSense, IA desactivada.

## Descargar el paquete

Lo más fácil es bajarlo ya hecho de [Releases](../../releases):

| Archivo | Cuándo usarlo |
|---|---|
| `examen-cpp.tar.gz` | la máquina no tiene red ni siquiera para prepararla |
| `examen-cpp-sin-vsix.tar.gz` | hay red al preparar (la extensión se descarga entonces) |

Las instrucciones para preparar las cuentas están en el `LEEME.md` de dentro del paquete.
En resumen:

```bash
tar -xzf examen-cpp.tar.gz && cd examen-cpp
sudo ./preparar.sh alumno1 alumno2 ...
```

## Construirlo

Hace falta [uv](https://docs.astral.sh/uv/), `git`, `mandoc` y, solo si falla la descarga
principal de cppreference, `bsdtar`:

```bash
sudo apt install mandoc libarchive-tools
uv run construir                      # deja los paquetes en dist/
uv run construir --apuntes ../ssoo-practica-backup   # con una copia local de los apuntes
```

La primera vez descarga unos 250 MB (todo queda en `.cache/`); las siguientes tarda
segundos. `--refrescar` fuerza a descargarlo todo de nuevo.

Lo que hace, paso a paso:

1. **Apuntes:** clona el [repo de la práctica](https://github.com/ull-esit-sistemas-operativos/ssoo-practica-backup)
   y copia el PDF ya generado del perfil `basico`.
2. **Páginas del manual:** las descubre en los enlaces a manpages.debian.org de los
   `.qmd` de ese perfil, y añade las de `[manual] extra` de `config.toml`.
3. **Manual:** inglés de los paquetes `manpages` y `manpages-dev` de Debian; español de
   manpages.debian.org, las mismas páginas que enlaza el libro. Las convierte con `mandoc`.
4. **cppreference:** el html-book oficial, sin el script de Google Analytics.
5. **Extensión:** `ms-vscode.cpptools` para linux-x64 del Marketplace.
6. **Empaquetado:** con `plantilla/` (incluye `preparar.sh`) en `dist/`.

## Configuración

Todo lo que cambia de un curso a otro está en [`config.toml`](config.toml): el repo y el
PDF de los apuntes, páginas extra del manual, la versión de cppreference, el compilador,
el estándar y la versión de la extensión.

## GitHub Actions

El workflow [`construir.yml`](.github/workflows/construir.yml) construye el paquete en
cada push a `main` y lo publica como release al lanzarlo a mano (*Actions → Construir
paquete del examen → Run workflow*) o al subir una etiqueta `v*`.

Como el repo de los apuntes es privado, necesita el secreto **`APUNTES_TOKEN`**: un
*fine-grained token* con permiso de solo lectura (*Contents: Read*) sobre
`ssoo-practica-backup`. Se añade en *Settings → Secrets and variables → Actions*.
