import os

GT_HOST = os.getenv("SRB_GT_HOST", "127.0.0.1")
GT_FRONT_PORT = int(os.getenv("SRB_GT_FRONT_PORT", "5555"))   # clientes -> GT
GT_BACK_PORT = int(os.getenv("SRB_GT_BACK_PORT", "5556"))     # GT -> RMC (workers)
PERSIST_HOST = os.getenv("SRB_PERSIST_HOST", "127.0.0.1")
PERSIST_PORT = int(os.getenv("SRB_PERSIST_PORT", "5557"))
MES_BASE = os.getenv("SRB_MES", "2026-11")
ASIENTOS_POR_EVENTO = 100

# PostgreSQL (puede estar en otra máquina virtual)
PG_HOST = os.getenv("SRB_PG_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("SRB_PG_PORT", "5432"))
PG_DB = os.getenv("SRB_PG_DB", "srb")
PG_USER = os.getenv("SRB_PG_USER", "srb")
PG_PASSWORD = os.getenv("SRB_PG_PASSWORD", "srb")