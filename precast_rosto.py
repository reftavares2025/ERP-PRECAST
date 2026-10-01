"""Entrada do operador de produção pelo rosto.

O celular calcula um descritor do rosto (128 números) na própria tela; a foto não sai do aparelho e não é
guardada. No primeiro acesso a pessoa informa o nome e o setor e tira a foto: fica cadastrada nesse setor. Nos
acessos seguintes, só a foto. Quem já está num setor não entra em outro: só o responsável acrescenta setores.

Prova de vida: antes de entrar, a pessoa cumpre um desafio sorteado pelo servidor (olhar de frente, virar a
cabeça para um lado e para o outro, sorrir ou abrir a boca). O celular manda as medidas do rosto de cada passo e o
descritor dos passos de frente; o servidor confere o desafio, a ordem, o tempo e se é o mesmo rosto em todos os
passos. Uma foto parada, ou uma foto de uma foto, não cumpre o desafio. Um vídeo da própria pessoa respondendo ao
desafio em tempo real ainda poderia enganar.
"""
import json
import math
import re

import frappe

DOCTYPE = "Rosto Operador"
LIMIAR = 0.5                      # distância máxima entre dois descritores da mesma pessoa
MARGEM_SEGUNDO = 0.04             # o melhor tem que ganhar do segundo colocado por esta folga
TENTATIVAS_POR_IP = 30            # tentativas de entrada por rosto em 5 minutos
CHAVE_CADASTRO_ABERTO = "rosto_cadastro_aberto"

# Cada setor trabalha a fase em que a peça está: o operador de "Armação" avança as peças que estão em Armação.
SETORES_PRODUCAO = ["Corte e Dobra", "Armação", "Forma", "Concretagem", "Cura", "Pátio / CQ", "Expedição", "Montagem em Obra"]


def fase_do_setor(setor):
    return SETORES_PRODUCAO.index(setor) + 1


def cadastro_aberto():
    valor = frappe.defaults.get_global_default(CHAVE_CADASTRO_ABERTO)
    return True if valor is None else str(valor) == "1"


def definir_cadastro_aberto(aberto):
    frappe.defaults.set_global_default(CHAVE_CADASTRO_ABERTO, "1" if aberto else "0")


def _descritor_valido(d):
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except ValueError:
            return None
    if not isinstance(d, list) or len(d) != 128:
        return None
    try:
        return [float(x) for x in d]
    except (TypeError, ValueError):
        return None


def _distancia(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _limitar_tentativas():
    ip = getattr(frappe.local, "request_ip", None) or "?"
    chave = f"rosto_tentativas:{ip}"
    feitas = int(frappe.cache.get_value(chave) or 0)
    if feitas >= TENTATIVAS_POR_IP:
        frappe.throw("Muitas tentativas seguidas. Aguarde alguns minutos e tente de novo.")
    frappe.cache.set_value(chave, feitas + 1, expires_in_sec=300)


def zerar_tentativas():
    """Zera o contador de tentativas por IP (o responsável usa quando a equipe inteira sai do mesmo roteador)."""
    frappe.cache.delete_keys("rosto_tentativas:*")


import secrets
import time

CHAVE_PROVA_DE_VIDA = "rosto_prova_de_vida"
VALIDADE_DESAFIO = 180            # segundos para cumprir o desafio
ESPERA_MINIMA = 3.0               # nenhum desafio honesto termina antes disso
GIRO_NEUTRO = 0.10                # |yaw| máximo de um rosto "de frente"
GIRO_MINIMO = 0.18                # |yaw| mínimo de um giro de cabeça
SORRISO_MINIMO = 1.10             # largura da boca em relação à do passo de frente
BOCA_ABERTA_MINIMA = 0.12         # abertura da boca acima da do passo de frente
DISTANCIA_MESMO_ROSTO = 0.55      # entre os descritores dos passos de frente


def prova_de_vida_exigida():
    valor = frappe.defaults.get_global_default(CHAVE_PROVA_DE_VIDA)
    return True if valor is None else str(valor) == "1"


def definir_prova_de_vida(exigida):
    frappe.defaults.set_global_default(CHAVE_PROVA_DE_VIDA, "1" if exigida else "0")


def novo_desafio():
    """Sorteia a ordem: de frente primeiro; depois o par de giros (um lado e o oposto) e uma expressão, antes ou depois."""
    expressao = secrets.choice(["sorrir", "abrir_boca"])
    giros = ["virar", "virar_oposto"]
    passos = ["neutro"] + (giros + [expressao] if secrets.randbelow(2) else [expressao] + giros)
    token = secrets.token_urlsafe(18)
    frappe.cache.set_value(f"rosto_desafio:{token}", {"acoes": passos, "emitido": time.time()}, expires_in_sec=VALIDADE_DESAFIO + 30)
    return {"token": token, "acoes": passos, "validade_s": VALIDADE_DESAFIO}


def validar_desafio(desafio, descritor_principal):
    """Devolve None se a prova de vida passou, ou o motivo (texto para a pessoa) se não passou."""
    if not isinstance(desafio, dict) or not desafio.get("token"):
        return "Falta a verificação de que você é uma pessoa de verdade. Atualize a página e tente de novo."
    chave = f"rosto_desafio:{desafio['token']}"
    emitido = frappe.cache.get_value(chave)
    frappe.cache.delete_value(chave)  # cada desafio vale uma vez
    if not emitido:
        return "A verificação expirou ou já foi usada. Tente de novo."
    decorrido = time.time() - emitido["emitido"]
    if decorrido > VALIDADE_DESAFIO:
        return "A verificação demorou demais. Tente de novo."
    if decorrido < ESPERA_MINIMA:
        return "A verificação foi rápida demais para ser feita por uma pessoa. Tente de novo."
    acoes, quadros = emitido["acoes"], desafio.get("quadros")
    if not isinstance(quadros, list) or [q.get("acao") for q in quadros if isinstance(q, dict)] != acoes:
        return "Os passos da verificação não bateram com o pedido. Tente de novo."

    def num(q, nome):
        try:
            return float((q.get("metricas") or {})[nome])
        except (KeyError, TypeError, ValueError):
            return None

    tempos = []
    for q in quadros:
        try:
            tempos.append(float(q.get("t")))
        except (TypeError, ValueError):
            return "Verificação incompleta. Tente de novo."
    if any(b - a < 600 for a, b in zip(tempos, tempos[1:])):
        return "Os passos da verificação vieram rápido demais. Tente de novo."

    neutro = quadros[0]
    yaw0, boca0, larg0 = num(neutro, "yaw"), num(neutro, "boca"), num(neutro, "largura_boca")
    if None in (yaw0, boca0, larg0) or abs(yaw0) > GIRO_NEUTRO:
        return "Olhe de frente para a câmera no primeiro passo."
    descritores = [_descritor_valido(neutro.get("descritor"))]
    primeiro_giro = None
    for q in quadros[1:]:
        acao, yaw = q["acao"], num(q, "yaw")
        if acao == "virar":
            if yaw is None or abs(yaw) < GIRO_MINIMO:
                return "Vire a cabeça para um lado, bem devagar, até aparecer o aviso."
            primeiro_giro = yaw
        elif acao == "virar_oposto":
            if yaw is None or primeiro_giro is None or abs(yaw) < GIRO_MINIMO or yaw * primeiro_giro >= 0:
                return "Agora vire a cabeça para o lado contrário."
        elif acao in ("sorrir", "abrir_boca"):
            larg, boca = num(q, "largura_boca"), num(q, "boca")
            if yaw is None or abs(yaw) > GIRO_NEUTRO + 0.08 or larg is None or boca is None:
                return "Olhe de frente para a câmera neste passo."
            if acao == "sorrir" and not (larg >= larg0 * SORRISO_MINIMO and boca < 0.35):
                return "Sorria mostrando os dentes."
            if acao == "abrir_boca" and not (boca >= boca0 + BOCA_ABERTA_MINIMA):
                return "Abra bem a boca."
            descritores.append(_descritor_valido(q.get("descritor")))
        else:
            return "Passo desconhecido na verificação."
    if len(descritores) < 2 or any(d is None for d in descritores):
        return "Faltou ler o rosto de frente em dois passos. Tente de novo."
    if _distancia(descritores[0], descritor_principal) > 1e-3 or any(_distancia(d, descritores[0]) > DISTANCIA_MESMO_ROSTO for d in descritores[1:]):
        return "O rosto mudou durante a verificação. Tente de novo, só você na frente da câmera."
    return None


def _melhor_correspondencia(descritor):
    """(registro, distância) do cadastrado mais parecido, ou (None, None) se nenhum passa do limiar."""
    ranking = []
    for r in frappe.get_all(DOCTYPE, filters={"ativo": 1}, fields=["name", "usuario", "nome", "setores", "descritor"]):
        try:
            ranking.append((_distancia(descritor, json.loads(r.descritor)), r))
        except ValueError:
            continue
    ranking.sort(key=lambda x: x[0])
    if not ranking or ranking[0][0] > LIMIAR:
        return None, None
    if len(ranking) > 1 and ranking[1][0] - ranking[0][0] < MARGEM_SEGUNDO and ranking[1][0] <= LIMIAR:
        frappe.throw("Não consegui separar este rosto de outro cadastrado. Tire a foto de novo, de frente e com boa luz.")
    return ranking[0][1], ranking[0][0]


def _setores_do(r):
    try:
        return [s for s in json.loads(r.setores or "[]") if s in SETORES_PRODUCAO]
    except ValueError:
        return []


def _login(usuario):
    from frappe.auth import LoginManager
    gerenciador = frappe.local.login_manager if getattr(frappe.local, "login_manager", None) else LoginManager()
    gerenciador.user = usuario
    gerenciador.post_login()


def entrar(descritor, nome=None, setor=None, desafio=None):
    """Entra pelo rosto. Sem cadastro anterior e com nome e setor, cadastra a pessoa (se o cadastro estiver aberto).
    Exige a prova de vida (desafio) enquanto ela estiver ligada."""
    _limitar_tentativas()
    d = _descritor_valido(descritor)
    if d is None:
        return {"success": False, "error": "Não consegui ler o rosto. Tire a foto de novo, de frente e com boa luz."}
    if isinstance(desafio, str):
        try:
            desafio = json.loads(desafio)
        except ValueError:
            desafio = None
    if prova_de_vida_exigida():
        motivo = validar_desafio(desafio, d)
        if motivo:
            return {"success": False, "prova_de_vida": False, "error": motivo}
    if setor and setor not in SETORES_PRODUCAO:
        return {"success": False, "error": "Setor inválido."}

    achado, _ = _melhor_correspondencia(d)
    if achado:
        setores = _setores_do(achado)
        if setor and setor not in setores:
            return {"success": False, "bloqueado_setor": True,
                    "error": f"Você já está vinculado ao setor {', '.join(setores) or '—'}. Para trabalhar em {setor}, peça ao responsável para liberar."}
        frappe.db.set_value(DOCTYPE, achado.name, "ultimo_acesso", frappe.utils.now_datetime())
        _login(achado.usuario)
        frappe.db.commit()
        return {"success": True, "nome": achado.nome, "setores": setores, "primeiro_acesso": False}

    nome = (nome or "").strip()
    if not nome or not setor:
        return {"success": True, "precisa_cadastro": True, "mensagem": "Rosto novo. Informe o nome e o setor para se cadastrar."}
    if not cadastro_aberto():
        return {"success": False, "error": "O cadastro pelo próprio operador está fechado. Procure o responsável."}
    if len(nome) < 3:
        return {"success": False, "error": "Escreva o nome completo."}

    usuario = _criar_usuario(nome)
    frappe.get_doc({"doctype": DOCTYPE, "usuario": usuario, "nome": nome, "setores": json.dumps([setor], ensure_ascii=False),
                    "descritor": json.dumps([round(x, 6) for x in d]), "ativo": 1,
                    "ultimo_acesso": frappe.utils.now_datetime()}).insert(ignore_permissions=True)
    _login(usuario)
    frappe.db.commit()
    return {"success": True, "nome": nome, "setores": [setor], "primeiro_acesso": True}


def _criar_usuario(nome):
    base = re.sub(r"[^a-z0-9]+", ".", nome.lower().encode("ascii", "ignore").decode() or "operador").strip(".") or "operador"
    email = f"{base}.{frappe.utils.random_string(5).lower()}@operador.precast"
    if not frappe.db.exists("Role", "Operador de Fábrica"):
        frappe.get_doc({"doctype": "Role", "role_name": "Operador de Fábrica", "desk_access": 0}).insert(ignore_permissions=True)
    frappe.get_doc({"doctype": "User", "email": email, "first_name": nome, "user_type": "Website User", "send_welcome_email": 0,
                    "new_password": frappe.utils.random_string(24), "roles": [{"role": "Operador de Fábrica"}]}).insert(ignore_permissions=True)
    return email


# ------------------------------------------------------------------ restrição por setor
def fases_permitidas(usuario):
    """None = sem restrição (usuário comum); senão, o conjunto de fases em que este operador pode avançar peças."""
    r = frappe.db.get_value(DOCTYPE, {"usuario": usuario, "ativo": 1}, ["setores"], as_dict=True)
    if not r:
        return None
    return {fase_do_setor(s) for s in _setores_do(r)}


# ------------------------------------------------------------------ gestão (Direção)
def listar():
    saida = []
    for r in frappe.get_all(DOCTYPE, fields=["name", "usuario", "nome", "setores", "ativo", "ultimo_acesso"], order_by="nome asc"):
        saida.append({"usuario": r.usuario, "nome": r.nome, "setores": _setores_do(r), "ativo": bool(r.ativo),
                      "ultimo_acesso": str(r.ultimo_acesso or "")[:16]})
    return saida


def _registro(usuario):
    nome = frappe.db.get_value(DOCTYPE, {"usuario": usuario}, "name")
    if not nome:
        frappe.throw("Cadastro não encontrado.")
    return frappe.get_doc(DOCTYPE, nome)


def definir_setores(usuario, setores):
    novos = [s for s in (setores or []) if s in SETORES_PRODUCAO]
    if not novos:
        frappe.throw("Escolha ao menos um setor.")
    doc = _registro(usuario)
    doc.setores = json.dumps(novos, ensure_ascii=False)
    doc.save(ignore_permissions=True)


def definir_ativo(usuario, ativo):
    doc = _registro(usuario)
    doc.ativo = 1 if ativo else 0
    doc.save(ignore_permissions=True)
    frappe.db.set_value("User", usuario, "enabled", 1 if ativo else 0)


def remover(usuario):
    doc = _registro(usuario)
    frappe.delete_doc(DOCTYPE, doc.name, ignore_permissions=True, force=True)
    frappe.db.set_value("User", usuario, "enabled", 0)
