"""Servicio RMC: atiende consultas y reservas síncronas enviadas por el GT."""
import os
import zmq
from config import (GT_HOST, GT_BACK_PORT, PERSIST_HOST, PERSIST_PORT,
                    MES_BASE, ASIENTOS_POR_EVENTO)

ctx = zmq.Context.instance()

def nuevo_req_bd():
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.RCVTIMEO, 5000)
    s.setsockopt(zmq.SNDTIMEO, 5000)
    s.setsockopt(zmq.LINGER, 0)
    s.connect(f"tcp://{PERSIST_HOST}:{PERSIST_PORT}")
    return s

bd = nuevo_req_bd()

def llamar_bd(op, **datos):
    global bd
    try:
        bd.send_json({"op": op, **datos})
        return bd.recv_json()
    except zmq.Again:        # un REQ tras timeout queda inutilizable: se recrea
        bd.close()
        bd = nuevo_req_bd()
        return {"ok": False, "error": "BD_NO_RESPONDE"}

def procesar(msg):
    op, p = msg.get("op"), msg.get("payload", {})
    if op == "CONSULTA":
        r = llamar_bd("consultar_eventos", mes=p.get("mes", MES_BASE))
        return ("EXITO", r["data"]) if r["ok"] else ("ERROR", r["error"])

    if op == "RESERVA":
        n = p.get("num_asientos")
        if not (p.get("id_tx") and p.get("id_cliente") and p.get("id_evento")
                and p.get("fecha") and isinstance(n, int) and 1 <= n <= ASIENTOS_POR_EVENTO):
            return "RECHAZO", "SOLICITUD_INVALIDA"
        disp = llamar_bd("disponibilidad", id_evento=p["id_evento"], fecha=p["fecha"])
        if not disp["ok"]:
            return "RECHAZO", disp["error"]
        if disp["data"]["asientos_libres"] < n:
            return "RECHAZO", "SIN_DISPONIBILIDAD"
        r = llamar_bd("confirmar_reserva", id_tx=p["id_tx"], id_cliente=p["id_cliente"],
                      id_evento=p["id_evento"], fecha=p["fecha"], num_asientos=n)
        if r["ok"]:
            return "EXITO", r["data"]
        return ("RECHAZO" if r["error"] == "SIN_DISPONIBILIDAD" else "ERROR"), r["error"]

    return "ERROR", "OPERACION_NO_SOPORTADA"

def main():
    sock = ctx.socket(zmq.REP)
    sock.connect(f"tcp://{GT_HOST}:{GT_BACK_PORT}")
    pid = os.getpid()
    print(f"[RMC {pid}] conectado al GT en {GT_HOST}:{GT_BACK_PORT}", flush=True)
    while True:
        msg = sock.recv_json()
        try:
            estado, detalle = procesar(msg)
        except Exception as e:
            estado, detalle = "ERROR", str(e)
        sock.send_json({"req_id": msg.get("req_id"), "op": msg.get("op"),
                        "estado": estado, "detalle": detalle})
        print(f"[RMC {pid}] {msg.get('op')} -> {estado}", flush=True)

if __name__ == "__main__":
    main()