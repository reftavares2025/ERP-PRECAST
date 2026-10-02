"""Entrada do operador pelo rosto: prova de vida, cadastro no primeiro acesso, vínculo com o setor, bloqueio de outro
setor, setores extras pelo responsável e restrição das fases que o operador pode avançar."""
import copy, json, os, random, sys, time
import requests

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA = "ROSTO-TESTE"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


adm = requests.Session()
adm.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def chamar(sessao, metodo, **corpo):
    r = sessao.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo)
    try:
        return r.json().get("message", {})
    except ValueError:
        return {"success": False, "error": r.text[:120]}


rng = random.Random(7)
rosto = lambda: [rng.gauss(0, 0.1) for _ in range(128)]
parecido = lambda d: [x + rng.gauss(0, 0.01) for x in d]
A, B, C = rosto(), rosto(), rosto()

# medidas de um rosto fazendo cada gesto (o que o celular mediria)
NEUTRO = {"yaw": 0.01, "boca": 0.04, "largura_boca": 0.38}
GESTOS = {"virar": {"yaw": 0.30, "boca": 0.04, "largura_boca": 0.36}, "virar_oposto": {"yaw": -0.30, "boca": 0.04, "largura_boca": 0.36},
          "sorrir": {"yaw": 0.0, "boca": 0.10, "largura_boca": 0.46}, "abrir_boca": {"yaw": 0.0, "boca": 0.32, "largura_boca": 0.38}, "neutro": NEUTRO}


def desafio(sessao, descritor, espera=3.3, mudar=None):
    """Pede um desafio ao servidor e cumpre cada passo como uma pessoa de verdade faria."""
    d = chamar(sessao, "rosto_desafio")
    quadros = []
    for i, acao in enumerate(d["acoes"]):
        q = {"acao": acao, "metricas": dict(GESTOS[acao]), "t": 1000 * (i + 1)}
        if acao in ("neutro", "sorrir", "abrir_boca"):
            q["descritor"] = descritor if acao == "neutro" else parecido(descritor)
        quadros.append(q)
    if mudar:
        mudar(quadros)
    time.sleep(espera)
    return {"token": d["token"], "quadros": quadros}


def entrar(sessao, descritor, nome=None, setor=None, consentimento=True, **kw):
    return chamar(sessao, "rosto_entrar", descritor=json.dumps(descritor), nome=nome, setor=setor, consentimento=1 if consentimento else 0, desafio=json.dumps(desafio(sessao, descritor, **kw)))


chamar(adm, "gerir_rosto", acao="zerar_tentativas")
chamar(adm, "gerir_rosto", acao="prova_de_vida", aberto=True)
chamar(adm, "gerir_rosto", acao="cadastro_aberto", aberto=True)
for o in chamar(adm, "listar_rostos").get("operadores", []):
    if o["nome"].startswith("Teste Rosto"):
        chamar(adm, "gerir_rosto", usuario=o["usuario"], acao="remover")
chamar(adm, "delete_obra", codigo_obra=OBRA)
chamar(adm, "integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Rosto", "cliente": "Cliente"}),
       pieces_data=json.dumps([{"cod": f"RT{i}", "tag": f"RT {i}", "produto": "Pilar", "secao": "30x30", "comp": 3.0, "vol": 0.27, "peso": 675} for i in range(1, 5)]))

print("[Tela de entrada]")
visitante = requests.Session()
cfg = chamar(visitante, "rosto_config")
ok("setores de produção listados para o visitante", len(cfg.get("setores", [])) == 8 and cfg.get("cadastro_aberto") is True, str(cfg.get("setores"))[:60])
ok("sem rosto não há acesso: a API do sistema recusa o visitante", visitante.post(f"{URL}/api/method/frappe.precast_api.get_pieces", json={}).status_code in (401, 403))
d1 = chamar(visitante, "rosto_desafio")
ok("o servidor sorteia o desafio: de frente, par de giros e uma expressão", d1["acoes"][0] == "neutro" and sorted(d1["acoes"][1:]) == sorted(["virar", "virar_oposto", next(a for a in d1["acoes"] if a in ("sorrir", "abrir_boca"))]) and d1["acoes"].index("virar") < d1["acoes"].index("virar_oposto") and len(d1["acoes"]) == 4, str(d1["acoes"]))

print("[Prova de vida]")
r = chamar(requests.Session(), "rosto_entrar", descritor=json.dumps(A), nome="Teste Rosto Ana", setor="Armação")
ok("sem o desafio não entra", not r.get("success") and r.get("prova_de_vida") is False, r.get("error", "")[:70])
parada = lambda quadros: [q.update(metricas=dict(NEUTRO)) for q in quadros]   # a foto parada responde igual a tudo
r = entrar(requests.Session(), A, "Teste Rosto Ana", "Armação", mudar=parada)
ok("uma foto parada (sem girar a cabeça nem sorrir) é recusada", not r.get("success") and r.get("prova_de_vida") is False, r.get("error", "")[:80])
r = entrar(requests.Session(), A, "Teste Rosto Ana", "Armação", espera=0)
ok("responder rápido demais (sem pessoa) é recusado", not r.get("success") and "rápida" in r.get("error", ""), r.get("error", "")[:80])
s1 = requests.Session(); dd = desafio(s1, A)
chamar(s1, "rosto_entrar", descritor=json.dumps(A), nome="Teste Rosto Ana", setor="Armação", desafio=json.dumps(dd))
r = chamar(requests.Session(), "rosto_entrar", descritor=json.dumps(A), nome="Teste Rosto Ana", setor="Armação", desafio=json.dumps(dd))
ok("o mesmo desafio não vale duas vezes", not r.get("success") and "usada" in r.get("error", "") or "expirou" in r.get("error", ""), r.get("error", "")[:70])
chamar(adm, "gerir_rosto", acao="zerar_tentativas")
for o in chamar(adm, "listar_rostos")["operadores"]:
    if o["nome"].startswith("Teste Rosto"):
        chamar(adm, "gerir_rosto", usuario=o["usuario"], acao="remover")


def ordem_errada(quadros):
    quadros[1], quadros[2] = quadros[2], quadros[1]


r = entrar(requests.Session(), A, "Teste Rosto Ana", "Armação", mudar=ordem_errada)
ok("passos fora da ordem sorteada são recusados", not r.get("success") and r.get("prova_de_vida") is False, r.get("error", "")[:70])


def mesmo_lado(quadros):
    for q in quadros:
        if q["acao"] == "virar_oposto":
            q["metricas"]["yaw"] = 0.30


r = entrar(requests.Session(), A, "Teste Rosto Ana", "Armação", mudar=mesmo_lado)
ok("virar duas vezes para o mesmo lado é recusado", not r.get("success") and "contrário" in r.get("error", ""), r.get("error", "")[:70])


def outra_pessoa(quadros):
    for q in quadros:
        if q["acao"] in ("sorrir", "abrir_boca"):
            q["descritor"] = B


r = entrar(requests.Session(), A, "Teste Rosto Ana", "Armação", mudar=outra_pessoa)
ok("outro rosto no meio da verificação é recusado", not r.get("success") and "rosto mudou" in r.get("error", ""), r.get("error", "")[:70])

print("[Primeiro acesso]")
op = requests.Session()
r = entrar(op, A, "Teste Rosto Ana", "Armação")
ok("rosto novo + nome + setor + prova de vida cadastra e entra", r.get("success") and r.get("primeiro_acesso") and r["setores"] == ["Armação"], str(r))
pecas = chamar(op, "get_pieces", obra=OBRA)
ok("depois do cadastro a sessão está aberta (vê as peças)", pecas.get("success") and len(pecas["pieces"]) == 4)
r = entrar(requests.Session(), B)
ok("rosto novo sem nome e setor pede o cadastro", r.get("success") and r.get("precisa_cadastro"))

print("[Voltando e outro setor]")
op2 = requests.Session()
r = entrar(op2, parecido(A), "Teste Rosto Ana", "Armação")
ok("mesmo rosto entra de novo no setor dele", r.get("success") and not r.get("primeiro_acesso"), str(r))
op3 = requests.Session()
r = entrar(op3, parecido(A), "Teste Rosto Ana", "Forma")
ok("mesmo rosto em outro setor é barrado", not r.get("success") and r.get("bloqueado_setor"), r.get("error", "")[:90])
ok("barrado não ganha sessão", op3.post(f"{URL}/api/method/frappe.precast_api.get_pieces", json={}).status_code in (401, 403))
r = entrar(requests.Session(), rosto(), "Teste Rosto Bia", "Forma")
ok("outra pessoa se cadastra em outro setor", r.get("success") and r.get("primeiro_acesso") and r["setores"] == ["Forma"])

print("[Restrição por setor]")
cod = chamar(adm, "get_pieces", obra=OBRA)["pieces"][0]["codigo_peca"]
r = chamar(op2, "advance_piece_phase", codigo_peca=cod)
ok("operador de Armação não avança peça que está em Corte e Dobra", not r.get("success") and "Corte e Dobra" in r.get("error", ""), r.get("error", "")[:100])
chamar(adm, "advance_piece_phase", codigo_peca=cod, forcar=True)
r = chamar(op2, "advance_piece_phase", codigo_peca=cod)
ok("operador de Armação avança peça que está em Armação", r.get("success"), str(r.get("error", ""))[:100])

print("[Responsável libera setores]")
ana = next(o for o in chamar(adm, "listar_rostos")["operadores"] if o["nome"] == "Teste Rosto Ana")
chamar(adm, "gerir_rosto", usuario=ana["usuario"], acao="setores", setores=json.dumps(["Armação", "Forma"]))
r = entrar(requests.Session(), parecido(A), "Teste Rosto Ana", "Forma")
ok("com o setor liberado, o mesmo rosto entra", r.get("success") and set(r["setores"]) == {"Armação", "Forma"}, str(r)[:100])
chamar(adm, "gerir_rosto", usuario=ana["usuario"], acao="bloquear")
r = entrar(requests.Session(), parecido(A))
ok("rosto bloqueado não entra (vira rosto novo)", r.get("precisa_cadastro") or not r.get("success"))
chamar(adm, "gerir_rosto", usuario=ana["usuario"], acao="liberar")

print("[LGPD: termo, consentimento e direitos do titular]")
termo = requests.post(f"{URL}/api/method/frappe.precast_api.termo_lgpd", json={}).json()["message"]
ok("o termo é público (aparece antes do cadastro) e diz a finalidade e os direitos", termo["success"] and "reconhecimento facial" in termo["texto"] and "exclusão" in termo["texto"] and termo["versao"], termo["versao"])
r = entrar(requests.Session(), rosto(), "Teste Rosto Dani", "Cura", consentimento=False)
ok("cadastrar o rosto sem aceitar o termo é recusado", not r.get("success") and r.get("precisa_consentimento"), str(r.get("error")))
ok("e nenhum cadastro foi criado", not any(o["nome"] == "Teste Rosto Dani" for o in chamar(adm, "listar_rostos")["operadores"]))
D = rosto()
r = entrar(requests.Session(), D, "Teste Rosto Dani", "Cura")
ok("aceitando o termo, o cadastro é feito", r.get("success") and r.get("primeiro_acesso"), str(r))
dani = next(o for o in chamar(adm, "listar_rostos")["operadores"] if o["nome"] == "Teste Rosto Dani")
ok("o aceite fica registrado e aparece na gestão", dani["consentimento"] is True)
exp = chamar(adm, "lgpd_exportar_titular", usuario=dani["usuario"])
ok("o titular pode pedir uma cópia dos dados: cadastro, consentimentos e etapas", exp["success"] and exp["cadastro"]["nome"] == "Teste Rosto Dani" and len(exp["consentimentos"]) == 1 and "etapas_registradas_na_producao" in exp, str(exp)[:140])
ok("a cópia dos dados não traz o descritor do rosto", "descritor" not in json.dumps(exp))
ok("operador por rosto não exporta nem exclui dados de outro", chamar(op2, "lgpd_exportar_titular", usuario=dani["usuario"]).get("success") is not True and chamar(op2, "lgpd_excluir_titular", usuario=dani["usuario"]).get("success") is not True)
ex = chamar(adm, "lgpd_excluir_titular", usuario=dani["usuario"])
ok("excluir os dados apaga o rosto e retira o consentimento", ex["success"] and not any(o["nome"] == "Teste Rosto Dani" for o in chamar(adm, "listar_rostos")["operadores"]))
r = entrar(requests.Session(), parecido(D))
ok("depois da exclusão o rosto é desconhecido de novo", r.get("precisa_cadastro"), str(r))
ok("excluir de novo informa que não há dados", not chamar(adm, "lgpd_excluir_titular", usuario=dani["usuario"]).get("success"))

print("[Cadastro fechado]")
chamar(adm, "gerir_rosto", acao="cadastro_aberto", aberto=False)
r = entrar(requests.Session(), C, "Teste Rosto Caio", "Cura")
ok("com o cadastro fechado, rosto novo não entra", not r.get("success") and "fechado" in r.get("error", ""), r.get("error", "")[:80])
r = entrar(requests.Session(), parecido(A))
ok("quem já está cadastrado continua entrando", r.get("success") and not r.get("precisa_cadastro"))
chamar(adm, "gerir_rosto", acao="cadastro_aberto", aberto=True)

print("[Segurança]")
ok("operador por rosto não gerencia rostos", not chamar(op2, "gerir_rosto", acao="cadastro_aberto", aberto=True).get("success"))
ok("operador por rosto não liga nem desliga a prova de vida", not chamar(op2, "gerir_rosto", acao="prova_de_vida", aberto=False).get("success"))
ok("operador por rosto não vê o painel de rostos", not chamar(op2, "listar_rostos").get("success"))
ruim = chamar(requests.Session(), "rosto_entrar", descritor=json.dumps([1, 2, 3]))
ok("descritor inválido é recusado", not ruim.get("success"))
chamar(adm, "gerir_rosto", acao="prova_de_vida", aberto=False)
r = chamar(requests.Session(), "rosto_entrar", descritor=json.dumps(parecido(A)))
ok("com a prova de vida desligada pelo responsável, só o rosto basta (menos seguro)", r.get("success"))
chamar(adm, "gerir_rosto", acao="prova_de_vida", aberto=True)
limite = requests.Session(); bloqueou = False
for _ in range(40):
    x = chamar(limite, "rosto_entrar", descritor=json.dumps(rosto()))
    if not x.get("success") and "tentativas" in x.get("error", ""):
        bloqueou = True; break
ok("muitas tentativas seguidas são barradas", bloqueou)

# limpeza
chamar(adm, "gerir_rosto", acao="zerar_tentativas")
for o in chamar(adm, "listar_rostos").get("operadores", []):
    if o["nome"].startswith("Teste Rosto"):
        chamar(adm, "gerir_rosto", usuario=o["usuario"], acao="remover")
chamar(adm, "delete_obra", codigo_obra=OBRA)
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
