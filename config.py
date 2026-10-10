import os

GT_HOST = os.getenv("SRB_GT_HOST", "127.0.0.1")
GT_FRONT_PORT = int(os.getenv("SRB_GT_FRONT_PORT", "5555"))   # clientes -> GT
GT_BACK_PORT = int(os.getenv("SRB_GT_BACK_PORT", "5556"))     # GT -> RMC (workers)
PERSIST_HOST = os.getenv("SRB_PERSIST_HOST", "127.0.0.1")
PERSIST_PORT = int(os.getenv("SRB_PERSIST_PORT", "5557"))
DB_PATH = os.getenv("SRB_DB_PATH", "srb.db")
MES_BASE = os.getenv("SRB_MES", "2026-11")
ASIENTOS_POR_EVENTO = 100