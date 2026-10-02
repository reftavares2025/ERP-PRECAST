"""Procura texto em inglês no que a pessoa vê nas nossas telas (HTML) e nas mensagens do servidor (Python).
Uso: python tests/varredura_ingles.py
Não precisa do servidor. Termina com código 1 se achar algo."""
import ast
import glob
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INGLES = set("""the and or of to for with your you please not is are was were has have had from this that these those will can cannot could would should
invalid error errors failed failure success successfully loading save saved cancel delete deleted edit search select enter click description name status date
total new add remove update updated create created open close back next previous submit send sent upload download view show hide settings setting
required missing found login logout password user users email address phone company customer supplier item items quantity price amount invoice order
payment paid unpaid overdue due balance report reports list home help about yes no ok done pending approved rejected draft cancelled completed
warning info information message messages title type value values default empty none all any more less other optional filter filters sort
""".split())
PORTUGUES = set("""o a os as um uma de do da dos das em no na nos nas por para com sem que não sim e ou se ao à às pelo pela como mais menos já ainda só também
peça peças obra obras cliente clientes fase etapa data nome valor erro tente selecione informe escolha salvar cancelar excluir editar abrir fechar
""".split())

# termos técnicos e marcas que ficam como estão
PERMITIDOS = re.compile(r"^(ERP|Precast|CSV|PDF|PNG|ZPL|QR|CAD|DWG|DXF|IFC|API|ID|NF-e|NFS-e|CT-e|MDF-e|SPED|CNPJ|CPF|LGPD|ASO|EPI|CAT|NR-\d+|CA|OK|PIX|Pix|WhatsApp|Wi-?Fi|HTTPS?|URL|JSON|ZIP|IA|Kg|kg|MPa|m³|CP-[IV]+.*|CA-\d+.*)$")
PALAVRA = re.compile(r"[A-Za-zÀ-ÿ']+")


def suspeito(texto):
    t = re.sub(r"\s+", " ", re.sub(r"\$\{[^}]*\}", " ", texto)).strip()    # o que está dentro de ${...} é código, não texto
    if len(t) < 6 or PERMITIDOS.match(t) or "://" in t or t.startswith(("/", "#", ".", "{", "<", "$")) or re.fullmatch(r"[\w./:-]+", t):
        return False
    palavras = [p.lower() for p in PALAVRA.findall(t)]
    if len(palavras) < 2:
        return False
    en = sum(1 for p in palavras if p in INGLES)
    pt = sum(1 for p in palavras if p in PORTUGUES or re.search(r"[ãõçáéíóúâêô]", p))
    return en >= 2 and en > pt


def textos_html(caminho):
    s = open(caminho, encoding="utf-8").read()
    s = re.sub(r"<script\b.*?</script>", lambda m: "\n".join(f"@@JS {x}" for x in re.findall(r"""(?:'([^'\n]{6,})'|"([^"\n]{6,})"|`([^`\n]{6,})`)""", m.group(0)) if False) or m.group(0), s, flags=re.S)
    saida = []
    # texto entre tags e atributos visíveis
    for m in re.finditer(r">([^<>{}$]{4,})<", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", s, flags=re.S)):
        saida.append(m.group(1))
    for m in re.finditer(r"""(?:placeholder|title|alt|aria-label|data-tooltip)=["']([^"']{4,})["']""", s):
        saida.append(m.group(1))
    # textos dentro do JavaScript: alert/confirm/prompt, innerText/textContent e templates
    for m in re.finditer(r"""(?:alert|confirm|prompt|msgRosto|rastroMsg|relMsg|supMsg|segMsg|atMsg|corteMsg|patioMsg|cargasMsg)\(\s*[`'"]([^`'"\n]{6,})[`'"]""", s):
        saida.append(m.group(1))
    for m in re.finditer(r"""(?:innerText|textContent)\s*=\s*[`'"]([^`'"\n]{6,})[`'"]""", s):
        saida.append(m.group(1))
    return saida


def textos_python(caminho):
    arvore = ast.parse(open(caminho, encoding="utf-8").read())
    saida = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Dict):
            for k, v in zip(no.keys, no.values):
                if isinstance(k, ast.Constant) and k.value in ("error", "message", "aviso", "motivo", "detalhe", "mensagem", "explicacao") and isinstance(v, (ast.Constant, ast.JoinedStr)):
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        saida.append(v.value)
                    elif isinstance(v, ast.JoinedStr):
                        saida.append("".join(p.value for p in v.values if isinstance(p, ast.Constant) and isinstance(p.value, str)))
        if isinstance(no, ast.Call) and getattr(no.func, "attr", "") in ("throw", "msgprint") and no.args:
            a = no.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                saida.append(a.value)
            elif isinstance(a, ast.JoinedStr):
                saida.append("".join(p.value for p in a.values if isinstance(p, ast.Constant) and isinstance(p.value, str)))
    return saida


def main():
    achados = []
    for f in sorted(glob.glob(os.path.join(RAIZ, "*.html"))):
        for t in textos_html(f):
            if suspeito(t):
                achados.append((os.path.basename(f), t.strip()[:140]))
    for f in sorted(glob.glob(os.path.join(RAIZ, "precast_*.py"))) + [os.path.join(RAIZ, "provision_finalize.py"), os.path.join(RAIZ, "provision_schema.py")]:
        if os.path.exists(f):
            for t in textos_python(f):
                if suspeito(t):
                    achados.append((os.path.basename(f), t.strip()[:140]))
    for arq, t in achados:
        print(f"{arq}: {t}")
    print(f"\n{len(achados)} texto(s) suspeito(s) de estar em inglês.")
    sys.exit(1 if achados else 0)


if __name__ == "__main__":
    main()
