# SRB – Sistema de Reserva de Boletos (Entrega 1: arquitectura base)

Operaciones implementadas: **Consulta** y **Reserva** (sin tolerancia a fallos, sin cancelaciones).

## Requisitos
- Python 3.10+
- `pip install pyzmq` (SQLite viene incluido en Python)

## Arquitectura y puertos
| Nodo | Proceso | Puerto |
|---|---|---|
| M3 Almacenamiento | `persistencia.py` | 5557 |
| M2 Negocio | `gestor_transacciones.py` | 5555 (clientes), 5556 (RMC) |
| M2 Negocio | `rmc.py` | se conecta a 5556 y a M3:5557 |
| M1 Consumidores | `cliente_carga.py` | se conecta a M2:5555 |

## Configuración (variables de entorno)
`SRB_GT_HOST`, `SRB_PERSIST_HOST`, `SRB_MES` (por defecto 2026-11), `SRB_DB_PATH`, y los puertos.

## Ejecución en una sola máquina (prueba rápida)
Orden de arranque, cada comando en su terminal:
```
python persistencia.py --reset      # crea la BD: 50 eventos (20 con 2 ocurrencias, 30 con 1), 100 asientos c/u
python gestor_transacciones.py
python rmc.py
python cliente_carga.py --cliente-id C1 --duracion 60 --pct-consulta 50
python ver_bd.py                    # estado de la BD tras la prueba
```

## Ejecución en 3 máquinas
```
# M3 (almacenamiento)
python persistencia.py --reset

# M2 (negocio)
export SRB_PERSIST_HOST=<IP_M3>
python gestor_transacciones.py
python rmc.py                       # en otra terminal de M2

# M1 (clientes)
export SRB_GT_HOST=<IP_M2>
python cliente_carga.py --cliente-id C1 ...
```
Abrir en el firewall: M2 puerto 5555 hacia M1, y M3 puerto 5557 solo hacia M2.

## Parámetros del cliente
`--rpm` (solicitudes/min por hilo, mínimo 20), `--pct-consulta` (el resto son reservas), `--duracion` (s), `--hilos`, `--max-asientos`, `--semilla`.

## Escenarios de la Tabla 1 (150 s cada uno)
- **3 clientes:** 2 de solo consulta y 1 mixto
```
python cliente_carga.py --cliente-id C1 --pct-consulta 100 &
python cliente_carga.py --cliente-id C2 --pct-consulta 100 &
python cliente_carga.py --cliente-id C3 --pct-consulta 50 &
```
- **5 clientes:** 3 de solo consulta, 2 de reserva (`--pct-consulta 50`)
- **8 clientes:** 4 de solo consulta, 4 de reserva (`--pct-consulta 50`)

Entre escenarios, reiniciar `persistencia.py --reset` para partir del mismo estado.

## Métricas
```
python analisis.py "resultados_*.csv" --warmup 15
```
El GT también escribe `gt_metricas.csv` (TPM medido en el gestor).
Cada servicio imprime en consola cada operación y su resultado.

## Archivos
`config.py` · `persistencia.py` · `rmc.py` · `gestor_transacciones.py` · `cliente_carga.py` · `analisis.py` · `ver_bd.py`