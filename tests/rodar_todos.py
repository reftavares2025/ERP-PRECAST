"""Roda os testes de ponta a ponta um de cada vez e escreve o resultado num arquivo.
Antes de cada teste espera haver memória livre (cada navegador de teste usa cerca de 400 MB).

Uso: python tests/rodar_todos.py [arquivo_de_saida] [nome_do_teste ...]
Sem nomes, roda todos. O código de saída é 0 só se todos passarem."""
import ctypes
import os
import re
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
MEMORIA_MINIMA_MB = 900
TEMPO_MAXIMO_S = 1500

ORDEM = ["e2e_sistema", "e2e_ui", "e2e_cotacoes", "e2e_diario", "e2e_csrf", "e2e_fiscal_padrao", "e2e_portal_config", "e2e_dashboard",
         "e2e_rosto", "e2e_rosto_ui", "e2e_impressao_layout", "e2e_lote_voltar", "e2e_obras_mesmo_codigo",
         "e2e_rastreabilidade", "e2e_revisoes", "e2e_corte", "e2e_patio", "e2e_montagem", "e2e_compras", "e2e_sst", "e2e_portal_rg",
         "e2e_rastreabilidade_ui", "e2e_revisoes_ui", "e2e_corte_ui", "e2e_patio_ui", "e2e_montagem_ui", "e2e_compras_ui", "e2e_sst_ui", "e2e_relatorios",
         "e2e_pranchas"]


class _Memoria(ctypes.Structure):
    _fields_ = [("tamanho", ctypes.c_ulong), ("carga", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("livre", ctypes.c_ulonglong),
                ("pag_total", ctypes.c_ulonglong), ("pag_livre", ctypes.c_ulonglong), ("virt_total", ctypes.c_ulonglong), ("virt_livre", ctypes.c_ulonglong),
                ("ext", ctypes.c_ulonglong)]


def memoria_livre_mb():
    m = _Memoria()
    m.tamanho = ctypes.sizeof(_Memoria)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return int(m.livre / 1024 / 1024)


def esperar_memoria():
    for _ in range(60):                       # até 10 minutos
        if memoria_livre_mb() >= MEMORIA_MINIMA_MB:
            return True
        time.sleep(10)
    return False


def rodar(nome):
    inicio = time.time()
    try:
        r = subprocess.run([sys.executable, os.path.join(AQUI, nome + ".py")], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=TEMPO_MAXIMO_S, creationflags=0x08000000)
        saida, codigo = (r.stdout or "") + (r.stderr or ""), r.returncode
    except subprocess.TimeoutExpired as e:
        saida, codigo = f"TEMPO ESGOTADO ({TEMPO_MAXIMO_S} s)\n" + ((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")), 124
    linhas = [l for l in saida.splitlines() if "Warning" not in l and "warnings.warn" not in l]
    falhas = [l.strip() for l in linhas if l.strip().startswith("FALHA")]
    resumo = next((l.strip() for l in reversed(linhas) if re.search(r"tudo ok|verificações ok|FALHOU", l)), "")
    passou = codigo == 0 and not falhas
    return passou, round(time.time() - inicio), falhas, resumo, linhas[-12:] if not passou else []


def main():
    destino = sys.argv[1] if len(sys.argv) > 1 else os.path.join(AQUI, "resultado_testes.txt")
    nomes = sys.argv[2:] or ORDEM
    reprovados = []
    with open(destino, "w", encoding="utf-8") as f:
        for nome in nomes:
            if not esperar_memoria():
                f.write(f"{nome}: NÃO RODOU (menos de {MEMORIA_MINIMA_MB} MB livres por 10 minutos)\n"); f.flush(); reprovados.append(nome); continue
            passou, seg, falhas, resumo, cauda = rodar(nome)
            f.write(f"{'OK    ' if passou else 'FALHOU'} {nome} ({seg} s) {resumo}\n")
            for l in falhas[:12]:
                f.write(f"        {l[:240]}\n")
            if not passou and not falhas:
                for l in cauda:
                    f.write(f"        {l[:240]}\n")
            f.flush()
            if not passou:
                reprovados.append(nome)
        f.write(f"\n{len(nomes) - len(reprovados)} de {len(nomes)} passaram" + (f"; falharam: {', '.join(reprovados)}" if reprovados else "") + "\n")
    sys.exit(1 if reprovados else 0)


if __name__ == "__main__":
    main()
