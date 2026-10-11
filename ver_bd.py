"""Muestra el estado actual de la BD PostgreSQL (para la sustentación)."""
import psycopg2
from config import PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD

conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER,
                        password=PG_PASSWORD, connect_timeout=5)
c = conn.cursor()
c.execute("""SELECT e.id_evento, o.fecha, o.asientos_libres,
                    o.asientos_totales - o.asientos_libres
             FROM ocurrencias o JOIN eventos e USING(id_evento)
             ORDER BY CAST(SUBSTR(e.id_evento, 2) AS INT), o.fecha""")
for r in c.fetchall():
    print(f"{r[0]:5} {r[1]}  libres={r[2]:3}  ocupados={r[3]:3}")
c.execute("""SELECT r.id_reserva, r.id_cliente, o.id_evento, o.fecha, r.num_asientos, r.estado
             FROM reservas r JOIN ocurrencias o USING(id_ocurrencia) ORDER BY r.id_reserva""")
reservas = c.fetchall()
print(f"Reservas: {len(reservas)}")
for r in reservas:
    print(f"  R{r[0]} cliente={r[1]} {r[2]} {r[3]} asientos={r[4]} {r[5]}")
conn.close()