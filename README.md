# Vision AI Zabbix 1.0.3

Sistema de monitoreo de televisión digital para Raspberry Pi 4 con hasta dos
capturadoras USB independientes.

Incluye:

- Pantalla negra con diferenciación de gráficos y movimiento.
- Ausencia de audio.
- Digitalización o macroblocks.
- Imagen congelada validada junto con ausencia de audio (lógica V1.6).
- Identificación OCR de RED2, RED5, RED9 y FORO.
- Evidencias de 30 segundos con duración real completa en JSON.
- Dashboard HLS 480x270 a 15 FPS con ajuste A/V de 0.8 segundos.
- Telegram al finalizar la falla y horarios para identificaciones.
- Zabbix por SNMPv2c, métricas y traps.
- ZeroTier y WireGuard administrables desde el dashboard.
- Descubrimiento estable de video y audio por puerto USB.

## Plataforma soportada

- Raspberry Pi 4B de 8 GB.
- Raspberry Pi OS 64-bit basado en Debian Bookworm.
- Una o dos capturadoras UVC/UAC con MJPEG 1280x720 y audio estéreo 48 kHz.

## Instalación de un solo comando

En una Raspberry nueva:

```bash
curl -fsSL \
https://raw.githubusercontent.com/gadiel379/VisionAI_ZABBIZ_1.0.3/v1.0.3-r2/install.sh \
| sudo bash
```

El instalador detecta el usuario que ejecutó `sudo`, instala dependencias,
crea el entorno Python, instala systemd, SNMP, controles VPN, detecta hasta dos
capturadoras e inicia el dashboard.

Al finalizar muestra una dirección similar a:

```text
http://IP_DE_LA_RASPBERRY:5000
```

## Configuración posterior

La instalación ya contiene los valores validados de alarmas, OCR, clips,
dashboard y los canales de referencia. Desde `CONFIGURACIÓN` solamente deben
capturarse los valores propios del sitio:

1. Red e IP mostrada por el sistema.
2. Servidor, comunidad y puertos SNMPv2c.
3. Token, chat ID y horarios de Telegram.
4. Network ID de ZeroTier o archivo de WireGuard.

Configura la contraseña local de recuperación de SuperAdmin en cada Raspberry:

```bash
~/vision_ai/venv/bin/python ~/vision_ai/scripts/security_setup.py
```

La contraseña se captura de forma oculta y solo se guarda su hash. SuperAdmin
únicamente puede restablecer la contraseña de Admin desde
`CONFIGURACIÓN > SEGURIDAD`.

Las credenciales se guardan únicamente en:

```text
~/vision_ai/config/integrations.yaml
```

El archivo tiene permisos `600`, está ignorado por Git y nunca debe subirse.

## Capturadoras

El instalador empareja video y audio utilizando el mismo padre USB. Nunca usa
el audio de una capturadora con el video de otra. Las asignaciones se conservan
por puerto físico y pueden revisarse en `CONFIGURACIÓN > CAPTURADORAS`.

Para una instalación idéntica a la referencia:

- Conecta la señal RED5 al mismo puerto físico usado como Capturadora 1.
- Conecta la señal RED2 al mismo puerto físico usado como Capturadora 2.

Si se invierten los cables o los puertos, basta con seleccionar cada equipo en
el dashboard; los datos del canal y los detectores no se pierden.

## Verificación

```bash
sudo vision-ai-verify
```

Comprobación manual:

```bash
sudo systemctl status vision-ai.service --no-pager
sudo journalctl -u vision-ai.service -n 150 --no-pager
```

## Actualización

Una actualización vuelve a ejecutar el instalador y conserva:

- `config/channels.yaml`
- `config/integrations.yaml`
- plantillas OCR personalizadas
- eventos, clips y snapshots

```bash
vision-ai-update v1.0.3-r2
```

## Zabbix y SNMPv2c

El árbol local utilizado es:

```text
1.3.6.1.4.1.8072.9999.1
```

No representa un PEN empresarial registrado. Consulta la documentación en
[`docs/ZABBIX_SNMP.md`](docs/ZABBIX_SNMP.md).

## Seguridad

- No publiques `config/integrations.yaml`.
- No publiques archivos WireGuard ni llaves privadas.
- La rama `main` debe permanecer protegida.
- Instala únicamente tags publicados, por ejemplo `v1.0.3-r2`; no uses `main` en
  equipos de producción.
- El dashboard debe permanecer en una LAN o VPN controlada.

## Autor

ING. GADIEL AMINADAB ORTIZ GUTIÉRREZ  
OPER. DE TX Y MTTO TR. CE MÉRIDA, YUCATÁN.

Desarrollo e implementación del Sistema de Monitoreo Zabbix.

Consulta [NOTICE](NOTICE) para las condiciones de publicación.
