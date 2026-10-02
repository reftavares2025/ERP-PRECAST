"""Onde o motor CAD guarda os arquivos enviados e as pranchas geradas."""
import os
import re

_RAIZ = os.path.dirname(os.path.abspath(__file__))
_PASTA_HISTORICA = r"D:\SISTEMA ERP PRÉ-FABRICADO\uploads_dwg"


def pasta_de_uploads():
    """PRECAST_UPLOADS_DIR, se definida; senão a pasta histórica desta máquina, se ainda existir;
    senão `uploads_dwg` dentro do projeto (instalação nova de cliente)."""
    pasta = os.environ.get("PRECAST_UPLOADS_DIR") or (_PASTA_HISTORICA if os.path.isdir(_PASTA_HISTORICA) else os.path.join(_RAIZ, "uploads_dwg"))
    os.makedirs(pasta, exist_ok=True)
    return pasta


_RE_REVISAO = re.compile(r"(?:^|[\s_.\-])(REV[.\-\s]?\d{1,2}[a-z]?|R\d{1,2}[a-z]?)(?=$|[\s_.\-])", re.IGNORECASE)


def revisao_do_arquivo(nome_arquivo):
    """'EST - OBRA - R0e - 10-08-2026.dwg' -> 'R0e'; sem marca de revisão, None."""
    base = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", str(nome_arquivo or ""))
    achou = _RE_REVISAO.search(base)
    return achou.group(1).replace(" ", "") if achou else None
