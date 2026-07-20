# Zabbix por SNMPv2c

Vision AI expone métricas mediante `snmpd` y envía traps SNMPv2c. El acceso de
lectura queda limitado a la IP del servidor Zabbix indicada en el dashboard.

## Árbol OID local

Base:

```text
1.3.6.1.4.1.8072.9999.1
```

Este árbol es privado y local; no corresponde a un PEN registrado.

| OID | Tipo | Descripción |
|---|---|---|
| `.1.1` | Integer | Estado del servicio |
| `.1.2` | Integer | CPU en centésimas de porcentaje |
| `.1.3` | Integer | RAM en centésimas de porcentaje |
| `.1.4` | Integer | Temperatura en décimas de °C |
| `.1.5` | Integer | Disco usado en centésimas de porcentaje |
| `.1.6` | Integer | Capacidad total en MB |
| `.1.7` | Integer | Capacidad libre en MB |
| `.1.8` | Integer | Epoch de actualización |
| `.2.1` | Integer | Estado de capture_1 |
| `.2.2` | Integer | Estado de capture_2 |
| `.3.1`–`.3.12` | Mixto | Último evento y sus datos |

Estados de capturadora:

```text
0 = deshabilitada
1 = funcionando
2 = sin frames recientes
3 = dispositivo inexistente
4 = métricas vencidas o servicio detenido
```

Traps:

| OID | Descripción |
|---|---|
| `.0.1` | Falla menor a un minuto finalizada |
| `.0.2` | Falla superior a un minuto activa |
| `.0.3` | Falla superior a un minuto finalizada |
| `.0.4` | Identificación de canal |

## Prueba

Sustituye los valores por los configurados en el dashboard:

```bash
snmpwalk -v2c -c COMUNIDAD IP_RASPBERRY \
1.3.6.1.4.1.8072.9999.1
```

Nunca guardes la comunidad SNMP en este repositorio.
