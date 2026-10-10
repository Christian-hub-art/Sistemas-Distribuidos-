"""Calcula promedio, desviación estándar y TPM a partir de los CSV de los clientes."""
import argparse, csv, glob, statistics

ap = argparse.ArgumentParser()
ap.add_argument("patron", nargs="?", default="resultados_*.csv")
ap.add_argument("--warmup", type=float, default=15, help="segundos iniciales a descartar")
args = ap.parse_args()

filas = []
for archivo in glob.glob(args.patron):
    with open(archivo) as f:
        filas += [(float(r["t_envio"]), r["op"], float(r["latencia_ms"]), r["estado"])
                  for r in csv.DictReader(f)]
if not filas:
    raise SystemExit("Sin datos")
t0 = min(f[0] for f in filas)
filas = [f for f in filas if f[0] - t0 >= args.warmup]
minutos = (max(f[0] for f in filas) - min(f[0] for f in filas)) / 60 or 1e-9

print(f"{'op':9}{'n':>7}{'prom ms':>10}{'desv ms':>10}{'TPM':>9}{'timeouts/errores':>18}")
for op in ("CONSULTA", "RESERVA"):
    ok = [f[2] for f in filas if f[1] == op and f[3] in ("EXITO", "RECHAZO")]
    mal = sum(1 for f in filas if f[1] == op and f[3] not in ("EXITO", "RECHAZO"))
    if ok:
        sd = statistics.stdev(ok) if len(ok) > 1 else 0.0
        print(f"{op:9}{len(ok):>7}{statistics.mean(ok):>10.2f}{sd:>10.2f}{len(ok)/minutos:>9.1f}{mal:>18}")