# Entorno para el examen de C++ sin conexión

## Preparación

1. Copia esta carpeta a la máquina del examen (USB, red interna…).
2. Ejecuta:

   ```bash
   ./preparar.sh                            # desde la cuenta del alumno
   sudo ./preparar.sh alumno1 alumno2 ...   # o todas las cuentas de una vez
   ```

   `sudo` solo hace falta para preparar cuentas distintas de la tuya.

   La extensión C/C++ se descarga del Marketplace: hace falta red durante la
   preparación, pero no después.

3. Prueba con una cuenta y **sin red**: abre «Examen C++ (VS Code)» desde el menú de
   aplicaciones. No debe preguntar nada e IntelliSense debe funcionar con @ESTANDAR@.

Para deshacerlo: `[sudo] ./preparar.sh --desinstalar [cuentas...]`

## Qué deja en cada cuenta

| Dónde | Qué |
|---|---|
| `~/Escritorio/examen/` (o `~/Desktop`) | `@PDF@`, `cppreference/`, `man/` y `LEEME.html` (índice de la documentación) |
| `~/Escritorio/examen/.vscode/c_cpp_properties.json` | IntelliSense con `@COMPILADOR@` y @ESTANDAR@ |
| `~/.vscode/extensions/` | extensión C/C++ de Microsoft para linux-x64 (no descarga nada al usarse) |
| `~/.config/Code/User/settings.json` | IA desactivada, sin pregunta de confianza, sin actualizaciones ni telemetría, autoguardado |
| menú de aplicaciones | «Examen C++ (VS Code)» y «Documentación del examen» |

Si la cuenta ya tenía `settings.json`, se guarda como `settings.json.antes-examen`
y se restaura al desinstalar. `datos/VERSION` indica de dónde sale cada cosa.
