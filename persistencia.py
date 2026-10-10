"""Servicio de Persistencia: único dueño de la BD. REP secuencial => escrituras serializadas."""
import argparse, os, sqlite3, time
import zmq
from config import DB_PATH, PERSIST_PORT, MES_BASE, ASIENTOS_POR_EVENTO

ESQUEMA = """
CREATE TABLE IF NOT EXISTS eventos(
  id_evento TEXT PRIMARY KEY, nombre TEXT NOT NULL, ocurrencias_mes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ocurrencias(
  id_ocurrencia INTEGER PRIMARY KEY AUTOINCREMENT,
  id_evento TEXT NOT NULL REFERENCES eventos(id_evento),
  fecha TEXT NOT NULL, asientos_totales INTEGER NOT NULL,
  asientos_libres INTEGER NOT NULL CHECK(asientos_libres >= 0),
  UNIQUE(id_evento, fecha));
CREATE TABLE IF NOT EXISTS reservas(
  id_reserva INTEGER PRIMARY KEY AUTOINCREMENT,
  id_tx TEXT UNIQUE, id_cliente TEXT NOT NULL,
  id_ocurrencia INTEGER NOT NULL REFERENCES ocurrencias(id_ocurrencia),
  num_asientos INTEGER NOT NULL CHECK(num_asientos > 0),
  estado TEXT NOT NULL DEFAULT 'ACTIVA', creada_en REAL NOT NULL);
"""

def sembrar(conn, mes):
    conn.executescript(ESQUEMA)
    if conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]:
        return
    for i in range(1, 51):                       # 50 eventos
        eid, n = f"E{i}", (2 if i <= 20 else 1)  # 20 con 2 ocurrencias, 30 con 1
        conn.execute("INSERT INTO eventos VALUES (?,?,?)", (eid, f"Evento {i}", n))
        for k in range(n):
            dia = ((i - 1) % 14) + 1 + 14 * k    # días 1..28
            conn.execute(
                "INSERT INTO ocurrencias(id_evento,fecha,asientos_totales,asientos_libres)"
                " VALUES (?,?,?,?)",
                (eid, f"{mes}-{dia:02d}", ASIENTOS_POR_EVENTO, ASIENTOS_POR_EVENTO))

def resumen(conn):
    t, l = conn.execute(
        "SELECT SUM(asientos_totales), SUM(asientos_libres) FROM ocurrencias").fetchone()
    r = conn.execute("SELECT COUNT(*) FROM reservas").fetchone()[0]
    return f"asientos totales={t} libres={l} ocupados={t-l} reservas={r}"

def consultar_eventos(conn, d):
    filas = conn.execute(
        """SELECT o.id_ocurrencia, o.id_evento, e.nombre, o.fecha,
                  o.asientos_totales, o.asientos_libres
           FROM ocurrencias o JOIN eventos e ON e.id_evento = o.id_evento
           WHERE o.fecha LIKE ? ORDER BY o.fecha, o.id_evento""",
        (str(d["mes"]) + "-%",)).fetchall()
    return {"ok": True, "data": [dict(f) for f in filas]}

def disponibilidad(conn, d):
    f = conn.execute(
        "SELECT id_ocurrencia, asientos_libres FROM ocurrencias WHERE id_evento=? AND fecha=?",
        (d["id_evento"], d["fecha"])).fetchone()
    if not f:
        return {"ok": False, "error": "EVENTO_NO_EXISTE"}
    return {"ok": True, "data": dict(f)}

def confirmar_reserva(conn, d):
    n = d["num_asientos"]
    conn.execute("BEGIN IMMEDIATE")
    try:
        previa = conn.execute("SELECT id_reserva FROM reservas WHERE id_tx=?",
                              (d["id_tx"],)).fetchone()
        if previa:  # reintento idempotente
            conn.execute("COMMIT")
            return {"ok": True, "data": {"id_reserva": previa["id_reserva"], "duplicada": True}}
        o = conn.execute(
            "SELECT id_ocurrencia, asientos_libres FROM ocurrencias WHERE id_evento=? AND fecha=?",
            (d["id_evento"], d["fecha"])).fetchone()
        if not o or o["asientos_libres"] < n:
            conn.execute("ROLLBACK")
            return {"ok": False, "error": "SIN_DISPONIBILIDAD"}
        conn.execute("UPDATE ocurrencias SET asientos_libres = asientos_libres - ? "
                     "WHERE id_ocurrencia=?", (n, o["id_ocurrencia"]))
        cur = conn.execute(
            "INSERT INTO reservas(id_tx,id_cliente,id_ocurrencia,num_asientos,creada_en)"
            " VALUES (?,?,?,?,?)",
            (d["id_tx"], d["id_cliente"], o["id_ocurrencia"], n, time.time()))
        conn.execute("COMMIT")
        return {"ok": True, "data": {"id_reserva": cur.lastrowid,
                                     "asientos_libres": o["asientos_libres"] - n}}
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

HANDLERS = {"consultar_eventos": consultar_eventos,
            "disponibilidad": disponibilidad,
            "confirmar_reserva": confirmar_reserva}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="borra y recrea la BD inicial")
    args = ap.parse_args()
    if args.reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # control manual de transacciones
    sembrar(conn, MES_BASE)
    print(f"[PERSISTENCIA] BD lista ({DB_PATH}). Estado inicial: {resumen(conn)}", flush=True)

    sock = zmq.Context.instance().socket(zmq.REP)
    sock.bind(f"tcp://*:{PERSIST_PORT}")
    while True:
        msg = sock.recv_json()
        try:
            resp = HANDLERS[msg["op"]](conn, msg)
        except KeyError as e:
            resp = {"ok": False, "error": f"PETICION_INVALIDA:{e}"}
        except Exception as e:
            resp = {"ok": False, "error": f"ERROR_BD:{e}"}
        sock.send_json(resp)
        if msg.get("op") == "confirmar_reserva":
            print(f"[PERSISTENCIA] reserva cliente={msg.get('id_cliente')} "
                  f"{msg.get('id_evento')} {msg.get('fecha')} n={msg.get('num_asientos')} "
                  f"-> {resp.get('error', 'OK')} | {resumen(conn)}", flush=True)

if __name__ == "__main__":
    main()