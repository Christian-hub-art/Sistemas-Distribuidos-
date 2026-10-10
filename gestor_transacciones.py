"""Gestor de Transacciones: ROUTER (clientes) <-> DEALER (workers RMC)."""
import collections, csv, json, time, uuid
import zmq
from config import GT_FRONT_PORT, GT_BACK_PORT

OPS_SINCRONAS = {"CONSULTA", "RESERVA"}   # Entrega 1: sin modificación ni cancelación

def responder(front, ident, estado, detalle, req_id=None):
    cuerpo = json.dumps({"req_id": req_id, "estado": estado, "detalle": detalle}).encode()
    front.send_multipart([ident, b"", cuerpo])

def main():
    ctx = zmq.Context.instance()
    front = ctx.socket(zmq.ROUTER); front.bind(f"tcp://*:{GT_FRONT_PORT}")
    back = ctx.socket(zmq.DEALER);  back.bind(f"tcp://*:{GT_BACK_PORT}")
    poller = zmq.Poller()
    poller.register(front, zmq.POLLIN); poller.register(back, zmq.POLLIN)

    pendientes = {}                                   # req_id -> (ident, t0, op)
    ventana = {"CONSULTA": collections.deque(), "RESERVA": collections.deque()}
    archivo = open("gt_metricas.csv", "w", newline="")
    w = csv.writer(archivo); w.writerow(["t_epoch", "op", "latencia_ms", "estado"])
    ultimo_log = time.time()
    print(f"[GT] frontend :{GT_FRONT_PORT} | backend :{GT_BACK_PORT}", flush=True)

    while True:
        eventos = dict(poller.poll(1000))

        if front in eventos:
            ident, _, raw = front.recv_multipart()
            try:
                msg = json.loads(raw)
                op = msg["op"]
            except (ValueError, KeyError, TypeError):
                responder(front, ident, "ERROR", "SOLICITUD_MALFORMADA"); continue
            if op not in OPS_SINCRONAS:
                responder(front, ident, "ERROR", "OPERACION_NO_SOPORTADA"); continue
            req_id = uuid.uuid4().hex
            msg["req_id"] = req_id
            try:
                back.send_multipart([b"", json.dumps(msg).encode()], flags=zmq.NOBLOCK)
                pendientes[req_id] = (ident, time.perf_counter(), op)
            except zmq.Again:                         # no hay RMC disponible
                responder(front, ident, "ERROR", "SERVICIO_NO_DISPONIBLE")

        if back in eventos:
            _, raw = back.recv_multipart()
            resp = json.loads(raw)
            reg = pendientes.pop(resp.get("req_id"), None)
            if reg:
                ident, t0, op = reg
                lat = (time.perf_counter() - t0) * 1000
                front.send_multipart([ident, b"", raw])
                ahora = time.time()
                w.writerow([f"{ahora:.3f}", op, f"{lat:.3f}", resp.get("estado")])
                ventana[op].append(ahora)

        ahora = time.time()
        if ahora - ultimo_log >= 10:
            for op, dq in ventana.items():
                while dq and dq[0] < ahora - 60:
                    dq.popleft()
            print(f"[GT] TPM (últimos 60 s): consultas={len(ventana['CONSULTA'])} "
                  f"reservas={len(ventana['RESERVA'])} | pendientes={len(pendientes)}", flush=True)
            archivo.flush(); ultimo_log = ahora

if __name__ == "__main__":
    main()