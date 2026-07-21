# Historial de cambios

## 1.0.3-r3 - corrección del instalador

- Evita un falso negativo al verificar los codificadores libx264 y AAC con
  `pipefail` activo.

## 1.0.3 - actualización de seguridad

- Agrega la pestaña Seguridad al dashboard.
- Unifica la autorización de RED/SNMP, Telegram y VPN con el usuario Admin.
- Permite que Admin cambie su propia contraseña.
- Agrega SuperAdmin únicamente para restablecer la contraseña de Admin.
- Conserva la contraseña actual de Admin al actualizar desde 1.0.3.

## 1.0.3 - publicación inicial - 2026-07-20

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
