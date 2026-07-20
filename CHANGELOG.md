# Historial de cambios

## 1.0.3 - 2026-07-20

- Distribución portable para Raspberry Pi OS Bookworm.
- Instalador idempotente de un solo comando.
- Dos pipelines independientes con asociación estable USB de audio y video.
- Conservación de configuración, plantillas y evidencias durante actualizaciones.
- Instalación automatizada de systemd, SNMPv2c, ZeroTier y WireGuard.
- Controladores privilegiados limitados mediante sudoers.
- Arranque del dashboard aunque una capturadora tarde o no esté conectada.
- Lógica V1.6: imagen congelada solamente cuando coincide con ausencia de audio.
- Dashboard identificado como versión 1.0.3.

## Validaciones heredadas

- Alarmas de 10 segundos.
- Clips objetivo de 30 segundos y duración real completa en JSON.
- HLS 480x270, 15 FPS y ajuste A/V de 0.8 segundos.
- OCR dinámico según `config/channels.yaml`.
- Telegram final con un solo clip por falla.
- Identificaciones por dos ventanas horarias.
- Paginación de eventos.
- Métricas y traps Zabbix por SNMPv2c.
