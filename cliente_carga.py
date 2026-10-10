"""Generador de carga parametrizable. Cada hilo simula un cliente con socket REQ propio."""
import argparse, csv, random, threading, time, uuid
import zmq
from config import GT_HOST, GT_FRONT_PORT, MES_BASE

class Cliente:
    def __init__(self, cid, timeout_ms):
        self.cid, self.timeout_ms = cid, timeout_ms
        self.ctx = zmq.Context.instance()
        self.conectar()

    def conectar(self):
        self.sock = self.ctx.socket(zmq.REQ)
        self.sock.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect(f"tcp://{GT_HOST}:{GT_FRONT_PORT}")

    def pedir(self, op, payload):
        t0 = time.perf_counter()
        try:
            self.sock.send_json({"op": op, "payload": payload})
            resp = self.sock.recv_json()
        except zmq.Again:
            self.sock.close(); self.conectar()
            resp = {"estado": "TIMEOUT", "detalle": None}
        return resp["estado"], (time.perf_counter() - t0) * 1000, resp

def ejecutar(args, cid, filas):
    rnd = random.Random(f"{args.semilla}-{cid}")
    cli = Cliente(cid, args.timeout_ms)
    _, _, r = cli.pedir("CONSULTA", {"mes": args.mes})       # catálogo inicial (no se mide)
    catalogo = r["detalle"] if isinstance(r.get("detalle"), list) else []
    intervalo = 60.0 / args.rpm
    fin = time.time() + args.duracion
    siguiente = time.time()
    while time.time() < fin:
        espera = siguiente - time.time()
        if espera > 0:
            time.sleep(espera)
        siguiente += intervalo
        if rnd.random() * 100 < args.pct_consulta or not catalogo:
            op, payload = "CONSULTA", {"mes": args.mes}
        else:
            disponibles = [o for o in catalogo if o["asientos_libres"] > 0] or catalogo
            o = rnd.choice(disponibles)
            op, payload = "RESERVA", {
                "id_tx": str(uuid.uuid4()), "id_cliente": cid,
                "id_evento": o["id_evento"], "fecha": o["fecha"],
                "num_asientos": rnd.randint(1, args.max_asientos)}
        t_envio = time.time()
        estado, lat, resp = cli.pedir(op, payload)
        if op == "CONSULTA" and estado == "EXITO":
            catalogo = resp["detalle"]
        filas.append((cid, f"{t_envio:.3f}", op, f"{lat:.3f}", estado))

def main():
    ap = argparse.ArgumentParser(description="Cliente de carga SRB")
    ap.add_argument("--cliente-id", required=True)
    ap.add_argument("--hilos", type=int, default=1)
    ap.add_argument("--rpm", type=float, default=30, help="solicitudes/min por hilo (>=20)")
    ap.add_argument("--duracion", type=int, default=150, help="segundos")
    ap.add_argument("--pct-consulta", type=float, default=100, help="%% de consultas; el resto son reservas")
    ap.add_argument("--max-asientos", type=int, default=4)
    ap.add_argument("--mes", default=MES_BASE)
    ap.add_argument("--semilla", default="42")
    ap.add_argument("--timeout-ms", type=int, default=5000)
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()
    if args.rpm < 20:
        print("AVISO: el enunciado exige al menos 20 solicitudes/min por cliente")

    resultados, hilos = [], []
    for i in range(args.hilos):
        cid = args.cliente_id if args.hilos == 1 else f"{args.cliente_id}-{i}"
        filas = []; resultados.append(filas)
        t = threading.Thread(target=ejecutar, args=(args, cid, filas)); t.start(); hilos.append(t)
    for t in hilos:
        t.join()

    salida = args.salida or f"resultados_{args.cliente_id}.csv"
    with open(salida, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["cliente", "t_envio", "op", "latencia_ms", "estado"])
        for filas in resultados:
            w.writerows(filas)
    print(f"[{args.cliente_id}] {sum(len(f) for f in resultados)} solicitudes -> {salida}")

if __name__ == "__main__":
    main()