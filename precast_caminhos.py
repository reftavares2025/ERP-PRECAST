"""Onde o motor CAD guarda os arquivos enviados e as pranchas geradas."""
import os

_RAIZ = os.path.dirname(os.path.abspath(__file__))
_PASTA_HISTORICA = r"D:\SISTEMA ERP PRÉ-FABRICADO\uploads_dwg"


def pasta_de_uploads():
    """PRECAST_UPLOADS_DIR, se definida; senão a pasta histórica desta máquina, se ainda existir;
    senão `uploads_dwg` dentro do projeto (instalação nova de cliente)."""
    pasta = os.environ.get("PRECAST_UPLOADS_DIR") or (_PASTA_HISTORICA if os.path.isdir(_PASTA_HISTORICA) else os.path.join(_RAIZ, "uploads_dwg"))
    os.makedirs(pasta, exist_ok=True)
    return pasta
