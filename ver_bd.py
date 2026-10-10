"""Muestra el estado actual de la BD (para la sustentación)."""
import sqlite3
from config import DB_PATH

conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
for r in conn.execute("""SELECT e.id_evento, o.fecha, o.asientos_libres,
                                o.asientos_totales - o.asientos_libres
                         FROM ocurrencias o JOIN eventos e USING(id_evento)
                         ORDER BY CAST(SUBSTR(e.id_evento, 2) AS INT), o.fecha"""):
    print(f"{r[0]:5} {r[1]}  libres={r[2]:3}  ocupados={r[3]:3}")
print("Reservas:", conn.execute("SELECT COUNT(*) FROM reservas").fetchone()[0])