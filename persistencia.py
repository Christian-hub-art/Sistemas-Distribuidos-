"""Servicio de Persistencia: único dueño de la BD (PostgreSQL, puede estar en otra VM).

CRUD expuesto por ZeroMQ (REP):
  Create : confirmar_reserva
  Read   : consultar_eventos, disponibilidad, obtener_reserva
  Update : modificar_reserva (número de asientos o fecha)
  Delete : cancelar_reserva (borrado lógico: estado CANCELADA y libera asientos)
Cada escritura es una transacción que bloquea las filas que toca (SELECT ... FOR UPDATE):
si algo falla se hace ROLLBACK y la reserva queda exactamente como estaba.
"""
import argparse, json, time
import psycopg2
import psycopg2.extras
import zmq
from config import (PERSIST_PORT, MES_BASE, ASIENTOS_POR_EVENTO,
                    PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS eventos(
  id_evento TEXT PRIMARY KEY, nombre TEXT NOT NULL, ocurrencias_mes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ocurrencias(
  id_ocurrencia SERIAL PRIMARY KEY,
  id_evento TEXT NOT NULL REFERENCES eventos(id_evento),
  fecha TEXT NOT NULL, asientos_totales INTEGER NOT NULL,
  asientos_libres INTEGER NOT NULL CHECK(asientos_libres BETWEEN 0 AND asientos_totales),
  UNIQUE(id_evento, fecha));
CREATE TABLE IF NOT EXISTS reservas(
  id_reserva SERIAL PRIMARY KEY,
  id_tx TEXT UNIQUE, id_cliente TEXT NOT NULL,
  id_ocurrencia INTEGER NOT NULL REFERENCES ocurrencias(id_ocurrencia),
  num_asientos INTEGER NOT NULL CHECK(num_asientos > 0),
  estado TEXT NOT NULL DEFAULT 'ACTIVA' CHECK(estado IN ('ACTIVA','CANCELADA')),
  creada_en DOUBLE PRECISION NOT NULL,
  actualizada_en DOUBLE PRECISION);
"""

def conectar():
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER,
                            password=PG_PASSWORD, connect_timeout=5,
                            cursor_factory=psycopg2.extras.RealDictCursor)

def sembrar(conn, mes, reset):
    with conn, conn.cursor() as c:
        if reset:
            c.execute("DROP TABLE IF EXISTS reservas, ocurrencias, eventos")
        c.execute(ESQUEMA)
        c.execute("SELECT COUNT(*) AS n FROM eventos")
        if c.fetchone()["n"]:
            return
        for i in range(1, 51):                       # 50 eventos
            eid, n = f"E{i}", (2 if i <= 20 else 1)  # 20 con 2 ocurrencias, 30 con 1
            c.execute("INSERT INTO eventos VALUES (%s,%s,%s)", (eid, f"Evento {i}", n))
            for k in range(n):
                dia = ((i - 1) % 14) + 1 + 14 * k    # días 1..28
                c.execute(
                    "INSERT INTO ocurrencias(id_evento,fecha,asientos_totales,asientos_libres)"
                    " VALUES (%s,%s,%s,%s)",
                    (eid, f"{mes}-{dia:02d}", ASIENTOS_POR_EVENTO, ASIENTOS_POR_EVENTO))

def resumen(conn):
    with conn, conn.cursor() as c:
        c.execute("SELECT SUM(asientos_totales) AS t, SUM(asientos_libres) AS l FROM ocurrencias")
        f = c.fetchone()
        c.execute("SELECT COUNT(*) FILTER (WHERE estado='ACTIVA') AS a,"
                  " COUNT(*) FILTER (WHERE estado='CANCELADA') AS x FROM reservas")
        r = c.fetchone()
    return (f"asientos totales={f['t']} libres={f['l']} ocupados={f['t'] - f['l']} "
            f"reservas activas={r['a']} canceladas={r['x']}")

def error(codigo):
    return {"ok": False, "error": codigo}

def leer_reserva(c, id_reserva, bloquear=False):
    c.execute("""SELECT r.id_reserva, r.id_cliente, r.num_asientos, r.estado, r.id_ocurrencia,
                        o.id_evento, o.fecha
                 FROM reservas r JOIN ocurrencias o ON o.id_ocurrencia = r.id_ocurrencia
                 WHERE r.id_reserva = %s""" + (" FOR UPDATE OF r" if bloquear else ""),
              (id_reserva,))
    return c.fetchone()

# ----------------------------------------------------------------- READ
def consultar_eventos(conn, d):
    with conn, conn.cursor() as c:
        c.execute("""SELECT o.id_ocurrencia, o.id_evento, e.nombre, o.fecha,
                            o.asientos_totales, o.asientos_libres
                     FROM ocurrencias o JOIN eventos e ON e.id_evento = o.id_evento
                     WHERE o.fecha LIKE %s ORDER BY o.fecha, o.id_evento""",
                  (str(d["mes"]) + "-%",))
        return {"ok": True, "data": [dict(f) for f in c.fetchall()]}

def disponibilidad(conn, d):
    with conn, conn.cursor() as c:
        c.execute("SELECT id_ocurrencia, asientos_libres FROM ocurrencias"
                  " WHERE id_evento=%s AND fecha=%s", (d["id_evento"], d["fecha"]))
        f = c.fetchone()
    return {"ok": True, "data": dict(f)} if f else error("EVENTO_NO_EXISTE")

def obtener_reserva(conn, d):
    with conn, conn.cursor() as c:
        r = leer_reserva(c, d["id_reserva"])
    return {"ok": True, "data": dict(r)} if r else error("RESERVA_NO_EXISTE")

# --------------------------------------------------------------- CREATE
def confirmar_reserva(conn, d):
    n = d["num_asientos"]
    with conn, conn.cursor() as c:
        c.execute("SELECT id_reserva FROM reservas WHERE id_tx=%s", (d["id_tx"],))
        previa = c.fetchone()
        if previa:  # reintento idempotente
            return {"ok": True, "data": {"id_reserva": previa["id_reserva"], "duplicada": True}}
        c.execute("SELECT id_ocurrencia, asientos_libres FROM ocurrencias"
                  " WHERE id_evento=%s AND fecha=%s FOR UPDATE", (d["id_evento"], d["fecha"]))
        o = c.fetchone()
        if not o or o["asientos_libres"] < n:
            return error("SIN_DISPONIBILIDAD")
        c.execute("UPDATE ocurrencias SET asientos_libres = asientos_libres - %s"
                  " WHERE id_ocurrencia=%s", (n, o["id_ocurrencia"]))
        c.execute("INSERT INTO reservas(id_tx,id_cliente,id_ocurrencia,num_asientos,creada_en)"
                  " VALUES (%s,%s,%s,%s,%s) RETURNING id_reserva",
                  (d["id_tx"], d["id_cliente"], o["id_ocurrencia"], n, time.time()))
        return {"ok": True, "data": {"id_reserva": c.fetchone()["id_reserva"],
                                     "asientos_libres": o["asientos_libres"] - n}}

# --------------------------------------------------------------- UPDATE
def modificar_reserva(conn, d):
    """d: id_reserva, id_cliente y UNO de: num_asientos (mismo día) o fecha (mismos asientos)."""
    nuevo_n, nueva_fecha = d.get("num_asientos"), d.get("fecha")
    if (nuevo_n is None) == (nueva_fecha is None):
        return error("INDIQUE_NUM_ASIENTOS_O_FECHA")
    if nuevo_n is not None and (not isinstance(nuevo_n, int) or nuevo_n < 1):
        return error("SOLICITUD_INVALIDA")
    with conn, conn.cursor() as c:
        r = leer_reserva(c, d["id_reserva"], bloquear=True)
        if not r:
            return error("RESERVA_NO_EXISTE")
        if r["id_cliente"] != d["id_cliente"]:
            return error("NO_AUTORIZADO")
        if r["estado"] != "ACTIVA":
            return error("RESERVA_CANCELADA")

        if nuevo_n is not None:                       # cambio de número de asientos
            diferencia = nuevo_n - r["num_asientos"]
            if diferencia == 0:
                return error("SIN_CAMBIOS")
            c.execute("SELECT asientos_libres FROM ocurrencias WHERE id_ocurrencia=%s FOR UPDATE",
                      (r["id_ocurrencia"],))
            if diferencia > c.fetchone()["asientos_libres"]:
                return error("SIN_DISPONIBILIDAD")
            c.execute("UPDATE ocurrencias SET asientos_libres = asientos_libres - %s"
                      " WHERE id_ocurrencia=%s", (diferencia, r["id_ocurrencia"]))
            c.execute("UPDATE reservas SET num_asientos=%s, actualizada_en=%s WHERE id_reserva=%s",
                      (nuevo_n, time.time(), r["id_reserva"]))
        else:                                         # cambio de fecha
            if nueva_fecha == r["fecha"]:
                return error("SIN_CAMBIOS")
            c.execute("SELECT ocurrencias_mes FROM eventos WHERE id_evento=%s", (r["id_evento"],))
            if c.fetchone()["ocurrencias_mes"] < 2:
                return error("EVENTO_CON_UNA_SOLA_FECHA")
            c.execute("SELECT id_ocurrencia, asientos_libres FROM ocurrencias"
                      " WHERE id_evento=%s AND fecha=%s", (r["id_evento"], nueva_fecha))
            destino = c.fetchone()
            if not destino:
                return error("FECHA_NO_EXISTE")
            # Bloquear origen y destino siempre en el mismo orden (evita interbloqueos).
            c.execute("SELECT id_ocurrencia, asientos_libres FROM ocurrencias"
                      " WHERE id_ocurrencia IN (%s,%s) ORDER BY id_ocurrencia FOR UPDATE",
                      (r["id_ocurrencia"], destino["id_ocurrencia"]))
            libres = {f["id_ocurrencia"]: f["asientos_libres"] for f in c.fetchall()}
            if libres[destino["id_ocurrencia"]] < r["num_asientos"]:
                return error("SIN_DISPONIBILIDAD")
            c.execute("UPDATE ocurrencias SET asientos_libres = asientos_libres + %s"
                      " WHERE id_ocurrencia=%s", (r["num_asientos"], r["id_ocurrencia"]))
            c.execute("UPDATE ocurrencias SET asientos_libres = asientos_libres - %s"
                      " WHERE id_ocurrencia=%s", (r["num_asientos"], destino["id_ocurrencia"]))
            c.execute("UPDATE reservas SET id_ocurrencia=%s, actualizada_en=%s WHERE id_reserva=%s",
                      (destino["id_ocurrencia"], time.time(), r["id_reserva"]))
        return {"ok": True, "data": dict(leer_reserva(c, r["id_reserva"]))}

# --------------------------------------------------------------- DELETE
def cancelar_reserva(conn, d):
    with conn, conn.cursor() as c:
        r = leer_reserva(c, d["id_reserva"], bloquear=True)
        if not r:
            return error("RESERVA_NO_EXISTE")
        if r["id_cliente"] != d["id_cliente"]:
            return error("NO_AUTORIZADO")
        if r["estado"] != "ACTIVA":
            return error("RESERVA_CANCELADA")
        c.execute("UPDATE ocurrencias SET asientos_libres = asientos_libres + %s"
                  " WHERE id_ocurrencia=%s", (r["num_asientos"], r["id_ocurrencia"]))
        c.execute("UPDATE reservas SET estado='CANCELADA', actualizada_en=%s WHERE id_reserva=%s",
                  (time.time(), r["id_reserva"]))
        return {"ok": True, "data": {"id_reserva": r["id_reserva"],
                                     "asientos_liberados": r["num_asientos"]}}

HANDLERS = {"consultar_eventos": consultar_eventos,
            "disponibilidad": disponibilidad,
            "obtener_reserva": obtener_reserva,
            "confirmar_reserva": confirmar_reserva,
            "modificar_reserva": modificar_reserva,
            "cancelar_reserva": cancelar_reserva}
ESCRITURAS = {"confirmar_reserva", "modificar_reserva", "cancelar_reserva"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="borra y recrea la BD inicial")
    args = ap.parse_args()
    conn = conectar()
    sembrar(conn, MES_BASE, args.reset)
    print(f"[PERSISTENCIA] PostgreSQL {PG_HOST}:{PG_PORT}/{PG_DB}. "
          f"Estado inicial: {resumen(conn)}", flush=True)

    sock = zmq.Context.instance().socket(zmq.REP)
    sock.bind(f"tcp://*:{PERSIST_PORT}")
    while True:
        raw = sock.recv()
        try:
            msg = json.loads(raw)
            resp = HANDLERS[msg["op"]](conn, msg)
        except (ValueError, TypeError, KeyError) as e:
            msg, resp = {}, error(f"PETICION_INVALIDA:{e}")
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            resp = error(f"BD_NO_DISPONIBLE:{str(e).strip()}")
            try:                      # la VM de PostgreSQL se cayó o se reinició
                conn.close()
                conn = conectar()
            except psycopg2.Error:
                pass
        except Exception as e:
            resp = error(f"ERROR_BD:{e}")
        sock.send_json(resp)
        if msg.get("op") in ESCRITURAS:
            try:
                estado_bd = resumen(conn)
            except psycopg2.Error:
                estado_bd = "BD no disponible"
            print(f"[PERSISTENCIA] {msg['op']} cliente={msg.get('id_cliente')} "
                  f"reserva={msg.get('id_reserva', '-')} -> {resp.get('error', 'OK')} | {estado_bd}",
                  flush=True)

if __name__ == "__main__":
    main()