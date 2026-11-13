#!/usr/bin/env python3
"""Construye el paquete para preparar los puestos del examen de C++ sin conexión.

Pasos (todas las descargas se guardan en la caché, así que repetir es rápido):

1. Apuntes: clona el repo del libro y toma el PDF ya generado del perfil.
2. Descubre las páginas del manual en los enlaces a manpages.debian.org de los
   .qmd del perfil, y les añade las de `[manual] extra` de config.toml.
3. Manual: páginas en inglés de los paquetes de Debian (manpages, manpages-dev) y
   traducciones de manpages.debian.org, convertidas a HTML con mandoc.
4. cppreference: html-book oficial, sin el script de analítica.
5. Extensión C/C++ de VS Code (.vsix linux-x64) del Marketplace.
6. Empaqueta todo con preparar.sh en dist/<nombre>.tar.gz y dist/<nombre>-sin-vsix.tar.gz.

Uso:  uv run construir [--apuntes DIR] [--sin-vsix] [--refrescar]
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import html
import io
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

import yaml

RAIZ = Path(__file__).resolve().parent
UA = "ssoo-cpp-exam-desktop (+https://github.com/ull-esit-sistemas-operativos/ssoo-cpp-exam-desktop)"
DEBIAN = "https://deb.debian.org/debian"
MANPAGES_DEBIAN = "https://manpages.debian.org"
MARKETPLACE = "https://marketplace.visualstudio.com/_apis/public/gallery"


# --- Utilidades -------------------------------------------------------------------

def info(msg: str) -> None:
    print(f"\033[1;34m==>\033[0m {msg}", flush=True)


def aviso(msg: str) -> None:
    print(f"\033[1;33mAVISO:\033[0m {msg}", file=sys.stderr, flush=True)


def error(msg: str) -> NoReturn:
    print(f"\033[1;31mERROR:\033[0m {msg}", file=sys.stderr)
    sys.exit(1)


def leer_url(url: str, datos: bytes | None = None, cabeceras: dict | None = None) -> bytes:
    req = urllib.request.Request(url, data=datos, headers={"User-Agent": UA, **(cabeceras or {})})
    with urllib.request.urlopen(req, timeout=300) as r:
        cuerpo = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or cuerpo[:2] == b"\x1f\x8b" and url.endswith("vspackage"):
            cuerpo = gzip.decompress(cuerpo)
        return cuerpo


def descargar(url: str, destino: Path, refrescar: bool = False) -> Path:
    """Descarga a la caché si no está ya."""
    if destino.exists() and not refrescar:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    tmp.write_bytes(leer_url(url))
    tmp.replace(destino)
    return destino


def ar_miembros(datos: bytes):
    """Recorre un archivo ar (formato de los .deb)."""
    if not datos.startswith(b"!<arch>\n"):
        raise ValueError("no es un archivo ar")
    pos = 8
    while pos + 60 <= len(datos):
        cab = datos[pos:pos + 60]
        nombre = cab[:16].decode().strip().rstrip("/")
        tam = int(cab[48:58].decode().strip())
        yield nombre, datos[pos + 60:pos + 60 + tam]
        pos += 60 + tam + (tam % 2)


def extraer_deb(deb: Path, destino: Path, prefijo: str) -> None:
    """Extrae del data.tar.* del .deb solo lo que cuelga de `prefijo`."""
    for nombre, contenido in ar_miembros(deb.read_bytes()):
        if nombre.startswith("data.tar"):
            with tarfile.open(fileobj=io.BytesIO(contenido)) as tar:
                miembros = [m for m in tar.getmembers()
                            if m.name.lstrip("./").startswith(prefijo)]
                tar.extractall(destino, members=miembros, filter="data")
            return
    raise ValueError(f"{deb.name}: sin data.tar")


def sustituir(texto: str, valores: dict[str, str]) -> str:
    for k, v in valores.items():
        texto = texto.replace(f"@{k}@", v)
    return texto


# --- 1. Apuntes -----------------------------------------------------------------

def obtener_apuntes(cfg: dict, cache: Path, local: Path | None) -> Path:
    if local:
        info(f"Apuntes: usando {local}")
        return local
    destino = cache / "apuntes"
    url = cfg["repo"]
    token = os.environ.get("APUNTES_TOKEN")
    if token and url.startswith("https://github.com/"):
        url = url.replace("https://", f"https://x-access-token:{token}@", 1)
    try:
        if (destino / ".git").exists():
            info("Apuntes: actualizando el repositorio")
            subprocess.run(["git", "-C", destino, "fetch", "-q", "--depth", "1", url, cfg["rama"]], check=True)
            subprocess.run(["git", "-C", destino, "reset", "-q", "--hard", "FETCH_HEAD"], check=True)
        else:
            info("Apuntes: clonando el repositorio")
            shutil.rmtree(destino, ignore_errors=True)
            subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", cfg["rama"], url, destino],
                           check=True)
    except subprocess.CalledProcessError:
        error(f"no se pudo obtener {cfg['repo']}. Si es privado, define APUNTES_TOKEN o usa --apuntes DIR")
    return destino


# --- 2. Páginas del manual a incluir ---------------------------------------------

ENLACE_MAN = re.compile(
    r"manpages\.debian\.org/(?:[^/\s)\"'>]+/)*?([A-Za-z0-9_.+-]+?)\.(\d[a-z]*)\.(?:es|en)\.html")


def titulo_qmd(texto: str) -> str:
    if texto.startswith("---"):
        fin = texto.find("\n---", 3)
        texto = texto[fin + 4:] if fin >= 0 else texto
    m = re.search(r"^# (.+?)\s*(\{.*\})?\s*$", texto, re.M)
    return m.group(1).strip() if m else "Otras"


def descubrir_paginas(apuntes: Path, cfg_apuntes: dict, cfg_manual: dict) -> list[tuple[str, str]]:
    """Lista ordenada de (grupo, página) según los enlaces del perfil.

    Se recorren antes los apéndices (son la referencia de la API) y luego las
    unidades; cada página va al grupo del primer archivo que la enlaza.
    """
    perfil = yaml.safe_load((apuntes / cfg_apuntes["perfil"]).read_text(encoding="utf-8"))
    libro = perfil.get("book", {})
    archivos = list(libro.get("appendices", [])) + list(libro.get("chapters", []))
    vistas: dict[str, str] = {}
    orden: list[tuple[str, str]] = []
    for rel in archivos:
        ruta = apuntes / rel
        if not ruta.exists():
            aviso(f"el perfil cita {rel}, que no existe")
            continue
        texto = ruta.read_text(encoding="utf-8")
        grupo = titulo_qmd(texto)
        for nombre, sec in ENLACE_MAN.findall(texto):
            pagina = f"{nombre}.{sec}"
            if pagina not in vistas:
                vistas[pagina] = grupo
                orden.append((grupo, pagina))
    for pagina in cfg_manual.get("extra", []):
        if pagina not in vistas:
            vistas[pagina] = "Otras funciones útiles"
            orden.append(("Otras funciones útiles", pagina))
    return orden


# --- 3. Manual en HTML ------------------------------------------------------------

def paquetes_debian(suite: str, nombres: set[str], cache: Path, refrescar: bool) -> dict[str, str]:
    """Ruta en el pool de cada paquete (Arch: all) de la suite."""
    idx = descargar(f"{DEBIAN}/dists/{suite}/main/binary-all/Packages.xz",
                    cache / f"debian-{suite}-Packages.xz", refrescar)
    rutas = {}
    for estrofa in lzma.decompress(idx.read_bytes()).decode("utf-8").split("\n\n"):
        campos = dict(re.findall(r"^([A-Za-z-]+): (.*)$", estrofa, re.M))
        if campos.get("Package") in nombres:
            rutas[campos["Package"]] = campos["Filename"]
    if falta := nombres - rutas.keys():
        error(f"no encuentro en Debian {suite}: {', '.join(sorted(falta))}")
    return rutas


def man_ingles(suite: str, cache: Path, refrescar: bool) -> Path:
    destino = cache / f"man-en-{suite}"
    rutas = paquetes_debian(suite, {"manpages", "manpages-dev"}, cache, refrescar)
    marca = destino / ".versiones"
    firma = json.dumps(rutas, sort_keys=True)
    if marca.exists() and marca.read_text() == firma and not refrescar:
        return destino / "usr/share/man"
    info(f"Manual en inglés: {', '.join(Path(r).name for r in rutas.values())}")
    shutil.rmtree(destino, ignore_errors=True)
    for ruta in rutas.values():
        deb = descargar(f"{DEBIAN}/{ruta}", cache / "debs" / Path(ruta).name)
        extraer_deb(deb, destino, "usr/share/man")
    marca.write_text(firma)
    return destino / "usr/share/man"


def leer_fuente(ruta: Path) -> str:
    datos = ruta.read_bytes()
    if datos[:2] == b"\x1f\x8b":
        datos = gzip.decompress(datos)
    try:
        return datos.decode("utf-8")
    except UnicodeDecodeError:
        return datos.decode("latin-1")


def buscar_en(raiz: Path, pagina: str, prof: int = 0) -> tuple[Path, str] | None:
    """Fuente inglesa de la página, siguiendo enlaces simbólicos y .so."""
    sec = pagina.rsplit(".", 1)[1]
    for cand in (raiz / f"man{sec[0]}" / f"{pagina}.gz", raiz / f"man{sec[0]}" / pagina):
        if cand.exists() or cand.is_symlink():
            if cand.is_symlink():
                destino = Path(os.readlink(cand)).name.removesuffix(".gz")
                return buscar_en(raiz, destino, prof + 1) if prof < 4 else None
            m = re.match(r"\s*\.so\s+(\S+)", leer_fuente(cand))
            if m:
                destino = Path(m.group(1)).name.removesuffix(".gz")
                return buscar_en(raiz, destino, prof + 1) if prof < 4 else None
            return cand, pagina
    return None


def es_espanol(fuente: str) -> bool:
    return re.search(r'^\.SH\s+"?NOMBRE"?', fuente, re.M) is not None


def buscar_es(suite: str, pagina: str, cache: Path, refrescar: bool, prof: int = 0) -> tuple[Path, str] | None:
    """Traducción de manpages.debian.org (la misma que enlaza el libro), si existe."""
    destino = cache / "man-es" / suite / pagina
    falta = destino.with_suffix(destino.suffix + ".no")
    if falta.exists() and not refrescar:
        return None
    if not destino.exists() or refrescar:
        try:
            fuente = leer_url(f"{MANPAGES_DEBIAN}/{suite}/manpages-es/{pagina}.es.gz")
        except urllib.error.HTTPError:
            fuente = b""
        if fuente[:2] == b"\x1f\x8b":
            fuente = gzip.decompress(fuente)
        destino.parent.mkdir(parents=True, exist_ok=True)
        texto = fuente.decode("utf-8", "replace")
        m = re.match(r"\s*\.so\s+(\S+)", texto)
        if not (es_espanol(texto) or m):
            falta.touch()
            return None
        destino.write_bytes(fuente)
    m = re.match(r"\s*\.so\s+(\S+)", leer_fuente(destino))
    if m:
        otra = Path(m.group(1)).name.removesuffix(".gz")
        return buscar_es(suite, otra, cache, refrescar, prof + 1) if prof < 4 else None
    return destino, pagina


def mandoc(fuente: Path) -> str:
    r = subprocess.run(["mandoc", "-K", "utf-8", "-T", "html", "-O", "fragment"],
                       input=leer_fuente(fuente).encode("utf-8"), capture_output=True)
    if not r.stdout:
        aviso(f"mandoc no ha generado nada para {fuente.name}: {r.stderr.decode()[:200]}")
    return r.stdout.decode("utf-8")


@dataclass
class Pagina:
    nombre: str                                    # página canónica en inglés (stat.2)
    grupo: str
    alias: list[str] = field(default_factory=list)  # nombres enlazados (fstat.2, lstat.2)
    html: dict[str, str] = field(default_factory=dict)  # idioma -> cuerpo

    def archivo(self, idioma: str) -> str:
        # La principal es la española si existe; la inglesa queda aparte
        if idioma == "en" and len(self.html) == 2:
            return f"{self.nombre}.en.html"
        return f"{self.nombre}.html"

    def etiqueta(self) -> str:
        nombres = [n.rsplit(".", 1)[0] for n in [self.nombre, *self.alias]]
        return " / ".join(dict.fromkeys(nombres))


def generar_manual(lista: list[tuple[str, str]], cfg: dict, cache: Path, salida: Path,
                   refrescar: bool) -> dict:
    if not shutil.which("mandoc"):
        error("falta mandoc (sudo apt install mandoc)")
    suite = cfg.get("suite", "testing")
    raiz_en = man_ingles(suite, cache, refrescar)
    renombradas = cfg.get("renombradas_en", {})

    info(f"Manual: {len(lista)} páginas enlazadas; buscando traducciones")
    paginas: dict[str, Pagina] = {}
    for grupo, enlazada in lista:
        en = buscar_en(raiz_en, renombradas.get(enlazada, enlazada))
        es = buscar_es(suite, enlazada, cache, refrescar)
        if not en and not es:
            aviso(f"no existe la página {enlazada}; la salto")
            continue
        # Las variantes (fstat → stat) se agrupan con su página canónica
        clave = en[1] if en and enlazada not in renombradas else enlazada
        if clave in paginas:
            if enlazada != clave and enlazada not in paginas[clave].alias:
                paginas[clave].alias.append(enlazada)
            if es and "es" not in paginas[clave].html:
                paginas[clave].html = {"es": mandoc(es[0]), **paginas[clave].html}
            continue
        p = Pagina(clave, grupo, [enlazada] if enlazada != clave else [])
        if es is None and en and en[1] != enlazada:
            es = buscar_es(suite, en[1], cache, refrescar)
        if es:
            p.html["es"] = mandoc(es[0])
        if en:
            p.html["en"] = mandoc(en[0])
        paginas[clave] = p

    # Redirecciones para los nombres alternativos (fstat.2.html → stat.2.html)
    salida.mkdir(parents=True, exist_ok=True)
    redir = {a: p.nombre for p in paginas.values() for a in p.alias}
    for alias, destino in redir.items():
        (salida / f"{alias}.html").write_text(
            f'<!DOCTYPE html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={destino}.html">'
            f'<a href="{destino}.html">{destino}</a>\n', encoding="utf-8")

    def resolver(nombre: str) -> Pagina | None:
        return paginas.get(nombre) or paginas.get(redir.get(nombre, ""))

    for p in paginas.values():
        for idioma, cuerpo in p.html.items():
            def enlace(m: re.Match, p: Pagina = p, idioma: str = idioma) -> str:
                destino = resolver(f"{m.group(1)}.{m.group(2)}")
                if destino and destino is not p:
                    return f'<a href="{destino.archivo(idioma)}">{m.group(0)}</a>'
                return m.group(0)
            cuerpo = re.sub(r"<b>([A-Za-z_0-9-]+)</b>\(([0-9][a-z]*)\)", enlace, cuerpo)
            nombre, sec = p.nombre.rsplit(".", 1)
            if len(p.html) == 2:
                otro = "en" if idioma == "es" else "es"
                texto = "Versión en inglés (actualizada)" if otro == "en" else "Versión en español"
                cambio = f'<a href="{p.archivo(otro)}">{texto}</a>'
            else:
                cambio = '<span class="lang">Solo en inglés</span>' if idioma == "en" else ""
            (salida / p.archivo(idioma)).write_text(f"""<!DOCTYPE html>
<html lang="{idioma}"><head><meta charset="utf-8">
<title>{html.escape(nombre)}({sec})</title>
<link rel="stylesheet" href="man.css"></head>
<body><nav class="top"><a href="index.html">&larr; Índice</a>{cambio}</nav>
{cuerpo}
</body></html>
""", encoding="utf-8")

    # Índice
    partes = ["""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>Manual del sistema</title>
<link rel="stylesheet" href="man.css"></head><body class="index">
<h1>Manual del sistema (man)</h1>
<p>Páginas del manual de Linux de las funciones que se usan en la práctica.
Se abre la traducción al español cuando existe. Muchas traducciones son antiguas,
así que cada una enlaza también a la versión en inglés, que es la actualizada.</p>
<p>Para el lenguaje y la biblioteca estándar de C++ usa
<a href="../cppreference/en/cpp.html">cppreference</a>.</p>
"""]
    actual = None
    for p in paginas.values():
        if p.grupo != actual:
            if actual is not None:
                partes.append("</ul>")
            partes.append(f"<h2>{html.escape(p.grupo)}</h2><ul>")
            actual = p.grupo
        sec = p.nombre.rsplit(".", 1)[1]
        marcas = ' <span class="tag es">ES</span>' if "es" in p.html else ""
        if "en" in p.html:
            marcas += f' <a class="tag en" href="{p.archivo("en")}">EN</a>'
        partes.append(f'<li><a href="{p.nombre}.html">{html.escape(p.etiqueta())}</a> '
                      f'<span class="sec">({sec})</span>{marcas}</li>')
    partes.append("</ul></body></html>\n")
    (salida / "index.html").write_text("\n".join(partes), encoding="utf-8")
    (salida / "man.css").write_text(CSS_MAN, encoding="utf-8")

    n_es = sum("es" in p.html for p in paginas.values())
    info(f"Manual: {len(paginas)} páginas, {n_es} con traducción al español")
    return {"paginas": len(paginas), "en_espanol": n_es, "suite": suite}


CSS_MAN = """
body{font-family:system-ui,sans-serif;max-width:52rem;margin:1rem auto;padding:0 1rem;line-height:1.45;color:#222}
nav.top{display:flex;justify-content:space-between;border-bottom:1px solid #ccc;padding-bottom:.4rem;margin-bottom:1rem}
.lang{font-size:.85em;color:#666}
h1.Sh,h1{font-size:1.15rem;margin-top:1.6rem;border-bottom:1px solid #ddd}
h1 a.permalink,h2 a.permalink,h1.Sh a,h2.Ss a{color:inherit;text-decoration:none}
body.index h1{font-size:1.6rem}
h2{font-size:1.15rem;margin-top:1.4rem}
pre,code,.Nm,.Fn,.Fa,.Ft,.Cm,.Fl{font-family:ui-monospace,monospace}
pre{background:#f5f5f5;padding:.6rem;overflow-x:auto}
.Nm,.Fn,.Cm{font-weight:bold}
.Fa,.Ar{font-style:italic}
table.head,table.foot{width:100%;color:#666;font-size:.85em}
td.head-rtitle,td.foot-os{text-align:right}
dl.Bl-tag dt{font-weight:bold;margin-top:.5rem}
dl.Bl-tag dd{margin-left:2rem}
.tag{font-size:.7em;padding:0 .3em;border-radius:3px;font-weight:bold}
a.tag{text-decoration:none}
.tag.es{background:#d7f0d7;color:#1b5e20}.tag.en{background:#e3e8f5;color:#1a3a7a}
.sec{color:#777}
ul{columns:2;column-gap:2rem}li{margin:.15rem 0;break-inside:avoid}
@media(max-width:40rem){ul{columns:1}}
"""


# --- 4. cppreference --------------------------------------------------------------

ANALITICA = re.compile(
    rb'<script async src="https://www\.googletagmanager\.com/[^"]*"></script>\s*'
    rb'<script>\s*window\.dataLayer.*?</script>\s*', re.S)


def cppreference(cfg: dict, cache: Path, salida: Path, refrescar: bool) -> dict:
    version = cfg["version"]
    extraido = cache / f"cppreference-{version}"
    if not (extraido / "en" / "cpp.html").exists() or refrescar:
        shutil.rmtree(extraido, ignore_errors=True)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                archivo = descargar(cfg["url"], cache / Path(cfg["url"]).name, refrescar)
                info(f"cppreference: {archivo.name}")
                with tarfile.open(archivo) as tar:
                    tar.extractall(tmp, filter="data")
            except (urllib.error.URLError, tarfile.TarError) as e:
                aviso(f"no se pudo usar {cfg['url']} ({e}); pruebo con openSUSE")
                cppreference_opensuse(cfg, version, cache, tmp)
            raiz = next((p.parent.parent for p in tmp.rglob("en/cpp.html")), None)
            if raiz is None:
                error("el archivo de cppreference no tiene en/cpp.html")
            shutil.move(raiz, extraido)
        n = 0
        for f in extraido.rglob("*.html"):
            datos = f.read_bytes()
            limpio = ANALITICA.sub(b"", datos)
            if limpio != datos:
                f.write_bytes(limpio)
                n += 1
        info(f"cppreference: analítica quitada de {n} páginas")
    shutil.copytree(extraido, salida, symlinks=True)
    return {"version": version}


def cppreference_opensuse(cfg: dict, version: str, cache: Path, tmp: Path) -> None:
    if not shutil.which("bsdtar"):
        error("para el respaldo de openSUSE hace falta bsdtar (sudo apt install libarchive-tools)")
    indice = leer_url(cfg["respaldo_opensuse"]).decode()
    rpms = sorted(set(re.findall(rf"cppreference-doc-{version}-[\d.]+\.noarch\.rpm", indice)))
    if not rpms:
        error(f"openSUSE no tiene cppreference-doc {version}")
    rpm = descargar(cfg["respaldo_opensuse"] + rpms[-1], cache / rpms[-1])
    info(f"cppreference: {rpm.name}")
    subprocess.run(["bsdtar", "-xf", rpm, "-C", tmp, "./usr/share/cppreference/doc/html"], check=True)


# --- 5. Extensión C/C++ -----------------------------------------------------------

def vsix_cpptools(version: str, cache: Path, refrescar: bool) -> tuple[Path, str]:
    consulta = json.dumps({"filters": [{"criteria": [{"filterType": 7, "value": "ms-vscode.cpptools"}]}],
                           "flags": 0x1 | 0x2 | 0x10}).encode()
    try:
        resp = json.loads(leer_url(f"{MARKETPLACE}/extensionquery", consulta, {
            "Content-Type": "application/json",
            "Accept": "application/json;api-version=7.2-preview.1"}))
        versiones = resp["results"][0]["extensions"][0]["versions"]
    except (urllib.error.URLError, KeyError, IndexError) as e:
        error(f"no se pudo consultar el Marketplace: {e}")

    def estable(v: dict) -> bool:
        props = {p["key"]: p["value"] for p in v.get("properties", [])}
        return props.get("Microsoft.VisualStudio.Code.PreRelease") != "true"

    candidatas = [v for v in versiones if v.get("targetPlatform") == "linux-x64"
                  and (v["version"] == version if version != "ultima" else estable(v))]
    if not candidatas:
        error(f"no hay cpptools {version} para linux-x64 en el Marketplace")
    elegida = candidatas[0]["version"]
    destino = cache / f"cpptools-{elegida}-linux-x64.vsix"
    if not destino.exists() or refrescar:
        info(f"Extensión C/C++ {elegida}: descargando")
        url = (f"{MARKETPLACE}/publishers/ms-vscode/vsextensions/cpptools/{elegida}"
               f"/vspackage?targetPlatform=linux-x64")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(leer_url(url))
    if not zipfile.is_zipfile(destino):
        destino.unlink()
        error("el .vsix descargado no es un zip válido")
    return destino, elegida


# --- 6. Empaquetado -------------------------------------------------------------------

def copiar_plantilla(origen: Path, destino: Path, valores: dict[str, str]) -> None:
    for f in origen.rglob("*"):
        rel = f.relative_to(origen)
        d = destino / rel
        if f.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        if f.suffix in {".sh", ".json", ".html", ".md"}:
            d.write_text(sustituir(f.read_text(encoding="utf-8"), valores), encoding="utf-8")
            shutil.copymode(f, d)
        else:
            shutil.copy2(f, d)


def empaquetar(dir_paquete: Path, salida: Path, nombre: str, excluir: set[str]) -> Path:
    archivo = salida / f"{nombre}.tar.gz"

    def filtro(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if Path(ti.name).name in excluir:
            return None
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        return ti

    with tarfile.open(archivo, "w:gz") as tar:
        tar.add(dir_paquete, arcname=dir_paquete.name, filter=filtro)
    return archivo


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=RAIZ / "config.toml")
    ap.add_argument("--cache", type=Path, default=RAIZ / ".cache")
    ap.add_argument("--salida", type=Path, default=RAIZ / "dist")
    ap.add_argument("--apuntes", type=Path, help="usar una copia local del repo de apuntes en vez de clonarlo")
    ap.add_argument("--sin-vsix", action="store_true", help="no descargar la extensión (solo el paquete sin .vsix)")
    ap.add_argument("--refrescar", action="store_true", help="volver a descargar todo aunque esté en la caché")
    args = ap.parse_args()

    cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    cache, salida = args.cache.resolve(), args.salida.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    nombre = cfg["paquete"]["nombre"]

    apuntes = obtener_apuntes(cfg["apuntes"], cache, args.apuntes)
    pdf = apuntes / cfg["apuntes"]["pdf"]
    if not pdf.exists():
        error(f"no existe {pdf}; ¿se ha renderizado el perfil en el repo de apuntes?")
    commit = subprocess.run(["git", "-C", apuntes, "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip() or "local"

    with tempfile.TemporaryDirectory() as tmp:
        paquete = Path(tmp) / nombre
        datos = paquete / "datos"
        valores = {
            "COMPILADOR": cfg["vscode"]["compilador"],
            "ESTANDAR": cfg["vscode"]["estandar"],
            "PDF": pdf.name,
        }
        copiar_plantilla(RAIZ / "plantilla", datos / "plantilla", valores)
        for f in ("preparar.sh", "LEEME.md"):
            (datos / "plantilla" / f).replace(paquete / f)
        (paquete / "preparar.sh").chmod(0o755)
        shutil.copy2(pdf, datos / "plantilla" / "examen" / pdf.name)

        lista = descubrir_paginas(apuntes, cfg["apuntes"], cfg["manual"])
        man = generar_manual(lista, cfg["manual"], cache, datos / "docs" / "man", args.refrescar)
        cpp = cppreference(cfg["cppreference"], cache, datos / "docs" / "cppreference", args.refrescar)

        version_ext = None
        if not args.sin_vsix:
            vsix, version_ext = vsix_cpptools(str(cfg["vscode"]["cpptools"]), cache, args.refrescar)
            shutil.copy2(vsix, datos / "cpptools-linux-x64.vsix")

        hoy = dt.date.today().isoformat()
        (datos / "VERSION").write_text(
            f"Generado: {hoy}\n"
            f"Apuntes: {cfg['apuntes']['repo']} @ {commit} ({pdf.name})\n"
            f"Manual: {man['paginas']} páginas, {man['en_espanol']} en español (Debian {man['suite']})\n"
            f"cppreference: {cpp['version']}\n"
            f"cpptools: {version_ext or 'se descarga al preparar'}\n", encoding="utf-8")

        salida.mkdir(parents=True, exist_ok=True)
        hechos = []
        if version_ext:
            hechos.append(empaquetar(paquete, salida, nombre, set()))
        hechos.append(empaquetar(paquete, salida, f"{nombre}-sin-vsix", {"cpptools-linux-x64.vsix"}))

    print()
    print(f"Apuntes @ {commit} · {man['paginas']} páginas del manual "
          f"({man['en_espanol']} en español) · cppreference {cpp['version']} · "
          f"cpptools {version_ext or '—'}")
    for h in hechos:
        print(f"  {h.relative_to(Path.cwd()) if h.is_relative_to(Path.cwd()) else h}"
              f"  ({h.stat().st_size / 2**20:.0f} MB)")


if __name__ == "__main__":
    main()
