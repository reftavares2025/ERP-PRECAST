import functools
import hashlib
import hmac
import json
import os
import re
import time
import frappe
from frappe import _

def _texto_limpo(msg):
    return re.sub(r"<[^>]+>", "", str(msg)).strip()


def _amigavel(fn):
    """Toda função exposta responde {success: False, error: "..."} com a causa em português,
    em vez de uma exceção que a tela só consegue mostrar como "erro desconhecido". Deadlock
    do banco (duas telas gravando juntas) é repetido até 3 vezes antes de desistir."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        for tentativa in range(3):
            try:
                return fn(*args, **kwargs)
            except (frappe.PermissionError, frappe.AuthenticationError, frappe.SessionExpired):
                raise
            except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
                frappe.db.rollback()
                if tentativa == 2:
                    frappe.log_error(title=f"{fn.__name__}: banco ocupado", message=frappe.get_traceback())
                    return {"success": False, "error": "O sistema estava ocupado com outra gravação. Tente de novo em alguns segundos."}
                time.sleep(0.5 * (tentativa + 1))
            except Exception as e:
                frappe.db.rollback()
                frappe.log_error(title=f"{fn.__name__} falhou", message=frappe.get_traceback())
                return {"success": False, "error": _texto_limpo(e) or "Erro inesperado. Avise o suporte."}
    return wrapper


def endpoint(**opcoes):
    """Substitui o decorador de exposição do Frappe: expõe a função com o tratamento de erro acima."""
    def decorador(fn):
        return frappe.whitelist(**opcoes)(_amigavel(fn))
    return decorador


@endpoint(allow_guest=True)
def enviar_contato(nome, email, empresa=None, telefone=None, mensagem=None):
    """
    Único endpoint público do sistema — o formulário de contato da página
    de apresentação, acessível antes do login. Toda a operação do sistema
    em si vive atrás de autenticação real (ver remoção de allow_guest nos
    demais endpoints deste arquivo).
    """
    if not nome or not email:
        return {"success": False, "error": "Nome e e-mail são obrigatórios"}

    doc = frappe.get_doc({
        "doctype": "Contato Comercial",
        "nome": nome.strip(), "email": email.strip(),
        "empresa": (empresa or "").strip(), "telefone": (telefone or "").strip(),
        "mensagem": (mensagem or "").strip(),
        "data_envio": frappe.utils.now_datetime(), "status": "Novo"
    })
    doc.insert(ignore_permissions=True)

    # Notifica o Administrator dentro do próprio sistema (sino de
    # notificações) — sem depender de SMTP configurado, que este ambiente
    # ainda não tem.
    try:
        frappe.get_doc({
            "doctype": "Notification Log",
            "subject": f"Novo contato comercial: {nome} ({empresa or 'sem empresa'})",
            "for_user": "Administrator",
            "type": "Alert",
            "document_type": "Contato Comercial",
            "document_name": doc.name,
            "email_content": f"E-mail: {email}<br>Telefone: {telefone or '-'}<br>Mensagem: {mensagem or '-'}"
        }).insert(ignore_permissions=True)
    except Exception:
        pass  # notificação é best-effort; o registro do contato já foi salvo

    _notificar_contato_whatsapp(nome, email, empresa, telefone, mensagem)

    # Todo contato do site vira Lead de verdade no funil comercial (CRM),
    # não só um registro informativo — best-effort, nunca bloqueia o envio.
    try:
        criar_lead_comercial(nome=nome, empresa=empresa, telefone=telefone, email=email,
                              obra_interesse=mensagem, fonte="Site")
    except Exception as e:
        frappe.log_error(title="Falha ao criar Lead a partir do contato", message=str(e))

    frappe.db.commit()
    return {"success": True, "message": "Contato recebido com sucesso"}


def _restaurar_usuario(fn):
    """Funções que elevam para Administrator (criar Item/Fatura exige isso) devolvem
    a sessão ao usuário de verdade ao terminar. Sem isso, quem chamou fica deslogado."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        sessao = frappe.local.session
        usuario, sid, dados = sessao.user, sessao.sid, sessao.data
        try:
            return fn(*args, **kwargs)
        finally:
            # set_user troca user, sid e data da sessão: restaura os três, senão o
            # fim da requisição grava a sessão errada e o usuário é deslogado.
            frappe.set_user(usuario)
            frappe.local.session.sid = sid
            frappe.local.session.data = dados
    return wrapper


def _whatsapp_config():
    """Credenciais do WhatsApp (Evolution API) - vivem no site_config.json
    (fora do git), nunca em texto puro no codigo-fonte versionado.
    Configurar com:
      bench --site frontend set-config whatsapp_evolution_url "<url>"
      bench --site frontend set-config whatsapp_evolution_instance "<instancia>"
      bench --site frontend set-config whatsapp_evolution_apikey "<apikey>"
      bench --site frontend set-config whatsapp_notificar_numero "<numero>"
    """
    return {
        "url": (frappe.conf.get("whatsapp_evolution_url") or "").strip(),
        "instance": (frappe.conf.get("whatsapp_evolution_instance") or "").strip(),
        "apikey": (frappe.conf.get("whatsapp_evolution_apikey") or "").strip(),
        "numero_admin": (frappe.conf.get("whatsapp_notificar_numero") or "").strip(),
    }


def _enviar_whatsapp(numero, texto):
    """Envia uma mensagem de texto via Evolution API. Best-effort: nunca
    levanta - se o WhatsApp nao estiver configurado/conectado, quem chamou
    segue o fluxo normalmente (o dado ja foi salvo no sistema antes)."""
    import requests

    cfg = _whatsapp_config()
    if not (cfg["url"] and cfg["instance"] and cfg["apikey"] and numero):
        return False
    try:
        resposta = requests.post(
            f"{cfg['url']}/message/sendText/{cfg['instance']}",
            headers={"apikey": cfg["apikey"], "Content-Type": "application/json"},
            json={"number": numero, "text": texto},
            timeout=20,
        )
        if not resposta.ok:
            frappe.log_error(title="WhatsApp recusou a mensagem", message=f"HTTP {resposta.status_code}: {resposta.text[:300]}")
        return resposta.ok
    except Exception as e:
        frappe.log_error(title="Falha ao enviar WhatsApp", message=str(e))
        return False


def _notificar_contato_whatsapp(nome, email, empresa, telefone, mensagem):
    """
    Avisa no WhatsApp assim que um lead chega pelo formulario de contato da
    pagina de apresentacao - best-effort: se o WhatsApp nao estiver
    conectado, o contato ja foi salvo no sistema mesmo assim.
    """
    texto = (
        "🔔 *Novo contato no ERP Precast*\n\n"
        f"*Nome:* {nome}\n"
        f"*Empresa:* {empresa or '-'}\n"
        f"*Telefone:* {telefone or '-'}\n"
        f"*E-mail:* {email}\n"
        f"*Mensagem:* {mensagem or '-'}"
    )
    numero = _whatsapp_config()["numero_admin"]
    if numero:
        _enviar_whatsapp(numero, texto)

VALORES_SUGERIDOS_HISTORICO = {
    "Aço CA-50": {"valor": 2.74, "unidade": "kg"},
    "Aço CA-60": {"valor": 2.73, "unidade": "kg"},
    "Cimento CP-II": {"valor": 0.43, "unidade": "kg"},
    "Cimento CP-V": {"valor": 0.43, "unidade": "kg"},
    "Areia": {"valor": 44.00, "unidade": "m³"},
    "Brita/Pedra": {"valor": 35.46, "unidade": "m³"},
    "Cordoalha": {"valor": 2.24, "unidade": "unidade"},
}
"""
Medias historicas extraidas de ~1290 planilhas de orcamento reais (aba
INSUMOS, safra 2024-2026) - servem so de sugestao inicial pro painel de
Cotacoes; cada cliente confirma ou ajusta antes de lancar de verdade.
"""

COTACAO_INSUMOS_PADRAO = [
    "Dólar (USD)", "Aço CA-50", "Aço CA-60", "Cimento CP-II",
    "Cimento CP-V", "Areia", "Brita/Pedra", "Cordoalha", "Terra"
]


# Matérias-primas extras e padrão ocultas ficam no cadastro de valores padrão do site
# (DefaultValue), sem tabela nova. Cada cliente (site) tem a sua própria lista.
_CHAVE_INSUMOS_EXTRAS = "insumos_extras"
_CHAVE_INSUMOS_OCULTOS = "insumos_ocultos"
INSUMOS_PROTEGIDOS = {"Dólar (USD)", "Aço CA-50", "Cimento CP-II"}  # o orçador automático usa estes
UNIDADES_INSUMO = ["kg", "saca 50kg", "ton", "m³", "unidade"]


def _ler_lista_insumos(chave):
    bruto = frappe.defaults.get_global_default(chave)
    try:
        return json.loads(bruto) if bruto else []
    except ValueError:
        return []


def _gravar_lista_insumos(chave, lista):
    frappe.defaults.set_global_default(chave, json.dumps(lista, ensure_ascii=False))


def _cotacao_do_insumo(insumo, data, nome_extra=None):
    """Lançamento da data pedida; se não houver, o último anterior (desatualizado)."""
    filtros = {"insumo": "Outro", "insumo_outro": nome_extra} if nome_extra else {"insumo": insumo}
    campos = ["name", "data", "insumo", "insumo_outro", "valor", "unidade", "fonte", "observacao", "lancado_por"]
    do_dia = frappe.get_all("Cotacao Insumo", filters={**filtros, "data": data}, fields=campos, limit=1)
    if do_dia:
        return {**do_dia[0], "atualizado": True}
    anterior = frappe.get_all("Cotacao Insumo", filters={**filtros, "data": ["<", data]}, fields=campos,
                              order_by="data desc", limit=1)
    if anterior:
        return {**anterior[0], "atualizado": False}
    return None


@endpoint()
def get_cotacoes(data=None):
    """
    Painel de cotacoes do dia: para cada materia-prima (padrao + as que o cliente
    cadastrou), traz o lancamento da data pedida (default hoje) e, se nao houver, o
    ultimo anterior (marcado como desatualizado) ou a media historica sugerida - assim
    o orcamento sempre tem um preco de referencia.
    """
    data = data or frappe.utils.nowdate()
    ocultos = set(_ler_lista_insumos(_CHAVE_INSUMOS_OCULTOS))
    extras = _ler_lista_insumos(_CHAVE_INSUMOS_EXTRAS)
    resultado = []

    for insumo in COTACAO_INSUMOS_PADRAO:
        if insumo in ocultos:
            continue
        item = _cotacao_do_insumo(insumo, data)
        if item is None:
            sugestao = VALORES_SUGERIDOS_HISTORICO.get(insumo)
            item = {"insumo": insumo, "valor": sugestao["valor"] if sugestao else None,
                    "unidade": sugestao["unidade"] if sugestao else None, "data": None,
                    "fonte": "Sugestão (média histórica de orçamentos)" if sugestao else None, "atualizado": False}
        item.update({"nome": insumo, "personalizado": False, "protegido": insumo in INSUMOS_PROTEGIDOS})
        resultado.append(item)

    for extra in extras:
        item = _cotacao_do_insumo("Outro", data, nome_extra=extra["nome"])
        if item is None:
            item = {"insumo": "Outro", "valor": None, "unidade": extra.get("unidade"), "data": None, "atualizado": False}
        item.update({"nome": extra["nome"], "personalizado": True, "protegido": False})
        resultado.append(item)

    return {"success": True, "data": data, "cotacoes": resultado, "unidades": UNIDADES_INSUMO}


def _upsert_cotacao_insumo(data, nome, valor, unidade, observacao):
    """Grava a cotação de uma matéria-prima (padrão ou extra) numa data. Devolve (ok, erro)."""
    extras = {e["nome"] for e in _ler_lista_insumos(_CHAVE_INSUMOS_EXTRAS)}
    if nome in COTACAO_INSUMOS_PADRAO:
        insumo, outro = nome, None
    elif nome in extras:
        insumo, outro = "Outro", nome
    else:
        return False, f"Matéria-prima '{nome}' não cadastrada."
    try:
        valor = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return False, f"Valor inválido em {nome}."
    if valor < 0:
        return False, f"Valor de {nome} não pode ser negativo."
    resultado = lancar_cotacao(data=data, insumo=insumo, valor=valor, unidade=unidade or None,
                               insumo_outro=outro, observacao=observacao or None, fonte="Manual")
    return bool(resultado.get("success")), resultado.get("error")


@endpoint()
def salvar_cotacoes(data, itens):
    """Salva de uma vez as cotações editadas na tela (valor, unidade e observação por linha)."""
    _exigir_papel("Financeiro", "Produção", "Direção")
    if isinstance(itens, str):
        itens = json.loads(itens)
    if not data:
        return {"success": False, "error": "Informe a data."}
    salvos, erros = 0, []
    for it in itens or []:
        if it.get("valor") in (None, ""):
            continue
        ok, erro = _upsert_cotacao_insumo(data, it.get("nome"), it.get("valor"), it.get("unidade"), it.get("observacao"))
        if ok:
            salvos += 1
        else:
            erros.append(erro)
    if erros:
        return {"success": False, "salvos": salvos, "error": " ".join(erros)}
    return {"success": True, "salvos": salvos, "message": f"{salvos} cotação(ões) salva(s)."}


@endpoint()
def adicionar_insumo(nome, unidade="kg", valor=None, data=None):
    """Cadastra uma matéria-prima nova (ou traz de volta uma padrão que foi excluída)."""
    _exigir_papel("Financeiro", "Produção", "Direção")
    nome = (nome or "").strip()
    if not 2 <= len(nome) <= 40:
        return {"success": False, "error": "O nome da matéria-prima deve ter de 2 a 40 caracteres."}
    if unidade not in UNIDADES_INSUMO:
        return {"success": False, "error": f"Unidade inválida. Use: {', '.join(UNIDADES_INSUMO)}."}

    existentes = [i.lower() for i in COTACAO_INSUMOS_PADRAO] + [e["nome"].lower() for e in _ler_lista_insumos(_CHAVE_INSUMOS_EXTRAS)]
    ocultos = _ler_lista_insumos(_CHAVE_INSUMOS_OCULTOS)
    padrao = next((i for i in COTACAO_INSUMOS_PADRAO if i.lower() == nome.lower()), None)
    if padrao and padrao in ocultos:
        _gravar_lista_insumos(_CHAVE_INSUMOS_OCULTOS, [o for o in ocultos if o != padrao])
        nome = padrao
    elif nome.lower() in existentes:
        return {"success": False, "error": f"'{nome}' já está na lista."}
    else:
        extras = _ler_lista_insumos(_CHAVE_INSUMOS_EXTRAS)
        extras.append({"nome": nome, "unidade": unidade})
        _gravar_lista_insumos(_CHAVE_INSUMOS_EXTRAS, extras)

    if valor not in (None, ""):
        ok, erro = _upsert_cotacao_insumo(data or frappe.utils.nowdate(), nome, valor, unidade, None)
        if not ok:
            frappe.db.commit()
            return {"success": False, "error": erro}
    frappe.db.commit()
    return {"success": True, "nome": nome, "message": f"'{nome}' adicionada."}


@endpoint()
def excluir_insumo(nome):
    """Exclui uma matéria-prima. As extras somem com o histórico; as padrão só saem da lista
    (o histórico fica). Dólar, aço CA-50 e cimento CP-II não saem: o orçamento automático usa."""
    _exigir_papel("Financeiro", "Produção", "Direção")
    if nome in INSUMOS_PROTEGIDOS:
        return {"success": False, "error": f"'{nome}' não pode ser excluída: o orçamento automático usa esse preço."}
    extras = _ler_lista_insumos(_CHAVE_INSUMOS_EXTRAS)
    if any(e["nome"] == nome for e in extras):
        _gravar_lista_insumos(_CHAVE_INSUMOS_EXTRAS, [e for e in extras if e["nome"] != nome])
        for linha in frappe.get_all("Cotacao Insumo", filters={"insumo": "Outro", "insumo_outro": nome}, pluck="name"):
            frappe.delete_doc("Cotacao Insumo", linha, ignore_permissions=True, force=True)
    elif nome in COTACAO_INSUMOS_PADRAO:
        ocultos = _ler_lista_insumos(_CHAVE_INSUMOS_OCULTOS)
        if nome not in ocultos:
            _gravar_lista_insumos(_CHAVE_INSUMOS_OCULTOS, ocultos + [nome])
    else:
        return {"success": False, "error": f"Matéria-prima '{nome}' não encontrada."}
    frappe.db.commit()
    return {"success": True, "message": f"'{nome}' excluída."}


@endpoint()
def lancar_cotacao(data, insumo, valor, unidade=None, insumo_outro=None, observacao=None, fonte="Manual"):
    """
    Lancamento (upsert) da cotacao de um insumo para uma data especifica:
    se ja existir lancamento para o mesmo insumo+data, atualiza o valor em
    vez de duplicar - cada dia tem no maximo um preco vigente por insumo.
    """
    _exigir_papel("Financeiro", "Produção", "Direção")
    if not data or not insumo or valor in (None, ""):
        return {"success": False, "error": "Data, insumo e valor sao obrigatorios"}

    existente = frappe.get_all("Cotacao Insumo", filters={"insumo": insumo, "data": data}, limit=1)
    if existente:
        doc = frappe.get_doc("Cotacao Insumo", existente[0].name)
    else:
        doc = frappe.new_doc("Cotacao Insumo")
        doc.insumo = insumo
        doc.data = data

    doc.valor = float(valor)
    doc.unidade = unidade
    doc.insumo_outro = insumo_outro
    doc.observacao = observacao
    doc.fonte = fonte
    doc.lancado_por = frappe.utils.get_fullname(frappe.session.user)
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"success": True, "cotacao": doc.name, "valor": doc.valor}


@endpoint()
def get_cotacao_dolar_automatica():
    """
    Busca o dolar comercial em tempo real na AwesomeAPI (publica, gratuita,
    sem chave) e grava/atualiza automaticamente a cotacao do dia com
    fonte=Automatico. Chamada sob demanda ao abrir o painel de cotacoes -
    nao depende de job agendado.
    """
    import requests

    try:
        resp = requests.get("https://economia.awesomeapi.com.br/last/USD-BRL", timeout=6)
        resp.raise_for_status()
        payload = resp.json()
        cotacao = payload.get("USDBRL", {})
        valor = float(cotacao.get("bid"))
    except Exception as e:
        frappe.log_error(title="Falha ao buscar dolar automatico", message=str(e))
        return {"success": False, "error": "Nao foi possivel consultar a cotacao do dolar agora"}

    hoje = frappe.utils.nowdate()
    resultado = lancar_cotacao(
        data=hoje, insumo="Dólar (USD)", valor=valor, unidade="USD",
        observacao="Cotacao comercial (AwesomeAPI)", fonte="Automático"
    )
    resultado["fetched_at"] = frappe.utils.now_datetime().strftime("%H:%M:%S")
    return resultado


def get_website_user_home_page(user):
    """
    Hook (get_website_user_home_page): pra onde qualquer usuario logado vai
    apos autenticar. Sem isso, a home_page publica (a apresentacao, para
    visitantes) tambem virava o destino do login - a pessoa autenticava e
    caia de volta na propria pagina de apresentacao, num loop.
    """
    if user and user != "Guest":
        papeis = set(frappe.get_roles(user))
        outros = {"System Manager", "Direção", *(f"Setor {x}" for x in SETORES_ASSENTO)}
        so_operador = PAPEL_OPERADOR in papeis and not papeis.intersection(outros)
        so_encarregado = PAPEL_ENCARREGADO in papeis and not papeis.intersection(outros)
        if so_encarregado:
            return "diario-obra"
        return "bipar" if so_operador else "painel"
    return None


@endpoint()
def token_csrf():
    """Token CSRF da sessão. As páginas do sistema (Web Page) não recebem o token do desk; sem ele, quem
    também abriu o desk na mesma sessão tem cada gravação recusada com "Solicitação inválida"."""
    if frappe.session.user == "Guest":
        frappe.throw("Entre no sistema.", frappe.PermissionError)
    return {"success": True, "token": frappe.sessions.get_csrf_token()}


@endpoint()
def get_branding():
    """
    Multi-tenant: cada cliente logado ve o nome e a logo da propria empresa
    (Company do ERPNext) no topo do app, em vez de uma marca fixa. Usa o
    campo nativo `company_logo` do doctype Company — sem doctype novo.
    """
    company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")

    company_name = "ERP Precast"
    company_logo = None
    if company and frappe.db.exists("Company", company):
        doc = frappe.get_cached_doc("Company", company)
        company_name = doc.company_name or company
        company_logo = doc.company_logo or None

    papeis = set(frappe.get_roles(frappe.session.user))
    is_direcao = bool(papeis.intersection({"Direção", "System Manager"})) or frappe.session.user == "Administrator"

    return {
        "success": True,
        "company_name": company_name,
        "company_logo": company_logo,
        "user_full_name": frappe.utils.get_fullname(frappe.session.user),
        "is_direcao": is_direcao,
    }

@endpoint()
def get_pieces(obra=None, search=None, status=None):
    filters = {}
    if obra:
        filters['obra'] = obra
    if status:
        filters['status_producao'] = status

    fields = [
        'codigo_peca', 'tag', 'obra', 'cliente', 'produto', 'grupo',
        'secao', 'comprimento_m', 'volume_m3', 'peso_kg', 'fck',
        'cobrimento_cm', 'status_producao', 'fase_numero',
        'prancha_url', 'print_url', 'arquivo_origem',
        'dimensoes_confirmadas', 'aviso_engenharia', 'modified',
        'forma_pista', 'data_programada', 'romaneio',
        'peso_aco_kg', 'folha_prancha', 'fonte_leitura',
        'lote_concreto', 'corridas_aco', 'plano_corte', 'sequencia_montagem', 'data_montagem_prevista'
    ]
    
    pieces = frappe.get_all('Peca Pre-Moldada', filters=filters, fields=fields, order_by='modified desc', limit=5000)
    
    if search:
        s = search.lower()
        pieces = [p for p in pieces if s in str(p.get('codigo_peca', '')).lower() or s in str(p.get('tag', '')).lower()]
        
    return {"success": True, "count": len(pieces), "pieces": pieces}

@endpoint()
def get_obras():
    obras = frappe.get_all('Obra', fields=[
        'codigo_obra', 'nome_obra', 'cliente_nome', 'cidade_uf',
        'fck_padrao', 'status', 'cor_identificacao', 'modified', 'customer'
    ], order_by='modified desc')
    
    # Calculate piece count and weight per obra
    for o in obras:
        cod = o.codigo_obra
        stats = frappe.db.sql("""
            SELECT COUNT(*) as qtd, SUM(peso_kg) as peso_total, SUM(volume_m3) as vol_total
            FROM `tabPeca Pre-Moldada`
            WHERE obra = %s
        """, (cod,), as_dict=True)
        if stats and stats[0]:
            o['total_pecas'] = stats[0].qtd or 0
            o['total_peso'] = round(stats[0].peso_total or 0, 1)
            o['total_volume'] = round(stats[0].vol_total or 0, 2)
        else:
            o['total_pecas'] = 0
            o['total_peso'] = 0
            o['total_volume'] = 0
            
    return {"success": True, "obras": obras}

@endpoint()
def advance_piece_phase(codigo_peca, next_fase=None, forcar=False):
    _exigir_papel("Produção", "Qualidade", "Direção", "Operador")
    if not frappe.db.exists('Peca Pre-Moldada', codigo_peca):
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}

    doc = frappe.get_doc('Peca Pre-Moldada', codigo_peca)
    # "Projetado" não é uma fase de chão de fábrica — é o próprio ato de
    # importar o DWG/DXF no sistema. A peça já nasce na fase 1 (Corte e
    # Dobra); não existe um estado "1. Projetado" separado pra bipar.
    fases = [
        (1, "1. Corte e Dobra"),
        (2, "2. Armação Pronta"),
        (3, "3. Forma e Embutidos"),
        (4, "4. Concretado"),
        (5, "5. Curado / Desmoldado"),
        (6, "6. Pátio / Liberado CQ"),
        (7, "7. Expedido"),
        (8, "8. Montado na Obra")
    ]
    curr_fase = doc.fase_numero or 1
    from frappe.precast_rosto import fases_permitidas, SETORES_PRODUCAO
    permitidas = fases_permitidas(frappe.session.user)
    if permitidas is not None and curr_fase not in permitidas:
        return {"success": False, "error": f"Esta peça está em {SETORES_PRODUCAO[curr_fase - 1]}. O seu cadastro libera só: "
                f"{', '.join(SETORES_PRODUCAO[f - 1] for f in sorted(permitidas))}."}
    from frappe.precast_sst import bloqueio_por_treinamento
    sem_treinamento = bloqueio_por_treinamento(frappe.session.user, curr_fase) if permitidas is not None else None
    if sem_treinamento:
        return {"success": False, "bloqueado_treinamento": True, "error": sem_treinamento}
    if next_fase:
        new_fase = int(next_fase)
    else:
        new_fase = min(8, curr_fase + 1)

    # Trava sequencial: a peça so avanca uma fase de cada vez (bipar/avancar
    # so libera a proxima etapa, nunca pula). Retroceder (corrigir bipagem
    # errada) e sempre permitido - e revogavel a qualquer momento. Pular pra
    # frente exige forcar=True explicito, e fica registrado no historico da
    # peca para auditoria.
    if new_fase > curr_fase + 1 and not forcar:
        fase_esperada = next((nome for num, nome in fases if num == curr_fase + 1), None)
        return {
            "success": False,
            "bloqueado_sequencia": True,
            "fase_atual": curr_fase,
            "fase_esperada_numero": curr_fase + 1,
            "error": f"Peça ainda não passou pela fase anterior ({fase_esperada}). "
                     f"Bipe as fases em ordem, ou confirme forçar o avanço se tiver certeza."
        }

    fase_nome = next((nome for num, nome in fases if num == new_fase), "1. Corte e Dobra")

    # Controle tecnologico do concreto (NBR 9062): desformar (fase 5) exige
    # um corpo de prova aprovado com fck igual ou acima do exigido pela
    # peca. Sem isso, a desforma fica bloqueada mesmo sequencialmente certa.
    if new_fase >= 5 and curr_fase < 5 and not forcar:
        from frappe.precast_patio import desforma_liberada
        aprovado_cp, explicacao_cp = desforma_liberada(codigo_peca, doc.fck)
        if not aprovado_cp:
            return {
                "success": False,
                "bloqueado_fck": True,
                "error": f"Desforma bloqueada: {explicacao_cp}."
            }

    if new_fase > curr_fase + 1 and forcar:
        try:
            doc.add_comment('Info', f"Fase forçada de {curr_fase} para {new_fase} por {frappe.session.user}, pulando etapa(s) intermediária(s).")
        except Exception:
            pass

    doc.fase_numero = new_fase
    doc.status_producao = fase_nome
    doc.save(ignore_permissions=True)

    # Historico de fases (auditoria + base pro OEE de pista - melhoria 9).
    try:
        frappe.get_doc({
            "doctype": "Fase Historico", "codigo_peca": codigo_peca,
            "forma_pista": doc.forma_pista, "fase_anterior": curr_fase, "fase_nova": new_fase,
            "data_hora": frappe.utils.now_datetime(), "usuario": frappe.session.user,
        }).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(title="Falha ao gravar historico de fase", message=str(e))

    if new_fase >= 5 and curr_fase < 5:
        from frappe.precast_patio import peca_desmoldada
        peca_desmoldada(codigo_peca)    # a forma ganha um giro e fica livre se esvaziou

    frappe.db.commit()

    return {"success": True, "codigo_peca": codigo_peca, "fase_numero": new_fase, "status_producao": fase_nome}


_NOMES_FASES = {1: "1. Corte e Dobra", 2: "2. Armação Pronta", 3: "3. Forma e Embutidos", 4: "4. Concretado", 5: "5. Curado / Desmoldado",
                6: "6. Pátio / Liberado CQ", 7: "7. Expedido", 8: "8. Montado na Obra"}


@endpoint()
def voltar_fase_peca(codigo_peca, fase_destino, motivo=""):
    """Corrige uma bipagem errada: leva a peça de volta para a fase escolhida. Fica no histórico com quem fez e por quê.
    Só gestão (Direção, Produção, Qualidade): o operador por rosto não volta fases."""
    _exigir_papel("Direção", "Produção", "Qualidade")
    if not frappe.db.exists('Peca Pre-Moldada', codigo_peca):
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}
    try:
        destino = int(fase_destino)
    except (TypeError, ValueError):
        return {"success": False, "error": "Escolha a fase de destino."}
    doc = frappe.get_doc('Peca Pre-Moldada', codigo_peca)
    atual = doc.fase_numero or 1
    if destino not in _NOMES_FASES or destino >= atual:
        return {"success": False, "error": f"A peça está em {_NOMES_FASES[atual]}. Escolha uma fase anterior."}
    if doc.get("romaneio"):
        return {"success": False, "error": f"A peça está no romaneio {doc.romaneio}. Tire a peça do romaneio antes de voltar a fase."}
    if doc.get("faturado_montagem"):
        return {"success": False, "error": "A peça já foi faturada na medição de montagem. Não dá para voltar a fase."}

    doc.fase_numero = destino
    doc.status_producao = _NOMES_FASES[destino]
    doc.save(ignore_permissions=True)
    try:
        doc.add_comment('Info', f"Fase corrigida de {_NOMES_FASES[atual]} para {_NOMES_FASES[destino]} por {frappe.session.user}."
                        + (f" Motivo: {str(motivo).strip()[:300]}" if str(motivo or "").strip() else ""))
        frappe.get_doc({"doctype": "Fase Historico", "codigo_peca": codigo_peca, "forma_pista": doc.forma_pista, "fase_anterior": atual,
                        "fase_nova": destino, "data_hora": frappe.utils.now_datetime(), "usuario": frappe.session.user}).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(title="Falha ao gravar o histórico da correção de fase", message=str(e))
    frappe.db.commit()
    return {"success": True, "codigo_peca": codigo_peca, "fase_numero": destino, "status_producao": _NOMES_FASES[destino]}


def _tem_corpo_de_prova_aprovado(codigo_peca, fck_exigido):
    """Melhoria 2: checklist de concretagem aprovado com fck do CP >= exigido."""
    checklists = frappe.get_all(
        "Checklist Qualidade",
        filters={"codigo_peca": codigo_peca, "aprovado": 1},
        fields=["fck_corpo_prova"],
    )
    if not checklists:
        return False

    def _num(valor):
        try:
            return float(str(valor).upper().replace("MPA", "").strip())
        except (TypeError, ValueError):
            return None

    exigido = _num(fck_exigido) or 0
    for c in checklists:
        obtido = _num(c.fck_corpo_prova)
        if obtido is not None and obtido >= exigido:
            return True
    return False

QR_PAYLOAD_PREFIX = "PECA:"
QR_DIR = "/home/frappe/frappe-bench/sites/frontend/public/files/qrcodes"

def _qr_payload(codigo_peca):
    return f"{QR_PAYLOAD_PREFIX}{codigo_peca}"

@endpoint()
def get_or_generate_qrcode(codigo_peca):
    import qrcode

    if not frappe.db.exists('Peca Pre-Moldada', codigo_peca):
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}

    os.makedirs(QR_DIR, exist_ok=True)
    fname = f"{codigo_peca}.png"
    fpath = os.path.join(QR_DIR, fname)
    payload = _qr_payload(codigo_peca)

    if not os.path.exists(fpath):
        img = qrcode.make(payload, box_size=10, border=2)
        img.save(fpath)

    doc = frappe.db.get_value('Peca Pre-Moldada', codigo_peca, ['obra', 'fck'], as_dict=True)
    obra = frappe.db.get_value('Obra', doc.obra, ['nome_obra', 'fck_padrao'], as_dict=True) if doc.obra else None
    fck = doc.fck or (obra and obra.fck_padrao) or 0
    from urllib.parse import quote
    return {"success": True, "qr_url": f"/files/qrcodes/{quote(fname)}", "payload": payload,
            "obra": f"{doc.obra} | {obra.nome_obra}" if obra else (doc.obra or ""), "fck": fck}

@endpoint()
def get_detalhe_prancha(codigo_peca):
    """Aço da peça segundo a lista de materiais da prancha: ferros (posição, bitola, quantidade, comprimento) e resumo."""
    if not frappe.db.exists('Peca Pre-Moldada', codigo_peca):
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}
    d = frappe.db.get_value('Peca Pre-Moldada', codigo_peca, ['lista_ferros', 'peso_aco_kg', 'volume_m3', 'taxa_aco_kg_m3', 'folha_prancha', 'titulo_prancha'], as_dict=True)
    try:
        ferros = json.loads(d.lista_ferros or '[]')
    except ValueError:
        ferros = []
    return {"success": True, "ferros": ferros, "aco_kg": d.peso_aco_kg, "volume_m3": d.volume_m3, "taxa_aco": d.taxa_aco_kg_m3,
            "folha": d.folha_prancha, "titulo": d.titulo_prancha}


@endpoint()
def get_piece_for_scan(codigo):
    if not codigo:
        return {"success": False, "error": "Código não informado"}
    codigo = codigo.strip()
    veio_do_qr = codigo.upper().startswith(QR_PAYLOAD_PREFIX)
    if veio_do_qr:
        codigo = codigo[len(QR_PAYLOAD_PREFIX):]
    else:
        # Digitado à mão: se mais de uma obra tem uma peça com esse código, a pessoa escolhe a obra.
        iguais = frappe.get_all('Peca Pre-Moldada', filters=[['tag', '=', codigo]], fields=['name', 'obra', 'tag'])
        iguais += [p for p in frappe.get_all('Peca Pre-Moldada', filters=[['name', '=', codigo]], fields=['name', 'obra', 'tag']) if p.name not in {i.name for i in iguais}]
        if len({i.obra for i in iguais}) > 1:
            return {"success": False, "ambiguo": True, "error": f"O código {codigo} existe em mais de uma obra. Escolha a obra.",
                    "opcoes": [{"obra": i.obra, "codigo": i.name} for i in sorted(iguais, key=lambda x: x.obra or "")]}

    if not frappe.db.exists('Peca Pre-Moldada', codigo):
        return {"success": False, "error": f"Peça '{codigo}' não encontrada. Confira o código ou bipe novamente."}

    doc = frappe.get_doc('Peca Pre-Moldada', codigo)
    checklist = frappe.get_all('Checklist Qualidade',
        filters={'codigo_peca': codigo},
        fields=['name', 'etapa', 'aprovado', 'inspetor', 'data_inspecao', 'observacoes'],
        order_by='data_inspecao desc'
    )

    return {
        "success": True,
        "peca": {
            "codigo_peca": doc.codigo_peca, "tag": doc.tag, "obra": doc.obra,
            "produto": doc.produto, "secao": doc.secao, "comprimento_m": doc.comprimento_m,
            "peso_kg": doc.peso_kg, "fck": doc.fck,
            "prancha_url": doc.prancha_url, "print_url": doc.print_url, "folha_prancha": doc.get("folha_prancha"),
            "fase_numero": doc.fase_numero, "status_producao": doc.status_producao,
            "forma_pista": doc.forma_pista, "data_programada": doc.data_programada,
            "aviso_engenharia": doc.aviso_engenharia
        },
        "checklist": checklist
    }

@endpoint()
def submit_checklist(codigo_peca, etapa, aprovado=1, inspetor=None, observacoes=None,
                      caminhao_betoneira=None, lote_concreto=None, fck_corpo_prova=None):
    _exigir_papel("Produção", "Qualidade", "Direção")
    if not frappe.db.exists('Peca Pre-Moldada', codigo_peca):
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}

    aprovado_bool = str(aprovado).strip().lower() in ('1', 'true', 'on', 'yes')

    doc = frappe.get_doc({
        "doctype": "Checklist Qualidade",
        "codigo_peca": codigo_peca,
        "etapa": etapa,
        "aprovado": 1 if aprovado_bool else 0,
        "inspetor": inspetor or frappe.utils.get_fullname(frappe.session.user),
        "data_inspecao": frappe.utils.now_datetime(),
        "observacoes": observacoes,
        "caminhao_betoneira": caminhao_betoneira,
        "lote_concreto": lote_concreto,
        "fck_corpo_prova": fck_corpo_prova
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"success": True, "name": doc.name, "message": "Checklist registrado com sucesso"}

@endpoint()
def get_checklists(limit=200):
    _exigir_papel("Produção", "Qualidade", "Direção")
    rows = frappe.get_all('Checklist Qualidade',
        fields=['name', 'codigo_peca', 'etapa', 'aprovado', 'inspetor', 'data_inspecao', 'observacoes', 'fck_corpo_prova'],
        order_by='data_inspecao desc', limit=int(limit))
    return {"success": True, "checklists": rows}

# ---- Rastreabilidade: lote de concreto, corpos de prova, certificados do aço e RG da peça (precast_qualidade.py)

@endpoint()
def get_rastreabilidade():
    from frappe.precast_qualidade import resumo
    return resumo()


@endpoint()
def registrar_lote_concreto(codigo, fck_especificado, data_concretagem=None, usina=None, traco=None, slump_cm=None,
                            temperatura_c=None, volume_m3=None, nota_fiscal=None, observacoes=None):
    _exigir_papel("Qualidade", "Produção", "Direção")
    from frappe.precast_qualidade import registrar_lote
    return registrar_lote(codigo, fck_especificado, data_concretagem, usina, traco, slump_cm, temperatura_c,
                          volume_m3, nota_fiscal, observacoes)


@endpoint()
def registrar_corpo_prova(lote, idade_dias, fck_obtido, data_ruptura=None, carga_kn=None):
    _exigir_papel("Qualidade", "Direção")
    from frappe.precast_qualidade import registrar_corpo_de_prova
    return registrar_corpo_de_prova(lote, idade_dias, fck_obtido, data_ruptura, carga_kn)


@endpoint()
def vincular_lote_pecas(lote, pecas):
    _exigir_papel("Qualidade", "Produção", "Direção")
    from frappe.precast_qualidade import vincular_lote
    return vincular_lote(lote, pecas)


@endpoint()
def registrar_certificado_aco(corrida, bitola_mm, fabricante=None, norma=None, data_recebimento=None,
                              nota_fiscal=None, certificado_anexo=None):
    _exigir_papel("Qualidade", "Produção", "Direção")
    from frappe.precast_qualidade import registrar_certificado
    return registrar_certificado(corrida, bitola_mm, fabricante, norma, data_recebimento, nota_fiscal, certificado_anexo)


@endpoint()
def vincular_corridas_pecas(pecas, corridas):
    _exigir_papel("Qualidade", "Produção", "Direção")
    from frappe.precast_qualidade import vincular_corridas
    return vincular_corridas(pecas, corridas)


@endpoint()
def get_rg_peca(codigo_peca):
    from frappe.precast_qualidade import rg_da_peca
    return rg_da_peca(codigo_peca)


@endpoint()
def config_rastreabilidade(exigir_rg_expedicao=None):
    """Liga ou desliga a exigência do RG completo para a peça entrar num romaneio."""
    from frappe.precast_qualidade import definir_exigir_rg, exigir_rg_para_expedir
    if exigir_rg_expedicao is not None:
        _exigir_papel("Direção", "Qualidade")
        definir_exigir_rg(str(exigir_rg_expedicao).lower() in ("1", "true", "yes"))
    return {"success": True, "exigir_rg_expedicao": exigir_rg_para_expedir()}


# ---- Corte e dobra do aço (precast_corte.py)

@endpoint()
def config_corte(barra_m=None, traspasse_diametros=None, retalho_minimo_m=None):
    from frappe.precast_corte import configuracao
    if any(v not in (None, "") for v in (barra_m, traspasse_diametros, retalho_minimo_m)):
        _exigir_papel("Produção", "Direção")
    return configuracao(barra_m, traspasse_diametros, retalho_minimo_m)


@endpoint()
def pecas_para_corte(obra):
    from frappe.precast_corte import pecas_para_corte as _pecas
    return {"success": True, "pecas": _pecas(obra)}


@endpoint()
def gerar_plano_corte(obra, pecas=None, barra_m=None):
    _exigir_papel("Produção", "Direção")
    from frappe.precast_corte import gerar
    return gerar(obra, pecas, barra_m)


@endpoint()
def listar_planos_corte(obra):
    from frappe.precast_corte import listar
    return {"success": True, "planos": listar(obra)}


@endpoint()
def get_plano_corte(plano):
    from frappe.precast_corte import abrir
    return abrir(plano)


@endpoint()
def mudar_status_plano_corte(plano, status):
    _exigir_papel("Produção", "Direção")
    from frappe.precast_corte import mudar_status
    return mudar_status(plano, status)


# ---- Logística e montagem (precast_montagem.py)

@endpoint()
def definir_sequencia_montagem(obra, pecas=None):
    _exigir_papel("Logística", "Produção", "Direção")
    from frappe.precast_montagem import definir_sequencia
    return definir_sequencia(obra, pecas)


@endpoint()
def planejar_cargas(obra, pecas=None, balanco_m=None):
    from frappe.precast_montagem import planejar_cargas as _planejar
    return _planejar(obra, pecas, balanco_m)


@endpoint()
def aplicar_plano_cargas(obra, data_expedicao, cargas):
    _exigir_papel("Logística", "Produção", "Direção")
    from frappe.precast_montagem import aplicar_cargas
    return aplicar_cargas(obra, data_expedicao, cargas)


@endpoint()
def salvar_equipamento_icamento(nome, capacidade_max_kg, tipo=None, tabela_carga=None, fator_seguranca=None):
    _exigir_papel("Logística", "Direção")
    from frappe.precast_montagem import salvar_equipamento
    return salvar_equipamento(nome, tipo, capacidade_max_kg, tabela_carga, fator_seguranca)


@endpoint()
def listar_equipamentos_icamento():
    from frappe.precast_montagem import listar_equipamentos
    return {"success": True, "equipamentos": listar_equipamentos()}


@endpoint()
def excluir_equipamento_icamento(nome):
    _exigir_papel("Logística", "Direção")
    from frappe.precast_montagem import excluir_equipamento
    return excluir_equipamento(nome)


@endpoint()
def plano_icamento(obra, equipamento, raio_m):
    from frappe.precast_montagem import plano_icamento as _plano
    return _plano(obra, equipamento, raio_m)


@endpoint()
def cronograma_montagem(obra, data_inicio=None, pecas_por_dia=None, aplicar=False):
    if data_inicio and str(aplicar).lower() in ("1", "true", "sim"):
        _exigir_papel("Logística", "Produção", "Direção")
    from frappe.precast_montagem import cronograma
    return cronograma(obra, data_inicio, pecas_por_dia, aplicar)


# ---- Suprimentos e financeiro (precast_compras.py)

@endpoint()
def config_compras(alcada_producao=None, prazo_dias=None):
    from frappe.precast_compras import configuracao
    if alcada_producao not in (None, "") or prazo_dias not in (None, ""):
        _exigir_papel("Direção", "Financeiro")
    return configuracao(alcada_producao, prazo_dias)


@endpoint()
def necessidade_materiais(obra=None):
    from frappe.precast_compras import necessidade
    return necessidade(obra)


@endpoint()
def solicitar_compra(item, categoria, quantidade, preco_unitario, fornecedor, obra=None, bitola_mm=None, unidade="kg", prazo_dias=None, observacoes=None):
    _exigir_papel("Produção", "Financeiro", "Direção")
    from frappe.precast_compras import solicitar
    return solicitar(item, categoria, quantidade, preco_unitario, fornecedor, obra, bitola_mm, unidade, prazo_dias, observacoes)


@endpoint()
def aprovar_compra(pedido):
    from frappe.precast_compras import aprovar, quem_aprova, _pedido
    p = _pedido(pedido)
    if p:
        _exigir_papel(*quem_aprova(float(p.valor_total or 0)))     # a alçada: valor maior só a Direção aprova
    return aprovar(pedido)


@endpoint()
def cancelar_compra(pedido):
    _exigir_papel("Produção", "Financeiro", "Direção")
    from frappe.precast_compras import cancelar
    return cancelar(pedido)


@endpoint()
def receber_compra(pedido, corrida=None, nota_fiscal=None, vencimento=None, data_recebimento=None):
    _exigir_papel("Produção", "Logística", "Financeiro", "Direção")
    from frappe.precast_compras import receber
    return receber(pedido, corrida, nota_fiscal, vencimento, data_recebimento)


@endpoint()
def listar_pedidos_compra(obra=None, status=None):
    from frappe.precast_compras import listar_pedidos
    return {"success": True, "pedidos": listar_pedidos(obra, status)}


@endpoint()
def listar_titulos_pagar(status=None):
    _exigir_papel("Financeiro", "Direção")
    from frappe.precast_compras import listar_titulos
    return {"success": True, "titulos": listar_titulos(status)}


@endpoint()
def pagar_titulo(titulo, data=None):
    _exigir_papel("Financeiro", "Direção")
    from frappe.precast_compras import pagar
    return pagar(titulo, data)


@endpoint()
def fluxo_caixa_projetado(semanas=8):
    _exigir_papel("Financeiro", "Direção")
    from frappe.precast_compras import fluxo_caixa
    return fluxo_caixa(semanas)


@endpoint()
def orcado_realizado_obras():
    _exigir_papel("Financeiro", "Direção", "Produção")
    from frappe.precast_compras import orcado_realizado
    return {"success": True, "obras": orcado_realizado()}


@endpoint()
def saldo_aco_corridas():
    from frappe.precast_compras import saldo_aco
    linhas, por_bitola = saldo_aco()
    return {"success": True, "corridas": linhas, "por_bitola": {str(k): round(v, 1) for k, v in por_bitola.items()}}


# ---- Segurança do trabalho, manutenção de equipamentos e LGPD (precast_sst.py)

@endpoint()
def painel_seguranca():
    _exigir_papel("Direção", "Produção", "Qualidade", "RH")
    from frappe.precast_sst import painel_sst
    return painel_sst()


@endpoint()
def registrar_sst(tipo, pessoa, documento=None, data_emissao=None, validade=None, observacoes=None, funcao=None, obra=None, cat=False, dias_afastamento=None):
    _exigir_papel("Direção", "Produção", "Qualidade", "RH")
    from frappe.precast_sst import registrar_sst as _registrar
    return _registrar(tipo, pessoa, documento, data_emissao, validade, observacoes, funcao, obra, cat, dias_afastamento)


@endpoint()
def listar_registros_sst(tipo=None, pessoa=None):
    _exigir_papel("Direção", "Produção", "Qualidade", "RH")
    from frappe.precast_sst import listar_sst
    return {"success": True, "registros": listar_sst(tipo, pessoa)}


@endpoint()
def config_seguranca(exigir_treinamento=None):
    from frappe.precast_sst import definir_exigir_treinamento, exigir_treinamento as _exigir
    if exigir_treinamento is not None:
        _exigir_papel("Direção")
        definir_exigir_treinamento(str(exigir_treinamento).lower() in ("1", "true", "sim"))
    return {"success": True, "exigir_treinamento": _exigir()}


@endpoint()
def salvar_ativo_operacional(nome, tipo, unidade_medida="Horas", leitura_atual=0, intervalo_manutencao=None, vencimento_documento=None, identificacao=None):
    _exigir_papel("Logística", "Produção", "Direção")
    from frappe.precast_sst import salvar_ativo
    return salvar_ativo(nome, tipo, unidade_medida, leitura_atual, intervalo_manutencao, vencimento_documento, identificacao)


@endpoint()
def listar_ativos_operacionais():
    from frappe.precast_sst import listar_ativos
    return {"success": True, "ativos": listar_ativos()}


@endpoint()
def registrar_manutencao_ativo(ativo, tipo, descricao=None, custo=None, leitura=None, data=None):
    _exigir_papel("Logística", "Produção", "Direção")
    from frappe.precast_sst import registrar_manutencao
    return registrar_manutencao(ativo, tipo, descricao, custo, leitura, data)


@endpoint()
def atualizar_leitura_ativo(ativo, leitura):
    _exigir_papel("Logística", "Produção", "Direção")
    from frappe.precast_sst import atualizar_leitura
    return atualizar_leitura(ativo, leitura)


@endpoint()
def historico_manutencao_ativo(ativo):
    from frappe.precast_sst import historico_manutencao
    return {"success": True, "historico": historico_manutencao(ativo)}


@endpoint()
def excluir_ativo_operacional(nome):
    _exigir_papel("Logística", "Direção")
    if not frappe.db.exists("Ativo Operacional", nome):
        return {"success": False, "error": "Equipamento não encontrado."}
    for m in frappe.get_all("Manutencao Ativo", filters={"ativo": nome}, pluck="name"):
        frappe.delete_doc("Manutencao Ativo", m, ignore_permissions=True, force=True)
    frappe.delete_doc("Ativo Operacional", nome, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"success": True}


@endpoint(allow_guest=True)
def termo_lgpd():
    from frappe.precast_sst import termo
    return termo()


@endpoint()
def lgpd_exportar_titular(usuario):
    _exigir_papel("Direção")
    from frappe.precast_sst import exportar_titular
    return exportar_titular(usuario)


@endpoint()
def lgpd_excluir_titular(usuario):
    _exigir_papel("Direção")
    from frappe.precast_sst import excluir_titular
    return excluir_titular(usuario)


# ---- Relatório de peças (precast_relatorios.py)

_PAPEIS_RELATORIO = ("Direção", "Produção", "Qualidade", "Logística", "Comercial", "Financeiro")


@endpoint()
def relatorio_clientes():
    _exigir_papel(*_PAPEIS_RELATORIO)
    from frappe.precast_relatorios import clientes
    return {"success": True, "clientes": clientes()}


@endpoint()
def relatorio_lista_pecas(cliente=None, obra=None):
    _exigir_papel(*_PAPEIS_RELATORIO)
    from frappe.precast_relatorios import pecas_da_selecao
    return {"success": True, "pecas": pecas_da_selecao(cliente, obra)}


@endpoint()
def relatorio_pecas(codigos, secoes=None):
    _exigir_papel(*_PAPEIS_RELATORIO)
    from frappe.precast_relatorios import relatorio
    return relatorio(codigos, secoes)


@endpoint()
def get_transportadoras():
    return {"success": True, "transportadoras": frappe.get_all('Transportadora',
        fields=['nome', 'cnpj', 'telefone'], order_by='nome asc')}

@endpoint()
def create_transportadora(nome, cnpj=None, telefone=None):
    _exigir_papel("Logística", "Direção")
    if not nome:
        return {"success": False, "error": "Nome é obrigatório"}
    nome = nome.strip()
    if frappe.db.exists('Transportadora', nome):
        return {"success": False, "error": f"Transportadora '{nome}' já existe."}
    frappe.get_doc({"doctype": "Transportadora", "nome": nome, "cnpj": cnpj, "telefone": telefone}).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "message": "Transportadora cadastrada"}

@endpoint()
def delete_transportadora(nome):
    _exigir_papel("Logística", "Direção")
    if not frappe.db.exists('Transportadora', nome):
        return {"success": False, "error": "Transportadora não encontrada"}
    frappe.delete_doc('Transportadora', nome, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"success": True, "message": "Transportadora excluída"}

@endpoint()
def get_motoristas():
    return {"success": True, "motoristas": frappe.get_all('Motorista',
        fields=['nome', 'cnh', 'telefone', 'transportadora', 'avaliacao'], order_by='nome asc')}

@endpoint()
def create_motorista(nome, cnh=None, telefone=None, transportadora=None, avaliacao=5):
    _exigir_papel("Logística", "Direção")
    if not nome:
        return {"success": False, "error": "Nome é obrigatório"}
    nome = nome.strip()
    if frappe.db.exists('Motorista', nome):
        return {"success": False, "error": f"Motorista '{nome}' já existe."}
    frappe.get_doc({"doctype": "Motorista", "nome": nome, "cnh": cnh, "telefone": telefone,
                     "transportadora": transportadora, "avaliacao": avaliacao}).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "message": "Motorista cadastrado"}

@endpoint()
def delete_motorista(nome):
    _exigir_papel("Logística", "Direção")
    if not frappe.db.exists('Motorista', nome):
        return {"success": False, "error": "Motorista não encontrado"}
    frappe.delete_doc('Motorista', nome, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"success": True, "message": "Motorista excluído"}

@endpoint()
def get_caminhoes():
    return {"success": True, "caminhoes": frappe.get_all('Caminhao',
        fields=['placa', 'transportadora', 'capacidade_kg', 'motorista_padrao', 'comprimento_m'], order_by='placa asc')}

@endpoint()
def create_caminhao(placa, capacidade_kg, transportadora=None, motorista_padrao=None, comprimento_m=None):
    _exigir_papel("Logística", "Direção")
    if not placa or not capacidade_kg:
        return {"success": False, "error": "Placa e capacidade são obrigatórios"}
    placa = placa.strip().upper()
    if frappe.db.exists('Caminhao', placa):
        return {"success": False, "error": f"Caminhão '{placa}' já existe."}
    frappe.get_doc({"doctype": "Caminhao", "placa": placa, "capacidade_kg": capacidade_kg,
                     "transportadora": transportadora, "motorista_padrao": motorista_padrao,
                     "comprimento_m": float(comprimento_m) if comprimento_m not in (None, "") else None}).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "message": "Caminhão cadastrado"}

@endpoint()
def delete_caminhao(placa):
    _exigir_papel("Logística", "Direção")
    if not frappe.db.exists('Caminhao', placa):
        return {"success": False, "error": "Caminhão não encontrado"}
    frappe.delete_doc('Caminhao', placa, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"success": True, "message": "Caminhão excluído"}

@endpoint()
def get_pecas_liberadas_expedicao(obra=None):
    # Peças na fase 6 (Pátio / Liberado CQ) e sem romaneio ainda — únicas
    # aptas a entrar num romaneio novo.
    filters = {'fase_numero': 6, 'romaneio': ['in', ['', None]]}
    if obra:
        filters['obra'] = obra
    fields = ['codigo_peca', 'tag', 'obra', 'produto', 'peso_kg']
    return {"success": True, "pecas": frappe.get_all('Peca Pre-Moldada', filters=filters, fields=fields, order_by='obra asc')}

@endpoint()
def get_romaneios():
    romaneios = frappe.get_all('Romaneio', fields=[
        'codigo', 'obra', 'caminhao', 'motorista', 'data_expedicao', 'status', 'peso_total_kg', 'ordem_carga'
    ], order_by='data_expedicao desc')
    for r in romaneios:
        r['pecas'] = frappe.get_all('Peca Pre-Moldada', filters={'romaneio': r.codigo},
                                     fields=['codigo_peca', 'tag', 'peso_kg'])
    return {"success": True, "romaneios": romaneios}

@endpoint()
def create_romaneio(obra, caminhao, data_expedicao, pecas, motorista=None):
    _exigir_papel("Logística", "Produção", "Direção")
    if isinstance(pecas, str):
        pecas = json.loads(pecas)
    if not pecas:
        return {"success": False, "error": "Selecione ao menos uma peça para o romaneio"}
    if not frappe.db.exists('Caminhao', caminhao):
        return {"success": False, "error": "Caminhão não encontrado"}

    # Trava sequencial na entrada da Logística: só entra no romaneio quem já
    # passou pela fase 6 (Pátio / Liberado CQ). Bater o QR na expedição não
    # pode liberar peça que ainda não passou pelas fases de fabricação.
    fora_de_sequencia = []
    for cod in pecas:
        fase_atual = frappe.db.get_value('Peca Pre-Moldada', cod, 'fase_numero') or 1
        if fase_atual < 6:
            fora_de_sequencia.append(f"{cod} (fase {fase_atual})")
    if fora_de_sequencia:
        return {
            "success": False,
            "error": "Peça(s) fora de sequência — ainda não liberadas do pátio (fase 6): " + ", ".join(fora_de_sequencia)
        }

    # Melhoria 7: peça com RNC aberta (não conformidade ainda não aprovada)
    # não pode ser expedida.
    com_rnc = [cod for cod in pecas if _tem_rnc_aberta(cod)]
    if com_rnc:
        return {
            "success": False,
            "error": "Peça(s) com não conformidade aberta — não podem ser expedidas até o reparo ser aprovado: " + ", ".join(com_rnc)
        }

    from frappe.precast_qualidade import exigir_rg_para_expedir, pecas_sem_rg_completo
    if exigir_rg_para_expedir():
        sem_rg = pecas_sem_rg_completo(pecas)
        if sem_rg:
            return {"success": False, "error": "RG da peça incompleto (a exigência está ligada na aba Qualidade): " + "; ".join(sem_rg[:5])}

    caminhao_doc = frappe.get_doc('Caminhao', caminhao)
    peso_total = 0.0
    for cod in pecas:
        peso_total += frappe.db.get_value('Peca Pre-Moldada', cod, 'peso_kg') or 0

    if peso_total > (caminhao_doc.capacidade_kg or 0):
        return {"success": False, "error": f"Peso total ({peso_total:.0f} kg) excede a capacidade do caminhão ({caminhao_doc.capacidade_kg:.0f} kg)."}

    base_codigo = f"ROM-{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}"
    codigo, repeticao = base_codigo, 1
    while frappe.db.exists('Romaneio', codigo):   # dois romaneios no mesmo segundo
        repeticao += 1
        codigo = f"{base_codigo}-{repeticao}"
    romaneio = frappe.get_doc({
        "doctype": "Romaneio", "codigo": codigo, "obra": obra, "caminhao": caminhao,
        "motorista": motorista or caminhao_doc.motorista_padrao, "data_expedicao": data_expedicao,
        "status": "Montando", "peso_total_kg": peso_total
    })
    romaneio.insert(ignore_permissions=True)

    for cod in pecas:
        pdoc = frappe.get_doc('Peca Pre-Moldada', cod)
        pdoc.romaneio = codigo
        pdoc.save(ignore_permissions=True)

    frappe.db.commit()
    return {"success": True, "codigo": codigo, "peso_total_kg": peso_total, "message": "Romaneio montado com sucesso"}

@endpoint()
def despachar_romaneio(codigo):
    _exigir_papel("Logística", "Direção")
    if not frappe.db.exists('Romaneio', codigo):
        return {"success": False, "error": "Romaneio não encontrado"}
    romaneio = frappe.get_doc('Romaneio', codigo)
    romaneio.status = "Despachado"
    romaneio.save(ignore_permissions=True)

    pecas = frappe.get_all('Peca Pre-Moldada', filters={'romaneio': codigo}, fields=['name'])
    for p in pecas:
        # Passa pela mesma trava sequencial de advance_piece_phase - peça só
        # chega em "Expedido" se já estava na fase 6.
        advance_piece_phase(p.name, next_fase=7)

    frappe.db.commit()
    return {"success": True, "codigo": codigo, "pecas_expedidas": len(pecas), "message": "Romaneio despachado"}

@endpoint()
def delete_romaneio(codigo):
    _exigir_papel("Logística", "Direção")
    if not frappe.db.exists('Romaneio', codigo):
        return {"success": False, "error": "Romaneio não encontrado"}
    pecas = frappe.get_all('Peca Pre-Moldada', filters={'romaneio': codigo}, fields=['name'])
    for p in pecas:
        pdoc = frappe.get_doc('Peca Pre-Moldada', p.name)
        pdoc.romaneio = None
        pdoc.save(ignore_permissions=True)
    frappe.delete_doc('Romaneio', codigo, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"success": True, "message": f"Romaneio excluído ({len(pecas)} peças desvinculadas)"}

@endpoint()
def get_pecas_para_montagem(obra=None):
    # Peças expedidas (fase 7), aguardando confirmação de montagem em obra.
    filters = {'fase_numero': 7}
    if obra:
        filters['obra'] = obra
    fields = ['codigo_peca', 'tag', 'obra', 'produto', 'peso_kg', 'romaneio']
    return {"success": True, "pecas": frappe.get_all('Peca Pre-Moldada', filters=filters, fields=fields, order_by='obra asc')}

@endpoint()
def confirm_montagem(codigo_peca):
    return advance_piece_phase(codigo_peca, next_fase=8)

def _default_company():
    """Empresa padrão do site (multi-tenant: cada cliente roda seu próprio site,
    então isso nunca fica fixo em uma empresa específica)."""
    return frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")


# ============================================================
# Assentos por setor + RBAC
# ============================================================
# Cada empresa cadastrada (cada site) tem direito a 1 assento de graca por
# setor (Direção, Produção, Qualidade, Logística, Comercial, Financeiro,
# RH). Uma 2a pessoa no mesmo setor so entra se o limite daquele setor for
# aumentado em "Configuracao Assentos" - hoje isso e manual (o cliente
# contrata o assento extra, o operador libera aqui), sem gateway de
# pagamento automatico ainda.
#
# O login e sempre por e-mail + senha individual (nunca senha
# compartilhada): quem cadastra a empresa cria o primeiro usuario (Direção)
# e a partir dai convida uma pessoa por setor via `convidar_usuario_setor`.

SETORES_ASSENTO = ["Direção", "Produção", "Qualidade", "Logística", "Comercial", "Financeiro", "RH"]

_FIELDNAME_SETOR = {
    "Direção": "direcao", "Produção": "producao", "Qualidade": "qualidade",
    "Logística": "logistica", "Comercial": "comercial", "Financeiro": "financeiro", "RH": "rh",
}


PAPEL_OPERADOR = "Operador de Fábrica"
PAPEL_ENCARREGADO = "Encarregado de Obra"


def _papel_do_setor(setor):
    if setor == "Operador":
        return PAPEL_OPERADOR
    if setor == "Encarregado":
        return PAPEL_ENCARREGADO
    return "Direção" if setor == "Direção" else f"Setor {setor}"


def _garantir_papel(nome, desk_access=0):
    if not frappe.db.exists("Role", nome):
        frappe.get_doc({"doctype": "Role", "role_name": nome, "desk_access": desk_access}).insert(ignore_permissions=True)


def _exigir_papel(*setores_permitidos):
    """Bloqueia a chamada se o usuário logado não tiver o papel de nenhum
    dos setores permitidos (aceita o nome do setor, ex. "Produção" - traduz
    pra o Role real "Setor Produção" internamente). Administrator/System
    Manager sempre passam (conta do operador do sistema, não é um assento
    do cliente)."""
    papeis_usuario = set(frappe.get_roles(frappe.session.user))
    if "System Manager" in papeis_usuario or frappe.session.user == "Administrator":
        return
    papeis_exigidos = {_papel_do_setor(s) for s in setores_permitidos}
    if not papeis_usuario.intersection(papeis_exigidos):
        frappe.throw(
            f"Seu usuário não tem permissão para essa ação (requer: {', '.join(sorted(papeis_exigidos))}).",
            frappe.PermissionError,
        )


def _limite_assentos(setor):
    valor = frappe.db.get_single_value("Configuracao Assentos", f"limite_{_FIELDNAME_SETOR[setor]}")
    return valor or 1


@endpoint()
def listar_assentos():
    """Painel de assentos: quantas pessoas cada setor tem hoje vs. o limite
    contratado. Só Direção/admin vê isso."""
    _exigir_papel("Direção")
    resultado = []
    for setor in SETORES_ASSENTO:
        usados = frappe.get_all("Assento", filters={"setor": setor, "ativo": 1}, fields=["user", "incluido_no_plano"])
        resultado.append({
            "setor": setor, "limite": _limite_assentos(setor), "usados": len(usados),
            "pessoas": [u.user for u in usados],
        })
    com_papel = frappe.get_all("Has Role", filters={"role": PAPEL_OPERADOR, "parenttype": "User"}, pluck="parent")
    operadores = frappe.get_all("User", filters={"name": ["in", com_papel or [""]], "enabled": 1}, pluck="name")
    return {"success": True, "assentos": resultado, "operadores": operadores, "tabela_precos": TABELA_PRECOS_ASSENTO}


@endpoint()
def convidar_usuario_setor(email, full_name, setor):
    """Cria um novo usuário com login próprio (e-mail + senha) num setor.
    Bloqueia se o setor já estiver no limite de assentos contratado -
    nesse caso quem chamou precisa contratar um assento extra antes."""
    _exigir_papel("Direção")

    if setor not in SETORES_ASSENTO:
        return {"success": False, "error": f"Setor inválido. Use um de: {', '.join(SETORES_ASSENTO)}"}

    ativos = frappe.get_all("Assento", filters={"setor": setor, "ativo": 1})
    limite = _limite_assentos(setor)
    if len(ativos) >= limite:
        return {
            "success": False, "requer_upgrade": True,
            "error": f"Limite de assentos do setor {setor} atingido ({limite} contratado(s)). "
                     f"Contrate mais um assento pra adicionar essa pessoa.",
        }

    senha_temporaria = frappe.utils.random_string(10)

    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
        user.enabled = 1
        user.new_password = senha_temporaria
        for papel in [_papel_do_setor(setor), "HR User", "HR Manager"]:
            if papel not in [r.role for r in user.roles] and frappe.db.exists("Role", papel):
                user.append("roles", {"role": papel})
        user.save(ignore_permissions=True)
    else:
        frappe.get_doc({
            "doctype": "User", "email": email, "first_name": full_name or email.split("@")[0],
            "send_welcome_email": 0, "new_password": senha_temporaria,
            "roles": [{"role": _papel_do_setor(setor)}] + [{"role": r} for r in ("HR User", "HR Manager") if frappe.db.exists("Role", r)],
        }).insert(ignore_permissions=True)

    frappe.get_doc({
        "doctype": "Assento", "user": email, "setor": setor, "ativo": 1,
        "incluido_no_plano": 1, "data_ativacao": frappe.utils.now_datetime(),
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    numero = _whatsapp_config()["numero_admin"]
    if numero:
        _enviar_whatsapp(numero, f"🔑 Novo acesso criado\nSetor: {setor}\nE-mail: {email}\nSenha temporária: {senha_temporaria}")

    return {
        "success": True, "user": email, "setor": setor, "senha_temporaria": senha_temporaria,
        "message": "Usuário criado. Envie o e-mail e a senha temporária pra pessoa (ela deve trocar no primeiro acesso).",
    }


@endpoint()
def remover_assento(email):
    """Desativa o usuário e libera a vaga do setor pra outra pessoa."""
    _exigir_papel("Direção")
    if not frappe.db.exists("User", email):
        return {"success": False, "error": "Usuário não encontrado"}

    frappe.db.set_value("User", email, "enabled", 0)
    frappe.db.set_value("Assento", {"user": email, "ativo": 1}, "ativo", 0)
    frappe.db.commit()
    return {"success": True, "message": f"Acesso de {email} desativado e assento liberado."}


# Assentos extras de gestão: R$ 129/mês avulso; pacote de 5 por R$ 490; pacote de 10 por R$ 890.
TABELA_PRECOS_ASSENTO = {"avulso": 129.0, "pacote_5": 490.0, "pacote_10": 890.0}


def _preco_assentos_extra(qtd):
    dez, resto = divmod(int(qtd), 10)
    cinco, avulsos = divmod(resto, 5)
    return (dez * TABELA_PRECOS_ASSENTO["pacote_10"] + cinco * TABELA_PRECOS_ASSENTO["pacote_5"]
            + avulsos * TABELA_PRECOS_ASSENTO["avulso"])


@endpoint()
def criar_operador(email, full_name):
    """Operador de chão de fábrica (bipar QR no celular): login próprio, sem
    limite e sem custo - não ocupa assento de setor. Só acessa o bipar."""
    _exigir_papel("Direção", "Produção")
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return {"success": False, "error": "E-mail inválido."}
    if not (full_name or "").strip():
        return {"success": False, "error": "Informe o nome do operador."}

    _garantir_papel(PAPEL_OPERADOR)
    senha = frappe.utils.random_string(10)
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
        user.enabled = 1
        user.new_password = senha
        if PAPEL_OPERADOR not in [r.role for r in user.roles]:
            user.append("roles", {"role": PAPEL_OPERADOR})
        user.save(ignore_permissions=True)
    else:
        frappe.get_doc({
            "doctype": "User", "email": email, "first_name": full_name.strip(), "user_type": "Website User",
            "send_welcome_email": 0, "new_password": senha, "roles": [{"role": PAPEL_OPERADOR}],
        }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "user": email, "senha_temporaria": senha,
            "message": "Operador criado. Ele entra no celular em /bipar com este e-mail e a senha temporária."}


@endpoint(allow_guest=True)
def rosto_config():
    """Setores e se o primeiro acesso pelo rosto está liberado (tela de entrada do operador, antes do login)."""
    from frappe.precast_rosto import SETORES_PRODUCAO, cadastro_aberto
    return {"success": True, "setores": SETORES_PRODUCAO, "cadastro_aberto": cadastro_aberto()}


@endpoint(allow_guest=True)
def rosto_desafio():
    """Sorteia o desafio de prova de vida (passos na ordem) que a pessoa precisa cumprir diante da câmera."""
    from frappe.precast_rosto import novo_desafio, prova_de_vida_exigida
    if not prova_de_vida_exigida():
        return {"success": True, "exigido": False}
    return {"success": True, "exigido": True, **novo_desafio()}


@endpoint(allow_guest=True)
def rosto_entrar(descritor, nome=None, setor=None, desafio=None, consentimento=False):
    """Entrada do operador pelo rosto: o celular manda só o descritor (a foto não sai do aparelho)."""
    from frappe.precast_rosto import entrar
    return entrar(descritor, nome, setor, desafio, consentimento)


@endpoint()
def listar_rostos():
    _exigir_papel("Direção", "Produção")
    from frappe.precast_rosto import listar, cadastro_aberto, SETORES_PRODUCAO
    from frappe.precast_rosto import prova_de_vida_exigida
    return {"success": True, "operadores": listar(), "setores": SETORES_PRODUCAO, "cadastro_aberto": cadastro_aberto(), "prova_de_vida": prova_de_vida_exigida()}


@endpoint()
def gerir_rosto(usuario=None, acao=None, setores=None, aberto=None):
    """Ações do responsável: setores de cada pessoa, bloquear/liberar, remover e abrir/fechar o primeiro acesso."""
    _exigir_papel("Direção", "Produção")
    from frappe import precast_rosto as R
    if acao == "cadastro_aberto":
        R.definir_cadastro_aberto(str(aberto).lower() in ("1", "true", "yes"))
    elif acao == "setores":
        R.definir_setores(usuario, json.loads(setores) if isinstance(setores, str) else setores)
    elif acao == "prova_de_vida":
        R.definir_prova_de_vida(str(aberto).lower() in ("1", "true", "yes"))
    elif acao == "zerar_tentativas":
        R.zerar_tentativas()
    elif acao in ("bloquear", "liberar"):
        R.definir_ativo(usuario, acao == "liberar")
    elif acao == "remover":
        R.remover(usuario)
    else:
        return {"success": False, "error": "Ação inválida."}
    frappe.db.commit()
    return {"success": True}


@endpoint()
def remover_operador(email):
    _exigir_papel("Direção", "Produção")
    if not frappe.db.exists("Has Role", {"parent": email, "role": PAPEL_OPERADOR}):
        return {"success": False, "error": "Esse usuário não é operador."}
    frappe.db.set_value("User", email, "enabled", 0)
    frappe.db.commit()
    return {"success": True, "message": f"Operador {email} desativado."}


@endpoint()
def solicitar_assento_extra(setor, quantidade=1):
    """Direção pede mais assentos num setor. Registra uma tarefa (ToDo) para o
    Administrator do sistema e avisa por WhatsApp; o limite só sobe quando o
    Administrator aprova em `definir_limite_assento`."""
    _exigir_papel("Direção")
    if setor not in SETORES_ASSENTO:
        return {"success": False, "error": f"Setor inválido. Use um de: {', '.join(SETORES_ASSENTO)}"}
    try:
        qtd = int(quantidade)
    except (TypeError, ValueError):
        return {"success": False, "error": "Quantidade inválida."}
    if not 1 <= qtd <= 50:
        return {"success": False, "error": "Quantidade deve ficar entre 1 e 50."}

    total = _preco_assentos_extra(qtd)
    empresa = _default_company() or frappe.local.site
    resumo = (f"Solicitação de {qtd} assento(s) extra no setor {setor} — {empresa} — "
              f"R$ {total:,.2f}/mês (solicitante: {frappe.session.user})")
    frappe.get_doc({"doctype": "ToDo", "allocated_to": "Administrator", "description": resumo, "priority": "High"}).insert(ignore_permissions=True)
    frappe.db.commit()
    numero = _whatsapp_config()["numero_admin"]
    if numero:
        _enviar_whatsapp(numero, f"🪑 {resumo}")
    return {"success": True, "total_mensal": total,
            "message": f"Solicitação enviada: {qtd} assento(s) em {setor}, R$ {total:,.2f}/mês. O limite sobe assim que for aprovado."}


@endpoint()
def definir_limite_assento(setor, limite):
    """Só o Administrator do sistema (quem vende o plano) altera o limite."""
    if frappe.session.user != "Administrator":
        frappe.throw("Somente o Administrator do sistema pode alterar o limite de assentos.", frappe.PermissionError)
    if setor not in SETORES_ASSENTO:
        return {"success": False, "error": f"Setor inválido. Use um de: {', '.join(SETORES_ASSENTO)}"}
    limite = int(limite)
    if limite < 1:
        return {"success": False, "error": "O limite mínimo é 1."}
    frappe.db.set_single_value("Configuracao Assentos", f"limite_{_FIELDNAME_SETOR[setor]}", limite)
    frappe.db.commit()
    return {"success": True, "setor": setor, "limite": limite}


SECOES_PORTAL = [
    ("progresso", "Progresso da obra", "Barras de produzido e montado, em porcentagem"),
    ("pesos", "Pesos e volumes", "Toneladas e m³ produzidos e montados"),
    ("situacao", "Situação das peças", "Em produção, produzidas, em transporte, entregues e montadas"),
    ("etapas", "Etapas da fábrica", "Gráfico com as peças em cada etapa"),
    ("numeros", "Números da obra", "Quadro de totais (volume, toneladas, entregas e diário)"),
    ("produtos", "Por tipo de peça", "Total, produzidas e montadas de cada tipo"),
    ("pecas", "Lista de peças", "Cada peça com a sua situação"),
    ("entregas", "Entregas", "Romaneios, datas e quem recebeu"),
    ("diario", "Diário de obra", "Texto do que foi feito a cada dia"),
    ("fotos", "Fotos do diário", "Fotos enviadas pelo encarregado"),
    ("dossie", "Dossiê da peça (RG)", "O cliente abre o RG de cada peça: concreto, resistência, certificados do aço, fases e inspeções (sem nomes de pessoas)"),
]


def _config_portal(codigo_obra):
    """O que o cliente desta obra enxerga. Sem configuração salva, ele enxerga tudo."""
    bruto = frappe.defaults.get_global_default(f"portal_cfg:{codigo_obra}")
    try:
        salvo = json.loads(bruto) if bruto else {}
    except ValueError:
        salvo = {}
    secoes = {chave: bool((salvo.get("secoes") or {}).get(chave, chave != "dossie")) for chave, _, _ in SECOES_PORTAL}   # o dossiê só abre quando o dono liga
    return {"ativo": bool(salvo.get("ativo", True)), "secoes": secoes,
            "mensagem": str(salvo.get("mensagem") or ""), "versao": int(salvo.get("versao") or 0)}


def _gravar_config_portal(codigo_obra, cfg):
    frappe.defaults.set_global_default(f"portal_cfg:{codigo_obra}", json.dumps(cfg, ensure_ascii=False))


def _token_portal(codigo_obra):
    """O link muda quando a versão sobe: o token antigo deixa de valer. Versão 0 mantém os links já enviados."""
    chave = frappe.local.conf.get("encryption_key") or frappe.local.site
    versao = _config_portal(codigo_obra)["versao"]
    base = f"portal:{codigo_obra}" if not versao else f"portal:{codigo_obra}:v{versao}"
    return hmac.new(str(chave).encode(), base.encode(), hashlib.sha256).hexdigest()[:24]


@endpoint()
def get_config_portal(codigo_obra):
    _exigir_papel("Direção", "Comercial")
    if not frappe.db.exists("Obra", codigo_obra):
        return {"success": False, "error": "Obra não encontrada"}
    return {"success": True, "config": _config_portal(codigo_obra),
            "secoes": [{"chave": c, "rotulo": r, "descricao": d} for c, r, d in SECOES_PORTAL]}


@endpoint()
def salvar_config_portal(codigo_obra, ativo=True, secoes=None, mensagem=""):
    """Escolhe o que o cliente desta obra vê. Desligar `ativo` fecha o acesso por completo."""
    _exigir_papel("Direção", "Comercial")
    if not frappe.db.exists("Obra", codigo_obra):
        return {"success": False, "error": "Obra não encontrada"}
    if isinstance(secoes, str):
        secoes = json.loads(secoes or "{}")
    atual = _config_portal(codigo_obra)
    novo = {"ativo": str(ativo).lower() in ("1", "true", "yes"), "versao": atual["versao"],
            "mensagem": str(mensagem or "").strip()[:500],
            "secoes": {c: bool((secoes or {}).get(c, atual["secoes"][c])) for c, _, _ in SECOES_PORTAL}}
    _gravar_config_portal(codigo_obra, novo)
    return {"success": True, "config": _config_portal(codigo_obra), "url": _url_portal(codigo_obra)}


@endpoint()
def renovar_link_portal(codigo_obra):
    """Gera um link novo; o que foi enviado antes para o cliente deixa de funcionar."""
    _exigir_papel("Direção", "Comercial")
    if not frappe.db.exists("Obra", codigo_obra):
        return {"success": False, "error": "Obra não encontrada"}
    cfg = _config_portal(codigo_obra)
    cfg["versao"] += 1
    _gravar_config_portal(codigo_obra, cfg)
    return {"success": True, "url": _url_portal(codigo_obra)}


def _url_portal(codigo_obra):
    from urllib.parse import quote
    return f"/portal-obra?obra={quote(codigo_obra)}&t={_token_portal(codigo_obra)}"


@endpoint()
def get_link_portal(codigo_obra):
    """Link do portal do cliente: o código da obra sozinho não abre nada, o
    link leva um token que só quem tem acesso ao sistema consegue gerar."""
    _exigir_papel("Direção", "Comercial", "Produção", "Logística")
    if not frappe.db.exists("Obra", codigo_obra):
        return {"success": False, "error": "Obra não encontrada"}
    return {"success": True, "url": _url_portal(codigo_obra)}


# ============================================================
# Diário de obra e portal do cliente
# ============================================================
_EXT_FOTO = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png"}
MAX_FOTOS_DIARIO = 12
MAX_BYTES_FOTO = 8 * 1024 * 1024


def _obras_do_usuario():
    """None = todas as obras; senão a lista das obras liberadas para o encarregado."""
    papeis = set(frappe.get_roles(frappe.session.user))
    if frappe.session.user == "Administrator" or papeis.intersection({"System Manager", "Direção", "Setor Produção", "Setor Comercial"}):
        return None
    return frappe.get_all("User Permission", filters={"user": frappe.session.user, "allow": "Obra"}, pluck="for_value")


def _exigir_obra(codigo_obra):
    permitidas = _obras_do_usuario()
    if permitidas is not None and codigo_obra not in permitidas:
        frappe.throw("Você não tem acesso a esta obra.", frappe.PermissionError)
    if not frappe.db.exists("Obra", codigo_obra):
        frappe.throw("Obra não encontrada.", frappe.DoesNotExistError)


@endpoint()
def criar_encarregado(email, full_name, obras):
    """Encarregado de obra: login próprio, grátis, sem assento. Só vê o diário das obras liberadas."""
    _exigir_papel("Direção", "Produção")
    if isinstance(obras, str):
        obras = json.loads(obras)
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return {"success": False, "error": "E-mail inválido."}
    if not (full_name or "").strip():
        return {"success": False, "error": "Informe o nome do encarregado."}
    obras = [o for o in (obras or []) if frappe.db.exists("Obra", o)]
    if not obras:
        return {"success": False, "error": "Escolha ao menos uma obra para o encarregado."}

    _garantir_papel(PAPEL_ENCARREGADO)
    senha = frappe.utils.random_string(10)
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
        user.enabled = 1
        user.new_password = senha
        if PAPEL_ENCARREGADO not in [r.role for r in user.roles]:
            user.append("roles", {"role": PAPEL_ENCARREGADO})
        user.save(ignore_permissions=True)
    else:
        frappe.get_doc({
            "doctype": "User", "email": email, "first_name": full_name.strip(), "user_type": "Website User",
            "send_welcome_email": 0, "new_password": senha, "roles": [{"role": PAPEL_ENCARREGADO}],
        }).insert(ignore_permissions=True)
    ja = set(frappe.get_all("User Permission", filters={"user": email, "allow": "Obra"}, pluck="for_value"))
    for obra in obras:
        if obra not in ja:
            frappe.get_doc({"doctype": "User Permission", "user": email, "allow": "Obra", "for_value": obra}).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "user": email, "senha_temporaria": senha,
            "message": "Encarregado criado. Ele entra pelo celular em /diario-obra com este e-mail e a senha temporária."}


@endpoint()
def listar_encarregados():
    _exigir_papel("Direção", "Produção")
    emails = frappe.get_all("Has Role", filters={"role": PAPEL_ENCARREGADO, "parenttype": "User"}, pluck="parent")
    ativos = frappe.get_all("User", filters={"name": ["in", emails or [""]], "enabled": 1}, fields=["name", "full_name"])
    return {"success": True, "encarregados": [
        {"email": u.name, "nome": u.full_name,
         "obras": frappe.get_all("User Permission", filters={"user": u.name, "allow": "Obra"}, pluck="for_value")} for u in ativos]}


@endpoint()
def remover_encarregado(email):
    _exigir_papel("Direção", "Produção")
    if not frappe.db.exists("Has Role", {"parent": email, "role": PAPEL_ENCARREGADO}):
        return {"success": False, "error": "Esse usuário não é encarregado."}
    frappe.db.set_value("User", email, "enabled", 0)
    for nome in frappe.get_all("User Permission", filters={"user": email, "allow": "Obra"}, pluck="name"):
        frappe.delete_doc("User Permission", nome, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"success": True, "message": f"Encarregado {email} desativado."}


@endpoint()
def obras_para_diario():
    _exigir_papel("Direção", "Produção", "Encarregado")
    permitidas = _obras_do_usuario()
    filtros = {} if permitidas is None else {"name": ["in", permitidas or [""]]}
    return {"success": True, "obras": frappe.get_all("Obra", filters=filtros, fields=["codigo_obra", "nome_obra"], order_by="modified desc")}


def _fotos_do_diario(nomes):
    por_registro = {str(n): [] for n in nomes}
    if not nomes:
        return por_registro
    for f in frappe.get_all("File", filters={"attached_to_doctype": "Diario Obra", "attached_to_name": ["in", list(por_registro)]},
                            fields=["attached_to_name", "file_url"], order_by="creation asc"):
        por_registro.setdefault(str(f.attached_to_name), []).append(f.file_url)
    return por_registro


def _listar_diario(codigo_obra, limite=40):
    registros = frappe.get_all("Diario Obra", filters={"obra": codigo_obra},
                               fields=["name", "data", "clima", "autor", "resumo", "creation"], order_by="data desc, creation desc", limit=int(limite))
    fotos = _fotos_do_diario([r.name for r in registros])
    return [{"id": r.name, "data": str(r.data), "clima": r.clima, "autor": r.autor, "resumo": r.resumo, "fotos": fotos.get(str(r.name), [])} for r in registros]


@endpoint()
def listar_diario(obra, limite=40):
    _exigir_papel("Direção", "Produção", "Encarregado")
    _exigir_obra(obra)
    return {"success": True, "registros": _listar_diario(obra, limite)}


@endpoint()
@_restaurar_usuario
def registrar_diario(obra, data, resumo=None, clima=None):
    """Registro do dia pelo encarregado: o que foi feito (texto, ditado pelo celular) e as fotos.
    As fotos chegam como arquivos 'fotos' no mesmo envio."""
    _exigir_papel("Direção", "Produção", "Encarregado")
    _exigir_obra(obra)
    resumo = (resumo or "").strip()
    arquivos = frappe.request.files.getlist("fotos") if frappe.request and frappe.request.files else []
    if not resumo and not arquivos:
        return {"success": False, "error": "Escreva (ou dite) o que foi feito no dia ou anexe ao menos uma foto."}
    if len(arquivos) > MAX_FOTOS_DIARIO:
        return {"success": False, "error": f"Envie no máximo {MAX_FOTOS_DIARIO} fotos por registro."}
    try:
        dia = frappe.utils.getdate(data)
    except Exception:
        return {"success": False, "error": "Data inválida."}
    if dia > frappe.utils.add_days(frappe.utils.getdate(), 1):
        return {"success": False, "error": "A data do diário não pode ser no futuro."}
    if clima and clima not in ("Sol", "Nublado", "Chuva"):
        clima = None

    conteudos = []
    for arq in arquivos:
        bruto = arq.stream.read(MAX_BYTES_FOTO + 1)
        if len(bruto) > MAX_BYTES_FOTO:
            return {"success": False, "error": "Uma das fotos passa de 8 MB. Tire a foto de novo ou reduza o tamanho."}
        ext = next((e for magico, e in _EXT_FOTO.items() if bruto.startswith(magico)), None)
        if ext is None and bruto[:4] == b"RIFF" and bruto[8:12] == b"WEBP":
            ext = "webp"
        if ext is None:
            return {"success": False, "error": "Só são aceitas fotos JPG, PNG ou WEBP."}
        conteudos.append((bruto, ext))

    autor = frappe.utils.get_fullname(frappe.session.user)
    frappe.set_user("Administrator")  # anexar arquivo exige permissão de escrita no documento
    doc = frappe.get_doc({"doctype": "Diario Obra", "obra": obra, "data": dia, "clima": clima or "", "resumo": resumo, "autor": autor})
    doc.insert(ignore_permissions=True)
    for i, (bruto, ext) in enumerate(conteudos):
        frappe.get_doc({
            "doctype": "File", "file_name": f"diario_{uuid_hex()}.{ext}", "content": bruto, "decode": False, "is_private": 0,
            "attached_to_doctype": "Diario Obra", "attached_to_name": str(doc.name),
        }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "id": doc.name, "fotos": len(conteudos), "message": "Diário registrado. O cliente já vê no portal."}


def uuid_hex():
    import uuid
    return uuid.uuid4().hex[:16]


@endpoint()
def excluir_diario(registro):
    _exigir_papel("Direção", "Produção")
    if not frappe.db.exists("Diario Obra", registro):
        return {"success": False, "error": "Registro não encontrado."}
    for nome in frappe.get_all("File", filters={"attached_to_doctype": "Diario Obra", "attached_to_name": str(registro)}, pluck="name"):
        frappe.delete_doc("File", nome, ignore_permissions=True, force=True)
    frappe.delete_doc("Diario Obra", registro, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"success": True, "message": "Registro do diário excluído."}


_ROTULO_FASE = {1: "Corte e dobra", 2: "Armação pronta", 3: "Forma", 4: "Concretada", 5: "Curando", 6: "Pronta no pátio", 7: "Expedida", 8: "Montada"}


def _situacao_da_peca(fase, entregue):
    if fase >= 8:
        return "Montada"
    if entregue:
        return "Entregue"
    if fase == 7:
        return "Expedida"
    if fase == 6:
        return "Produzida"
    return "Em produção"


# ============================================================
# Suporte: Engenheiro João Vitor (assistente virtual, Groq)
# ============================================================
@endpoint()
def perguntar_suporte(mensagem, historico=None, tela=None):
    """Chat de suporte para qualquer usuário logado. O assistente responde pelo manual do produto; quando
    não resolve, pede o WhatsApp do cliente e avisa o responsável (o número do responsável nunca vai
    para o cliente)."""
    if frappe.session.user == "Guest":
        frappe.throw("Entre no sistema para falar com o suporte.", frappe.PermissionError)
    mensagem = (mensagem or "").strip()
    if not mensagem:
        return {"success": False, "error": "Escreva a sua dúvida."}
    if isinstance(historico, str):
        historico = json.loads(historico or "[]")

    from frappe.precast_suporte import conversar, _numero_valido, NOME
    try:
        ctx, dados = conversar(mensagem, historico, tela)
    except Exception as e:
        if isinstance(e, frappe.ValidationError):
            raise
        return {"success": False, "error": f"No momento o {NOME} está indisponível. Tente de novo em instantes."}

    resposta = str(dados.get("resposta") or "").strip() or "Não consegui formular a resposta agora. Pode repetir a pergunta?"
    escalar = bool(dados.get("escalar"))
    encaminhado = False
    numero_cliente = _numero_valido(dados.get("whatsapp_cliente"))

    if escalar and not numero_cliente:
        escalar = False
        resposta += "\n\nPara o nosso engenheiro responsável falar com você, qual é o seu WhatsApp com DDD?"
    if escalar:
        responsavel = _whatsapp_config()["numero_admin"]
        ultimas = [h.get("content", "") for h in (historico or []) if isinstance(h, dict) and h.get("role") == "user"][-3:] + [mensagem]
        texto = (
            f"🛠️ *Suporte — dúvida para o engenheiro*\n"
            f"*Empresa:* {ctx['empresa']}\n*Usuário:* {ctx['usuario']} ({ctx['perfil']})\n*Tela:* {ctx['tela']}\n"
            f"*WhatsApp do cliente:* https://wa.me/{numero_cliente if numero_cliente.startswith('55') else '55' + numero_cliente}\n\n"
            f"*Resumo:* {str(dados.get('resumo') or '-')[:600]}\n\n*Últimas mensagens do cliente:*\n" + "\n".join(f"• {u[:300]}" for u in ultimas)
        )
        encaminhado = bool(responsavel and _enviar_whatsapp(responsavel, texto))
        if not encaminhado:
            frappe.log_error(title="Suporte: não consegui avisar o responsável por WhatsApp", message=texto)
    # o contato do responsável jamais pode aparecer na resposta ao cliente
    protegido = re.sub(r"\D", "", _whatsapp_config()["numero_admin"] or "")
    if protegido and protegido[-9:] in re.sub(r"\D", "", resposta):
        resposta = re.sub(r"[\d()+\-\s]{9,}", "[contato removido]", resposta)
    return {"success": True, "resposta": resposta, "encaminhado": encaminhado}


@endpoint()
def get_dashboard(data_inicio=None, data_fim=None):
    """Dashboard Executivo da página inicial. Os números são o retrato de hoje; o período escolhido vale
    para o gráfico de volume concretado por semana."""
    if frappe.session.user == "Guest":
        frappe.throw("Entre no sistema.", frappe.PermissionError)
    from collections import defaultdict
    from datetime import date as _date, timedelta
    fim = frappe.utils.getdate(data_fim) if data_fim else frappe.utils.getdate()
    inicio = frappe.utils.getdate(data_inicio) if data_inicio else fim - timedelta(days=89)
    if inicio > fim:
        inicio, fim = fim, inicio

    obras = frappe.get_all("Obra", fields=["codigo_obra", "nome_obra", "cliente_nome", "status"], order_by="modified desc")
    pecas = frappe.get_all("Peca Pre-Moldada", fields=["codigo_peca", "obra", "fase_numero", "volume_m3"])
    total = len(pecas)
    por_obra = defaultdict(list)
    for p in pecas:
        por_obra[p.obra].append(p.fase_numero or 1)

    fases = {n: 0 for n in range(1, 9)}
    for p in pecas:
        fases[p.fase_numero or 1] += 1
    chegaram = {n: sum(1 for p in pecas if (p.fase_numero or 1) >= n) for n in range(1, 9)}

    linhas = []
    for o in obras:
        f = por_obra.get(o.codigo_obra, [])
        if not f:
            continue
        produzido = round(sum(1 for x in f if x >= 6) / len(f) * 100)
        montado = round(sum(1 for x in f if x >= 8) / len(f) * 100)
        situacao = "Concluída" if montado == 100 else ("Em montagem" if produzido == 100 else "Em produção")
        linhas.append({"codigo": o.codigo_obra, "cliente": o.cliente_nome or o.nome_obra or "", "progresso": produzido, "montado": montado,
                       "situacao": situacao, "pecas": len(f)})
    em_andamento = [l for l in linhas if l["situacao"] != "Concluída"]

    # volume concretado por semana (fase 4 alcançada no período)
    volumes = {x.codigo_peca: x.volume_m3 or 0 for x in pecas}
    eventos = frappe.get_all("Fase Historico", filters={"fase_nova": 4, "data_hora": ["between", [str(inicio), f"{fim} 23:59:59"]]},
                             fields=["codigo_peca", "data_hora"])
    semanas = {}
    cursor = inicio - timedelta(days=inicio.weekday())
    while cursor <= fim:
        semanas[cursor] = 0.0
        cursor += timedelta(days=7)
    for e in eventos:
        d = frappe.utils.getdate(e.data_hora)
        semanas[d - timedelta(days=d.weekday())] = semanas.get(d - timedelta(days=d.weekday()), 0) + volumes.get(e.codigo_peca, 0)

    em_transporte = fases[7]
    return {
        "success": True,
        "periodo": {"inicio": str(inicio), "fim": str(fim)},
        "kpis": {"obras_em_andamento": len(em_andamento), "pecas_produzidas": sum(1 for p in pecas if (p.fase_numero or 1) >= 6),
                 "em_transporte": em_transporte, "montadas": fases[8], "volume_concreto_m3": round(sum(x.volume_m3 or 0 for x in pecas), 1),
                 "total_pecas": total},
        "etapas": [{"numero": n, "etapa": _ROTULO_FASE[n], "percentual": round(chegaram[n] / total * 100) if total else 0} for n in range(1, 9)],
        "obras": sorted(em_andamento, key=lambda l: l["progresso"], reverse=True)[:8],
        "volume_semanal": [{"semana": str(d), "m3": round(v, 1)} for d, v in sorted(semanas.items())][-16:],
        "por_status": [{"numero": n, "etapa": _ROTULO_FASE[n], "pecas": fases[n]} for n in range(1, 9)],
    }


@endpoint()
def get_fiscal():
    """Cadastro fiscal da empresa e checklist do que falta para emitir nota (a emissão vem depois)."""
    _exigir_papel("Direção", "Financeiro")
    from frappe.precast_fiscal import ler, prontidao, sugestoes, REGIMES, AMBIENTES, UFS, PRODUTOS_FISCAIS
    dados = ler()
    return {"success": True, "dados": dados, "prontidao": prontidao(dados), "sugestoes": sugestoes(),
            "regimes": REGIMES, "ambientes": AMBIENTES, "ufs": UFS, "produtos": PRODUTOS_FISCAIS}


@endpoint()
def salvar_fiscal(dados):
    _exigir_papel("Direção", "Financeiro")
    from frappe.precast_fiscal import gravar, prontidao
    if isinstance(dados, str):
        dados = json.loads(dados)
    gravado = gravar(dados or {})
    return {"success": True, "dados": gravado, "prontidao": prontidao(gravado)}


PRECO_KG_VENDA_PADRAO = 8.0  # R$/kg — provisório até existir uma lista de preços real por produto
FATOR_CIMENTO_KG_POR_M3 = 350.0  # kg de cimento por m³ de concreto, traço típico estrutural

# Taxa de aço por m³ de concreto (kg/m³), já incluindo +30% de perda.
# Fonte: TaxasAco.cs (tabela paramétrica do Eng. Régis), validada contra
# 702 pilares reais produzidos (média 174,7 kg/m³, pilares
# 30x40 reais entre 146,6 e 150,2 kg/m³). Mapeada para as opções do campo
# "produto" de Peca Pre-Moldada; onde o tipo específico não bate
# 1:1 com uma linha da tabela original, usei a variante mais próxima —
# ajuste os valores abaixo se o Eng. Régis quiser outra correspondência:
#   Viga -> "VIGA COBERTURA (genérica)" (família mais comum sem marcação)
#   Escada -> "VIGA ESCADA" (não há uma linha própria de escada na tabela)
#   Bloco de Fundação / Estaca -> sem linha própria, usa o fallback da tabela
TAXA_ACO_KG_M3 = {
    "Pilar": 149.6,
    "Viga": 129.2,
    "Painel de Fechamento": 61.2,
    "Laje Alveolar": 0.0,  # tabela original: laje não passa por cálculo de aço (medida em m²)
    "Bloco de Fundação": 150.0,  # fallback da tabela — sem linha própria
    "Terça": 62.0,
    "Escada": 115.6,
    "Estaca": 150.0,  # fallback da tabela — sem linha própria
    "Outros": 150.0,  # fallback da tabela original (antigo KG_ACO_POR_M3)
}

FATOR_INDIRETOS_PRODUCAO = 0.12  # aditivos, forma, mão de obra indireta
MARGEM_LUCRO_PADRAO = 0.35  # sobre o custo direto+indireto


def _preco_insumo_hoje(nome_insumo):
    """
    Preco do insumo pro orcador automatico: usa a cotacao lancada hoje se
    existir, senao a ultima anterior, senao a media historica sugerida
    (VALORES_SUGERIDOS_HISTORICO) - o mesmo painel de Cotacoes que o
    usuario ja alimenta manualmente, nunca um valor fixo hardcoded.
    """
    hoje = frappe.utils.nowdate()
    do_dia = frappe.get_all("Cotacao Insumo", filters={"insumo": nome_insumo, "data": hoje}, fields=["valor"], limit=1)
    if do_dia:
        return do_dia[0].valor

    anterior = frappe.get_all("Cotacao Insumo", filters={"insumo": nome_insumo, "data": ["<", hoje]},
                               fields=["valor"], order_by="data desc", limit=1)
    if anterior:
        return anterior[0].valor

    sugestao = VALORES_SUGERIDOS_HISTORICO.get(nome_insumo)
    return sugestao["valor"] if sugestao else 0.0


def _produto_padrao(produto_lido):
    """Família do produto a partir do texto lido no desenho ("PILAR / PILAR", "VIGA / BRAÇO", "TERÇA / COBERTURA")."""
    familia = str(produto_lido or "").upper().split("/")[0].strip()
    for chave, nome in (("PILAR", "Pilar"), ("VIGA", "Viga"), ("BRAÇO", "Viga"), ("BRACO", "Viga"), ("FUNDA", "Bloco de Fundação"),
                        ("BLOCO", "Bloco de Fundação"), ("PAINEL", "Painel de Fechamento"), ("PLACA", "Painel de Fechamento"),
                        ("LAJE", "Laje Alveolar"), ("TERÇA", "Terça"), ("TERCA", "Terça"), ("ESCADA", "Escada"), ("ESTACA", "Estaca")):
        if chave in familia:
            return nome
    return "Outros"


def estimar_custo_peca(produto, volume_m3, preco_aco_kg=None, preco_cimento_kg=None, aco_kg_real=None):
    """
    Orcamento automatico por peca: usa a mesma taxa de aco validada (kg de
    aco por m3 de concreto, por tipo de produto) que ja alimenta a
    Requisicao de Compras, e o traco de cimento padrao - precificados pelos
    valores REAIS do dia no painel de Cotacoes, nao um R$/kg fixo.
    """
    volume_m3 = float(volume_m3 or 0)
    if volume_m3 <= 0:
        return {"peso_aco_kg": 0.0, "custo_aco": 0.0, "cimento_kg": 0.0, "custo_cimento": 0.0,
                "custo_estimado": 0.0, "preco_venda_sugerido": 0.0}

    preco_aco_kg = preco_aco_kg if preco_aco_kg is not None else _preco_insumo_hoje("Aço CA-50")
    preco_cimento_kg = preco_cimento_kg if preco_cimento_kg is not None else _preco_insumo_hoje("Cimento CP-II")

    taxa_aco = TAXA_ACO_KG_M3.get(produto, TAXA_ACO_KG_M3["Outros"])
    peso_aco_kg = round(float(aco_kg_real), 2) if aco_kg_real else round(volume_m3 * taxa_aco, 2)
    custo_aco = round(peso_aco_kg * preco_aco_kg, 2)

    cimento_kg = round(volume_m3 * FATOR_CIMENTO_KG_POR_M3, 2)
    custo_cimento = round(cimento_kg * preco_cimento_kg, 2)

    custo_direto = custo_aco + custo_cimento
    custo_estimado = round(custo_direto * (1 + FATOR_INDIRETOS_PRODUCAO), 2)
    preco_venda_sugerido = round(custo_estimado / (1 - MARGEM_LUCRO_PADRAO), 2) if custo_estimado > 0 else 0.0

    return {
        "peso_aco_kg": peso_aco_kg, "custo_aco": custo_aco,
        "cimento_kg": cimento_kg, "custo_cimento": custo_cimento,
        "custo_estimado": custo_estimado, "preco_venda_sugerido": preco_venda_sugerido,
    }


@endpoint()
def estimar_custos_pecas(pecas):
    """
    Recebe as pecas recem lidas do CAD (antes de gravar) e devolve o
    orcamento estimado de cada uma - usado pela tela de Integracao CAD/IA
    pra mostrar custo/preco sugerido peca a peca assim que o arquivo e lido.
    """
    if isinstance(pecas, str):
        pecas = json.loads(pecas)

    preco_aco_kg = _preco_insumo_hoje("Aço CA-50")
    preco_cimento_kg = _preco_insumo_hoje("Cimento CP-II")

    resultado = {}
    for p in pecas:
        cod = p.get("cod")
        if not cod:
            continue
        resultado[cod] = estimar_custo_peca(p.get("produto"), p.get("vol"), preco_aco_kg, preco_cimento_kg)

    total_custo = round(sum(r["custo_estimado"] for r in resultado.values()), 2)
    total_venda = round(sum(r["preco_venda_sugerido"] for r in resultado.values()), 2)

    return {
        "success": True,
        "pecas": resultado,
        "preco_aco_kg_usado": preco_aco_kg,
        "preco_cimento_kg_usado": preco_cimento_kg,
        "total_custo_estimado": total_custo,
        "total_preco_venda_sugerido": total_venda,
    }


def _default_warehouse(company=None, tipo_hint="Lojas"):
    company = company or _default_company()
    wh = frappe.db.get_value('Warehouse', {'company': company, 'warehouse_name': ['like', f'%{tipo_hint}%']}, 'name')
    if wh:
        return wh
    return frappe.db.get_value('Warehouse', {'company': company, 'is_group': 0}, 'name')

def _ensure_item(item_code, item_group='Products', stock_uom='Nos', is_stock_item=1):
    if frappe.db.exists('Item', item_code):
        return item_code
    frappe.get_doc({
        "doctype": "Item", "item_code": item_code, "item_name": item_code,
        "item_group": item_group, "stock_uom": stock_uom, "is_stock_item": is_stock_item
    }).insert(ignore_permissions=True)
    return item_code

def _ensure_customer_for_obra(codigo_obra):
    obra = frappe.get_doc('Obra', codigo_obra)
    if obra.customer and frappe.db.exists('Customer', obra.customer):
        return obra.customer

    nome_cliente = obra.cliente_nome or obra.nome_obra or codigo_obra
    if not frappe.db.exists('Customer', nome_cliente):
        frappe.get_doc({
            "doctype": "Customer", "customer_name": nome_cliente,
            "customer_group": frappe.db.get_value('Customer Group', {}, 'name') or "All Customer Groups",
            "territory": frappe.db.get_value('Territory', {}, 'name') or "All Territories"
        }).insert(ignore_permissions=True)

    obra.customer = nome_cliente
    obra.save(ignore_permissions=True)
    frappe.db.commit()
    return nome_cliente

@endpoint()
@_restaurar_usuario
def gerar_orcamento(codigo_obra, preco_kg=None):
    _exigir_papel("Comercial", "Financeiro", "Direção")
    frappe.set_user("Administrator")  # criação de Item/Quotation exige permissões que o Guest não tem
    if not frappe.db.exists('Obra', codigo_obra):
        return {"success": False, "error": "Obra não encontrada"}

    pecas = frappe.get_all('Peca Pre-Moldada', filters={'obra': codigo_obra},
                           fields=['produto', 'peso_kg', 'preco_venda_sugerido'])
    if not pecas:
        return {"success": False, "error": "Obra sem peças cadastradas — nada para orçar"}

    grupos = {}
    for p in pecas:
        g = grupos.setdefault(p.produto or "Peça Pré-Moldada", {"qtd": 0, "peso": 0.0, "venda": 0.0})
        g["qtd"] += 1
        g["peso"] += p.peso_kg or 0
        g["venda"] += p.preco_venda_sugerido or 0

    items = []
    for produto, g in grupos.items():
        if g["venda"] > 0 and not preco_kg:
            # preço do orçador automático (custo do dia + margem), peça a peça
            item_code = _ensure_item(f"PRECAST-{produto[:35]}", item_group='Products', stock_uom='Nos')
            items.append({"item_code": item_code, "item_name": produto, "description": produto,
                          "qty": g["qtd"], "uom": "Nos", "rate": round(g["venda"] / g["qtd"], 2)})
        elif g["peso"] > 0:
            item_code = _ensure_item(f"PRECAST-{produto[:35]}-KG", item_group='Products', stock_uom='Kg')
            items.append({"item_code": item_code, "item_name": produto, "description": produto,
                          "qty": round(g["peso"], 2), "uom": "Kg", "rate": float(preco_kg or PRECO_KG_VENDA_PADRAO)})
    if not items:
        return {"success": False, "error": "As peças desta obra ainda não têm seção e comprimento, então não há peso nem volume para orçar. "
                                           "Use o botão ✏️ Editar nas peças (Catálogo ou Fabricação), informe as dimensões e gere o orçamento de novo."}

    customer = _ensure_customer_for_obra(codigo_obra)
    quotation = frappe.get_doc({
        "doctype": "Quotation", "quotation_to": "Customer", "party_name": customer,
        "company": _default_company(), "currency": "BRL", "items": items
    })
    quotation.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"success": True, "quotation": quotation.name, "customer": customer,
            "valor_total": quotation.grand_total, "message": "Orçamento gerado com sucesso"}

@endpoint()
@_restaurar_usuario
def converter_orcamento_em_pedido(quotation_name):
    _exigir_papel("Comercial", "Financeiro", "Direção")
    frappe.set_user("Administrator")
    if not frappe.db.exists('Quotation', quotation_name):
        return {"success": False, "error": "Orçamento não encontrado"}

    from erpnext.selling.doctype.quotation.quotation import make_sales_order

    quotation = frappe.get_doc('Quotation', quotation_name)
    if quotation.docstatus == 0:
        quotation.submit()

    sales_order = make_sales_order(quotation_name)
    entrega = frappe.utils.add_days(frappe.utils.nowdate(), 30)
    warehouse = _default_warehouse(tipo_hint="Produtos Acabados") or _default_warehouse()
    sales_order.delivery_date = entrega
    for item in sales_order.items:
        item.delivery_date = entrega
        item.warehouse = warehouse
    sales_order.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"success": True, "sales_order": sales_order.name, "message": "Pedido de Venda gerado com sucesso"}

@endpoint()
@_restaurar_usuario
def gerar_requisicao_compras(codigo_obra, fator_cimento_kg_m3=None):
    _exigir_papel("Produção", "Financeiro", "Direção")
    frappe.set_user("Administrator")
    if not frappe.db.exists('Obra', codigo_obra):
        return {"success": False, "error": "Obra não encontrada"}

    pecas = frappe.get_all('Peca Pre-Moldada', filters={'obra': codigo_obra}, fields=['volume_m3', 'peso_kg', 'produto'])
    if not pecas:
        return {"success": False, "error": "Obra sem peças cadastradas — nada para explodir em materiais"}

    volume_total = sum(p.volume_m3 or 0 for p in pecas)
    fator = float(fator_cimento_kg_m3 or FATOR_CIMENTO_KG_POR_M3)
    cimento_kg = round(volume_total * fator, 1)

    # Aço por peça, usando a taxa real (kg de aço por m³ de concreto) do
    # tipo de produto daquela peça — não um percentual genérico do peso.
    aco_kg = 0.0
    for p in pecas:
        taxa = TAXA_ACO_KG_M3.get(p.produto, TAXA_ACO_KG_M3["Outros"])
        aco_kg += (p.volume_m3 or 0) * taxa
    aco_kg = round(aco_kg, 1)

    if cimento_kg <= 0 and aco_kg <= 0:
        return {"success": False, "error": "Volume/peso das peças insuficiente para estimar materiais"}

    item_cimento = _ensure_item("Cimento CP-V-ARI", item_group='Raw Material', stock_uom='Kg')
    item_aco = _ensure_item("Aço CA-50", item_group='Raw Material', stock_uom='Kg')
    warehouse = _default_warehouse()

    items = []
    if cimento_kg > 0:
        items.append({"item_code": item_cimento, "qty": cimento_kg, "uom": "Kg", "warehouse": warehouse, "schedule_date": frappe.utils.nowdate()})
    if aco_kg > 0:
        items.append({"item_code": item_aco, "qty": aco_kg, "uom": "Kg", "warehouse": warehouse, "schedule_date": frappe.utils.nowdate()})

    mr = frappe.get_doc({
        "doctype": "Material Request", "material_request_type": "Purchase",
        "company": _default_company(), "transaction_date": frappe.utils.nowdate(), "items": items
    })
    mr.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"success": True, "material_request": mr.name, "cimento_kg": cimento_kg, "aco_kg": aco_kg,
            "message": "Requisição de compras gerada com sucesso"}

@endpoint()
@_restaurar_usuario
def gerar_fatura_romaneio(codigo_romaneio, preco_kg=None):
    _exigir_papel("Financeiro", "Direção")
    frappe.set_user("Administrator")
    if not frappe.db.exists('Romaneio', codigo_romaneio):
        return {"success": False, "error": "Romaneio não encontrado"}

    romaneio = frappe.get_doc('Romaneio', codigo_romaneio)
    pecas = frappe.get_all('Peca Pre-Moldada', filters={'romaneio': codigo_romaneio},
                            fields=['codigo_peca', 'tag', 'produto', 'peso_kg'])
    if not pecas:
        return {"success": False, "error": "Romaneio sem peças vinculadas"}

    preco_kg = float(preco_kg or PRECO_KG_VENDA_PADRAO)
    customer = _ensure_customer_for_obra(romaneio.obra)

    warehouse = _default_warehouse(tipo_hint="Produtos Acabados") or _default_warehouse()
    items = []
    for p in pecas:
        item_code = _ensure_item(f"PRECAST-{(p.produto or 'PECA')[:35]}", item_group='Products', stock_uom='Kg')
        items.append({
            "item_code": item_code, "item_name": p.tag or p.codigo_peca,
            "description": f"{p.tag or p.codigo_peca} — Romaneio {codigo_romaneio}",
            "qty": p.peso_kg or 0, "uom": "Kg", "rate": preco_kg, "warehouse": warehouse
        })

    invoice = frappe.get_doc({
        "doctype": "Sales Invoice", "customer": customer, "company": _default_company(),
        "currency": "BRL", "items": items, "update_stock": 0
    })
    invoice.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"success": True, "sales_invoice": invoice.name, "valor_total": invoice.grand_total,
            "message": "Fatura gerada com sucesso"}

@endpoint()
def integrate_parsed_project(obra_data, pieces_data, modo="acrescentar"):
    """Grava a obra e as peças lidas do desenho. Cada peça fica na obra do arquivo importado: o mesmo código (PM.01)
    pode existir em obras diferentes. `modo`: "acrescentar" mantém o que a obra já tem; "substituir" tira da obra as
    peças que não estão mais no desenho e ainda não começaram a produção."""
    _exigir_papel("Produção", "Direção")
    if isinstance(obra_data, str):
        obra_data = json.loads(obra_data)
    if isinstance(pieces_data, str):
        pieces_data = json.loads(pieces_data)

    cod_obra = obra_data.get('cod', '').strip()
    if not cod_obra:
        return {"success": False, "error": "Código da obra é obrigatório"}

    nome_obra = obra_data.get('nome') or obra_data.get('cliente') or cod_obra
    cliente = obra_data.get('cliente') or nome_obra
    cidade_uf = obra_data.get('cidade_uf') or ''
    fck = obra_data.get('fck') or '40 MPa'

    if not frappe.db.exists('Obra', cod_obra):
        o_doc = frappe.get_doc({
            "doctype": "Obra",
            "codigo_obra": cod_obra,
            "nome_obra": nome_obra,
            "cliente_nome": cliente,
            "cidade_uf": cidade_uf,
            "fck_padrao": fck,
            "status": "Em Fabricação"
        })
        o_doc.insert(ignore_permissions=True)
    else:
        o_doc = frappe.get_doc('Obra', cod_obra)
        if (o_doc.nome_obra, o_doc.cliente_nome, o_doc.cidade_uf) != (nome_obra, cliente, cidade_uf):
            o_doc.nome_obra = nome_obra
            o_doc.cliente_nome = cliente
            o_doc.cidade_uf = cidade_uf
            o_doc.save(ignore_permissions=True)

    from frappe.precast_revisoes import aplicar as _aplicar_revisao, comparar as _comparar_revisao
    diferencas = _comparar_revisao(cod_obra, pieces_data)   # antes de a gravação trocar os dados das peças

    created_count = 0
    updated_count = 0
    gravados = set()  # códigos como ficaram no sistema (com o prefixo da obra quando outra obra já usa o código)

    # Preco do dia buscado uma unica vez pra todas as pecas da obra, nao
    # peca a peca (mesmo criterio do orcador: Cotacoes do dia > ultima
    # anterior > media historica sugerida).
    preco_aco_kg = _preco_insumo_hoje("Aço CA-50")
    preco_cimento_kg = _preco_insumo_hoje("Cimento CP-II")

    for p in pieces_data:
        p_cod = p.get('cod', '').strip()
        if not p_cod: continue

        tag = p.get('tag') or f"PEÇA {p_cod}"
        prod = _produto_padrao(p.get('produto', 'Pilar'))

        secao = str(p.get('secao') or '').strip()
        comp = float(p.get('comp') or 0.0)
        vol = float(p.get('vol') or 0.0)
        peso = float(p.get('peso') or 0.0)
        p_fck = p.get('fck') or fck
        orig_file = p.get('file', '')
        # Só grava o endereço da prancha quando o arquivo existe; um caminho inventado
        # vira anexo quebrado e erro no log.
        prancha_url = p.get('prancha_url') or None
        print_url = p.get('print_url') or None

        orcamento = estimar_custo_peca(prod, vol, preco_aco_kg, preco_cimento_kg, aco_kg_real=p.get('peso_aco_kg') if p.get('fonte') == 'prancha' else None)

        # A mesma tag (P1, V1...) se repete entre obras. A peça de outra obra nunca é
        # sobrescrita nem trocada de obra: o código dela ganha o prefixo desta obra.
        dono = frappe.db.get_value('Peca Pre-Moldada', p_cod, 'obra')
        if dono and dono != cod_obra:
            p_cod = f"{cod_obra}-{p_cod}"
            tag = p.get('tag') or p.get('cod')
        gravados.add(p_cod)

        if not frappe.db.exists('Peca Pre-Moldada', p_cod):
            p_doc = frappe.get_doc({
                "doctype": "Peca Pre-Moldada",
                "codigo_peca": p_cod,
                "tag": tag,
                "obra": cod_obra,
                "cliente": cliente,
                "produto": prod,
                "secao": secao,
                "comprimento_m": comp,
                "volume_m3": vol,
                "peso_kg": peso,
                "fck": p_fck,
                "status_producao": "1. Corte e Dobra",
                "fase_numero": 1,
                "prancha_url": prancha_url,
                "print_url": print_url,
                "prancha_pdf": prancha_url,
                "prancha_png": print_url,
                "arquivo_origem": orig_file,
                "peso_aco_kg": p.get('peso_aco_kg') or 0,
                "taxa_aco_kg_m3": p.get('taxa_aco') or 0,
                "lista_ferros": json.dumps(p.get('ferros') or [], ensure_ascii=False),
                "folha_prancha": p.get('folha') or '',
                "titulo_prancha": p.get('titulo_prancha') or '',
                "fonte_leitura": p.get('fonte') or 'texto',
                "dimensoes_confirmadas": 1 if p.get('dimensoes_confirmadas', True) else 0,
                "aviso_engenharia": p.get('aviso', ''),
                "custo_estimado_peca": orcamento["custo_estimado"],
                "preco_venda_sugerido": orcamento["preco_venda_sugerido"],
            })
            p_doc.insert(ignore_permissions=True)
            created_count += 1
        else:
            p_doc = frappe.get_doc('Peca Pre-Moldada', p_cod)
            p_doc.tag = tag
            p_doc.obra = cod_obra
            p_doc.secao = secao
            p_doc.comprimento_m = comp
            p_doc.volume_m3 = vol
            p_doc.peso_kg = peso
            p_doc.dimensoes_confirmadas = 1 if p.get('dimensoes_confirmadas', True) else 0
            p_doc.aviso_engenharia = p.get('aviso', '')
            p_doc.peso_aco_kg = p.get('peso_aco_kg') or 0
            p_doc.taxa_aco_kg_m3 = p.get('taxa_aco') or 0
            p_doc.lista_ferros = json.dumps(p.get('ferros') or [], ensure_ascii=False)
            p_doc.folha_prancha = p.get('folha') or ''
            p_doc.titulo_prancha = p.get('titulo_prancha') or ''
            p_doc.fonte_leitura = p.get('fonte') or 'texto'
            if prancha_url:
                p_doc.prancha_url = prancha_url
            if print_url:
                p_doc.print_url = print_url
            p_doc.custo_estimado_peca = orcamento["custo_estimado"]
            p_doc.preco_venda_sugerido = orcamento["preco_venda_sugerido"]
            p_doc.save(ignore_permissions=True)
            updated_count += 1

        # Cada peça sai da leitura do DWG/DXF já com o QR gerado - não fica
        # pendente do primeiro clique em "Etiqueta" pra existir.
        try:
            get_or_generate_qrcode(p_cod)
        except Exception as e:
            frappe.log_error(title="Falha ao gerar QR na importação", message=f"{p_cod}: {e}")

    removidas, mantidas = _sincronizar_pecas_da_obra(cod_obra, gravados, pieces_data) if modo == "substituir" else ([], [])
    numero_revisao = _aplicar_revisao(cod_obra, obra_data.get('revisao'), obra_data.get('arquivo'), modo, diferencas)
    frappe.db.commit()
    return {
        "success": True,
        "obra": cod_obra,
        "revisao": {"numero": numero_revisao, "nome": obra_data.get('revisao'), **diferencas["resumo"]},
        "pecas_removidas": removidas,
        "pecas_fora_do_desenho": mantidas,
        "created": created_count,
        "updated": updated_count,
        "total": len(pieces_data)
    }

@endpoint()
def comparar_revisao(obra_data, pieces_data):
    """Mostra o que o desenho lido muda nas peças já gravadas da obra e o efeito na produção. Não grava nada."""
    _exigir_papel("Produção", "Direção")
    if isinstance(obra_data, str):
        obra_data = json.loads(obra_data)
    if isinstance(pieces_data, str):
        pieces_data = json.loads(pieces_data)
    cod_obra = (obra_data.get('cod') or '').strip()
    if not cod_obra:
        return {"success": False, "error": "Código da obra é obrigatório"}
    from frappe.precast_revisoes import comparar
    return {"success": True, "obra": cod_obra, "revisao": obra_data.get('revisao'), **comparar(cod_obra, pieces_data)}


@endpoint()
def listar_revisoes(obra):
    from frappe.precast_revisoes import listar
    return {"success": True, "obra": obra, "revisoes": listar(obra)}


@endpoint()
def create_obra(codigo_obra, nome_obra=None, cliente_nome=None, cidade_uf=None, fck_padrao=None, status="Em Fabricação"):
    _exigir_papel("Produção", "Comercial", "Direção")
    if not codigo_obra:
        return {"success": False, "error": "Código da obra é obrigatório"}
    codigo_obra = codigo_obra.strip()
    if frappe.db.exists('Obra', codigo_obra):
        return {"success": False, "error": f"Obra {codigo_obra} já existe."}
    
    doc = frappe.get_doc({
        "doctype": "Obra",
        "codigo_obra": codigo_obra,
        "nome_obra": nome_obra or codigo_obra,
        "cliente_nome": cliente_nome or nome_obra or codigo_obra,
        "cidade_uf": cidade_uf or "",
        "fck_padrao": fck_padrao or "35 MPa",
        "status": status or "Em Fabricação"
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "codigo_obra": codigo_obra, "message": "Obra criada com sucesso"}

def _apagar_registros_da_peca(codigo_peca):
    """Laudos, corpos de prova, RNCs e histórico de fase pertencem à peça. Se ficassem
    para trás, uma peça reimportada com o mesmo código herdaria um corpo de prova
    aprovado de outra peça e a trava de desforma deixaria de valer."""
    for doctype in ("Checklist Qualidade", "Nao Conformidade", "Fase Historico"):
        for nome in frappe.get_all(doctype, filters={"codigo_peca": codigo_peca}, pluck="name"):
            frappe.delete_doc(doctype, nome, ignore_permissions=True, force=True)
    _apagar_arquivos_da_peca(codigo_peca)


_PASTA_ARQUIVOS = "/home/frappe/frappe-bench/sites/frontend/public/files"


def _apagar_arquivos_da_peca(codigo_peca):
    """Prancha (PDF e imagem) e QR Code da peça saem do disco junto com o registro: uma obra importada de novo
    não pode herdar o desenho de uma leitura anterior."""
    peca = frappe.db.get_value("Peca Pre-Moldada", codigo_peca, ["prancha_url", "print_url", "prancha_pdf", "prancha_png"], as_dict=True) or {}
    alvos = {f"{_PASTA_ARQUIVOS}/qrcodes/{codigo_peca}.png"}
    for url in (peca.get("prancha_url"), peca.get("print_url"), peca.get("prancha_pdf"), peca.get("prancha_png")):
        if url and str(url).startswith("/files/pranchas/"):
            alvos.add(f"{_PASTA_ARQUIVOS}/pranchas/{os.path.basename(str(url))}")
    for caminho in alvos:
        try:
            os.remove(caminho)
        except OSError:
            pass


_DENSIDADE_CONCRETO_KG_M3 = 2500.0


def _parse_secao(texto):
    """'30x50', '30 X 50' ou '30*50' (cm) -> (30.0, 50.0); None se não der para ler."""
    m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*[xX*×]\s*(\d+(?:[.,]\d+)?)\s*$", str(texto or ""))
    if not m:
        return None
    return float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))


@endpoint()
def atualizar_peca(codigo_peca, secao, comprimento_m, fck=None, aplicar_a_semelhantes=False):
    """Informa as dimensões que o desenho não trouxe. Calcula volume, peso e orçamento e marca a
    peça como confirmada. Com `aplicar_a_semelhantes`, vale também para as peças do mesmo produto
    na mesma obra que ainda estão sem dimensões."""
    _exigir_papel("Produção", "Direção")
    if not frappe.db.exists("Peca Pre-Moldada", codigo_peca):
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}
    medidas = _parse_secao(secao)
    if not medidas:
        return {"success": False, "error": "Informe a seção em cm no formato LARGURAxALTURA, por exemplo 30x50."}
    try:
        comp = float(str(comprimento_m).replace(",", "."))
    except (TypeError, ValueError):
        return {"success": False, "error": "Informe o comprimento em metros, por exemplo 6,5."}
    if not 0 < comp <= 60 or not all(0 < m <= 500 for m in medidas):
        return {"success": False, "error": "Dimensões fora do esperado. Seção em cm (até 500) e comprimento em metros (até 60)."}

    base = frappe.get_doc("Peca Pre-Moldada", codigo_peca)
    alvos = [base.name]
    if str(aplicar_a_semelhantes).lower() in ("1", "true", "sim"):
        comuns = {"obra": base.obra, "produto": base.produto, "name": ["!=", base.name]}
        sem_medidas = set(frappe.get_all("Peca Pre-Moldada", pluck="name", filters={**comuns, "dimensoes_confirmadas": 0}))
        sem_medidas |= set(frappe.get_all("Peca Pre-Moldada", pluck="name", filters={**comuns, "volume_m3": ["in", [0, None]]}))
        alvos += sorted(sem_medidas)

    secao_txt = f"{int(medidas[0]) if medidas[0].is_integer() else medidas[0]}x{int(medidas[1]) if medidas[1].is_integer() else medidas[1]}"
    volume = round(medidas[0] / 100 * medidas[1] / 100 * comp, 3)
    peso = round(volume * _DENSIDADE_CONCRETO_KG_M3, 1)
    preco_aco, preco_cimento = _preco_insumo_hoje("Aço CA-50"), _preco_insumo_hoje("Cimento CP-II")
    for nome in alvos:
        doc = frappe.get_doc("Peca Pre-Moldada", nome)
        orc = estimar_custo_peca(doc.produto, volume, preco_aco, preco_cimento)
        doc.secao, doc.comprimento_m, doc.volume_m3, doc.peso_kg = secao_txt, comp, volume, peso
        doc.custo_estimado_peca, doc.preco_venda_sugerido = orc["custo_estimado"], orc["preco_venda_sugerido"]
        if fck:
            doc.fck = fck
        doc.dimensoes_confirmadas = 1
        doc.aviso_engenharia = ""
        doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "atualizadas": len(alvos), "volume_m3": volume, "peso_kg": peso,
            "message": f"{len(alvos)} peça(s) atualizada(s): {secao_txt} cm x {comp} m = {volume} m³, {peso} kg."}


def _sincronizar_pecas_da_obra(cod_obra, codigos_lidos, pieces_data):
    """Modo "substituir": o desenho importado vira a referência da obra: peça que não está
    mais nas pranchas e ainda não começou a produção sai; a que já tem produção ou histórico fica marcada."""
    removidas, mantidas = [], []
    for peca in frappe.get_all('Peca Pre-Moldada', filters={'obra': cod_obra}, fields=['name', 'codigo_peca', 'fase_numero']):
        if peca.name in codigos_lidos:
            continue
        com_historico = frappe.db.exists('Fase Historico', {'codigo_peca': peca.name}) or frappe.db.exists('Checklist Qualidade', {'codigo_peca': peca.name})
        if (peca.fase_numero or 1) <= 1 and not com_historico:
            _apagar_registros_da_peca(peca.name)
            frappe.delete_doc('Peca Pre-Moldada', peca.name, ignore_permissions=True, force=True)
            removidas.append(peca.name)
        else:
            frappe.db.set_value('Peca Pre-Moldada', peca.name, 'aviso_engenharia', 'Esta peça não consta nas pranchas do último desenho importado.')
            mantidas.append(peca.name)
    return removidas, mantidas


@endpoint()
def delete_obra(codigo_obra):
    _exigir_papel("Direção")
    if not codigo_obra:
        return {"success": False, "error": "Código da obra não fornecido"}
    codigo_obra = codigo_obra.strip()
    
    # 1. Delete associated pieces
    pecas = frappe.get_all('Peca Pre-Moldada', filters={'obra': codigo_obra}, fields=['name', 'codigo_peca'])
    deleted_pieces = 0
    for p in pecas:
        _apagar_registros_da_peca(p.name)
        frappe.delete_doc('Peca Pre-Moldada', p.name, ignore_permissions=True, force=True)
        deleted_pieces += 1
        
    for doctype in ("Revisao Projeto", "Plano Corte", "Pedido Compra", "Titulo Pagar"):
        for nome in frappe.get_all(doctype, filters={"obra": codigo_obra}, pluck="name"):
            frappe.delete_doc(doctype, nome, ignore_permissions=True, force=True)
    frappe.defaults.clear_default(key=f"portal_cfg:{codigo_obra}", parent="__default")  # o que o cliente via e o link não passam para uma obra nova de mesmo código
    # 2. Delete the Obra document itself
    if frappe.db.exists('Obra', codigo_obra):
        frappe.delete_doc('Obra', codigo_obra, ignore_permissions=True, force=True)
        frappe.db.commit()
        return {
            "success": True, 
            "codigo_obra": codigo_obra, 
            "deleted_pieces": deleted_pieces,
            "message": f"Obra {codigo_obra} e suas {deleted_pieces} peças foram excluídas com sucesso."
        }
    else:
        frappe.db.commit()
        return {"success": False, "error": f"Obra {codigo_obra} não encontrada"}

@endpoint()
def delete_piece(codigo_peca):
    _exigir_papel("Produção", "Direção")
    if not codigo_peca:
        return {"success": False, "error": "Código da peça não fornecido"}
    codigo_peca = codigo_peca.strip()
    
    if frappe.db.exists('Peca Pre-Moldada', codigo_peca):
        _apagar_registros_da_peca(codigo_peca)
        frappe.delete_doc('Peca Pre-Moldada', codigo_peca, ignore_permissions=True, force=True)
        frappe.db.commit()
        return {"success": True, "codigo_peca": codigo_peca, "message": f"Peça {codigo_peca} excluída com sucesso."}
    else:
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}

@endpoint()
def get_formas_pistas():
    formas = frappe.get_all('Forma Pista', fields=[
        'codigo', 'tipo', 'comprimento_m', 'largura_m', 'capacidade_kg', 'status', 'ciclo_dias', 'giros_realizados', 'giros_limite_manutencao'
    ], order_by='codigo asc')

    for f in formas:
        pecas = frappe.get_all('Peca Pre-Moldada',
            filters={'forma_pista': f.codigo},
            fields=['codigo_peca', 'tag', 'obra', 'data_programada', 'status_producao'],
            order_by='data_programada asc'
        )
        f['pecas_alocadas'] = pecas

    return {"success": True, "formas_pistas": formas}

@endpoint()
def create_forma_pista(codigo, tipo, comprimento_m=None, largura_m=None, capacidade_kg=None):
    _exigir_papel("Produção", "Direção")
    if not codigo or not tipo:
        return {"success": False, "error": "Código e tipo são obrigatórios"}
    codigo = codigo.strip()
    if frappe.db.exists('Forma Pista', codigo):
        return {"success": False, "error": f"Forma/Pista {codigo} já existe."}

    doc = frappe.get_doc({
        "doctype": "Forma Pista",
        "codigo": codigo,
        "tipo": tipo,
        "comprimento_m": comprimento_m or 0,
        "largura_m": largura_m or 0,
        "capacidade_kg": capacidade_kg or 0,
        "status": "Livre"
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "codigo": codigo, "message": "Forma/Pista criada com sucesso"}

@endpoint()
def delete_forma_pista(codigo):
    _exigir_papel("Produção", "Direção")
    if not codigo:
        return {"success": False, "error": "Código não fornecido"}
    codigo = codigo.strip()
    if not frappe.db.exists('Forma Pista', codigo):
        return {"success": False, "error": f"Forma/Pista {codigo} não encontrada"}

    # Desaloca peças programadas nessa forma/pista antes de excluir — nunca
    # deixa uma peça apontando pra um registro que não existe mais.
    pecas = frappe.get_all('Peca Pre-Moldada', filters={'forma_pista': codigo}, fields=['name'])
    for p in pecas:
        pdoc = frappe.get_doc('Peca Pre-Moldada', p.name)
        pdoc.forma_pista = None
        pdoc.data_programada = None
        pdoc.save(ignore_permissions=True)

    frappe.delete_doc('Forma Pista', codigo, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"success": True, "codigo": codigo, "pecas_desalocadas": len(pecas),
            "message": f"Forma/Pista {codigo} excluída ({len(pecas)} peças desalocadas)."}

@endpoint()
def program_piece(codigo_peca, forma_pista, data_programada, forcar=False):
    """Programa a peça numa forma/pista numa data, conferindo manutenção, tamanho e ocupação (o ciclo de cura conta)."""
    _exigir_papel("Produção", "Direção")
    from frappe.precast_patio import programar
    r = programar(codigo_peca, forma_pista, data_programada, str(forcar).lower() in ("1", "true", "sim"))
    if not r.get("success"):
        return r
    frappe.db.commit()
    return {"success": True, "codigo_peca": codigo_peca, "forma_pista": forma_pista,
            "data_programada": data_programada, "message": "Peça programada com sucesso"}

@endpoint()
def config_patio(desforma_pct_fck=None, trabalha_sabado=None):
    from frappe.precast_patio import configuracao
    if desforma_pct_fck not in (None, "") or trabalha_sabado not in (None, ""):
        _exigir_papel("Produção", "Qualidade", "Direção")
    return configuracao(desforma_pct_fck, trabalha_sabado)


@endpoint()
def visao_patio(data_inicio=None, dias=14):
    from frappe.precast_patio import visao
    return visao(data_inicio, dias)


@endpoint()
def sugerir_programacao(obra=None, data_inicio=None, pecas=None):
    _exigir_papel("Produção", "Direção")
    from frappe.precast_patio import sugerir
    return sugerir(obra, data_inicio, pecas)


@endpoint()
def aplicar_programacao(sugestoes):
    _exigir_papel("Produção", "Direção")
    if isinstance(sugestoes, str):
        sugestoes = json.loads(sugestoes)
    from frappe.precast_patio import aplicar_sugestoes
    return aplicar_sugestoes(sugestoes)


@endpoint()
def configurar_forma_pista(codigo, ciclo_dias):
    _exigir_papel("Produção", "Direção")
    from frappe.precast_patio import configurar_forma
    return configurar_forma(codigo, ciclo_dias)


@endpoint()
def unprogram_piece(codigo_peca):
    _exigir_papel("Produção", "Direção")
    if not frappe.db.exists('Peca Pre-Moldada', codigo_peca):
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}

    doc = frappe.get_doc('Peca Pre-Moldada', codigo_peca)
    forma_pista = doc.forma_pista
    doc.forma_pista = None
    doc.data_programada = None
    doc.save(ignore_permissions=True)

    if forma_pista and frappe.db.exists('Forma Pista', forma_pista):
        restantes = frappe.db.count('Peca Pre-Moldada', {'forma_pista': forma_pista})
        if restantes == 0:
            forma_doc = frappe.get_doc('Forma Pista', forma_pista)
            if forma_doc.status == 'Ocupada':
                forma_doc.status = 'Livre'
                forma_doc.save(ignore_permissions=True)

    frappe.db.commit()
    return {"success": True, "codigo_peca": codigo_peca, "message": "Peça desprogramada com sucesso"}

@endpoint()
def get_estoque_armacao(obra=None):
    # Corte & Dobra (fase 1) e Armação Pronta (fase 2) — mesmo modelo de
    # 8 fases já usado na Lista da Fabricação, só reapresentado como um
    # painel duplo de movimentação entre as duas áreas.
    filters = {'fase_numero': ['in', [1, 2]]}
    if obra:
        filters['obra'] = obra
    fields = ['codigo_peca', 'tag', 'obra', 'produto', 'peso_kg', 'fase_numero', 'status_producao']
    pecas = frappe.get_all('Peca Pre-Moldada', filters=filters, fields=fields, order_by='modified desc')

    corte_dobra = [p for p in pecas if p.fase_numero == 1]
    armacao_pronta = [p for p in pecas if p.fase_numero == 2]
    return {"success": True, "corte_dobra": corte_dobra, "armacao_pronta": armacao_pronta}

@endpoint()
def move_armacao(codigo_peca, direction):
    _exigir_papel("Produção", "Direção")
    # direction: 'avancar' (Corte&Dobra -> Armação Pronta) ou 'recuar' (volta)
    if not frappe.db.exists('Peca Pre-Moldada', codigo_peca):
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}

    doc = frappe.get_doc('Peca Pre-Moldada', codigo_peca)
    curr_fase = doc.fase_numero or 1
    if direction == 'avancar':
        if curr_fase != 1:
            return {"success": False, "error": "Peça não está em Corte e Dobra"}
        new_fase = 2
    elif direction == 'recuar':
        if curr_fase != 2:
            return {"success": False, "error": "Peça não está em Armação Pronta"}
        new_fase = 1
    else:
        return {"success": False, "error": "Direção inválida (use 'avancar' ou 'recuar')"}

    fases_nome = {1: "1. Corte e Dobra", 2: "2. Armação Pronta"}
    doc.fase_numero = new_fase
    doc.status_producao = fases_nome[new_fase]
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "codigo_peca": codigo_peca, "fase_numero": new_fase, "status_producao": fases_nome[new_fase]}

@endpoint()
def get_programacao_semana(data_inicio):
    from datetime import datetime, timedelta
    inicio = datetime.strptime(data_inicio, "%Y-%m-%d").date()
    dias = [(inicio + timedelta(days=i)).isoformat() for i in range(7)]
    fim = dias[-1]

    formas = frappe.get_all('Forma Pista', fields=['codigo', 'tipo'], order_by='codigo asc')
    pecas = frappe.get_all('Peca Pre-Moldada',
        filters={'data_programada': ['between', [dias[0], fim]], 'forma_pista': ['is', 'set']},
        fields=['codigo_peca', 'tag', 'obra', 'forma_pista', 'data_programada', 'status_producao']
    )

    grade = {f.codigo: {d: [] for d in dias} for f in formas}
    for p in pecas:
        data_str = str(p.data_programada)
        if p.forma_pista in grade and data_str in grade[p.forma_pista]:
            grade[p.forma_pista][data_str].append({
                "codigo_peca": p.codigo_peca, "tag": p.tag, "obra": p.obra,
                "status_producao": p.status_producao
            })

    return {"success": True, "dias": dias, "formas_pistas": formas, "grade": grade}

@endpoint()
def clean_fictitious_data():
    _exigir_papel("Direção")
    # Remove TEST-01 or test obras
    test_obras = frappe.get_all('Obra', filters={'codigo_obra': ['like', '%TEST%']}, fields=['name'])
    deleted_obras = []
    for o in test_obras:
        delete_obra(o.name)
        deleted_obras.append(o.name)
        
    # Remove demo ERPNext customers if any
    demo_custs = ['Grant Plastics Ltd.', 'Palmer Productions Ltd.', 'West View Software Ltd.']
    for c in demo_custs:
        if frappe.db.exists('Customer', c):
            try:
                frappe.delete_doc('Customer', c, ignore_permissions=True, force=True)
            except Exception:
                pass
                
    # Remove demo items (SKU001 - SKU010)
    for i in range(1, 11):
        sku = f"SKU{i:03d}"
        if frappe.db.exists('Item', sku):
            try:
                frappe.delete_doc('Item', sku, ignore_permissions=True, force=True)
            except Exception:
                pass
                
    frappe.db.commit()
    return {"success": True, "deleted_obras": deleted_obras, "message": "Dados fictícios removidos com sucesso."}

@endpoint()
def update_web_page_content():
    _exigir_papel("Direção")
    html_path = "/home/frappe/frappe-bench/sites/frontend/www/painel.html"
    with open(html_path, 'r', encoding='utf-8') as f:
        new_html = f.read()

    doc = frappe.get_doc('Web Page', 'painel-controle-agil')
    doc.main_section = new_html
    doc.main_section_html = new_html
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    return {"success": True, "message": "Página atualizada com sucesso"}

@endpoint(allow_guest=True)
def precast_bipar_manifest():
    """Serve o manifest.json do PWA com Content-Type correto - servir como
    Web Page normal quebraria o JSON (fica embrulhado em HTML)."""
    with open("/home/frappe/frappe-bench/sites/frontend/www/bipar-manifest.json", encoding="utf-8") as f:
        content = f.read()
    frappe.local.response["type"] = "download"
    frappe.local.response["filename"] = "bipar-manifest.json"
    frappe.local.response["filecontent"] = content
    frappe.local.response["content_type"] = "application/manifest+json"
    frappe.local.response["display_content_as"] = "inline"


@endpoint(allow_guest=True)
def precast_bipar_sw():
    """Serve o service worker com Content-Type de JS e o header
    Service-Worker-Allowed: / — sem isso o navegador recusa o escopo raiz
    (senao o SW so controlaria a propria pasta onde o arquivo esta)."""
    with open("/home/frappe/frappe-bench/sites/frontend/www/bipar-sw.js", encoding="utf-8") as f:
        content = f.read()
    frappe.local.response["type"] = "download"
    frappe.local.response["filename"] = "bipar-sw.js"
    frappe.local.response["filecontent"] = content
    frappe.local.response["content_type"] = "text/javascript"
    frappe.local.response["display_content_as"] = "inline"
    frappe.local.response_headers["Service-Worker-Allowed"] = "/"


@endpoint()
def update_bipar_page_content():
    _exigir_papel("Direção")
    html_path = "/home/frappe/frappe-bench/sites/frontend/www/bipar.html"
    with open(html_path, 'r', encoding='utf-8') as f:
        new_html = f.read()

    name = frappe.db.get_value('Web Page', {'route': 'bipar'}, 'name')
    if not name:
        return {"success": False, "error": "Web Page com route 'bipar' não existe ainda."}

    doc = frappe.get_doc('Web Page', name)
    doc.main_section = new_html
    doc.main_section_html = new_html
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    return {"success": True, "message": "Página do coletor atualizada com sucesso"}


# ============================================================
# 20 MELHORIAS - funcionalidades adicionais sobre o pipeline
# real (CAD -> peca -> fase -> logistica -> financeiro).
# ============================================================

@endpoint()
def registrar_ruptura_cp(codigo_peca, fck_obtido, idade_dias=28, inspetor=None, observacoes=None):
    """Melhoria 2: atalho pra registrar a ruptura do corpo de prova direto
    (sem passar pelo checklist completo de etapa), gerando o mesmo registro
    que a trava de desforma em advance_piece_phase consulta."""
    _exigir_papel("Qualidade", "Direção")
    if not frappe.db.exists('Peca Pre-Moldada', codigo_peca):
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}

    peca = frappe.get_doc('Peca Pre-Moldada', codigo_peca)

    def _num(v):
        try:
            return float(str(v).upper().replace("MPA", "").strip())
        except (TypeError, ValueError):
            return None

    exigido = _num(peca.fck) or 0
    obtido = _num(fck_obtido)
    if obtido is None:
        return {"success": False, "error": "fck_obtido inválido"}
    aprovado = obtido >= exigido

    doc = frappe.get_doc({
        "doctype": "Checklist Qualidade", "codigo_peca": codigo_peca,
        "etapa": "5. Concretagem", "aprovado": 1 if aprovado else 0,
        "inspetor": inspetor, "data_inspecao": frappe.utils.now_datetime(),
        "observacoes": f"Ruptura de corpo de prova aos {idade_dias} dias. {observacoes or ''}".strip(),
        "fck_corpo_prova": fck_obtido,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "success": True, "aprovado": aprovado, "fck_exigido": exigido, "fck_obtido": obtido,
        "message": "CP aprovado — desforma liberada." if aprovado else
                   f"CP reprovado ({obtido} MPa < {exigido} MPa exigido) — desforma continua bloqueada."
    }


@endpoint()
def get_corpos_de_prova(codigo_peca=None, obra=None):
    filters = {}
    if codigo_peca:
        filters["codigo_peca"] = codigo_peca
    checklists = frappe.get_all("Checklist Qualidade",
        filters={**filters, "fck_corpo_prova": ["is", "set"]},
        fields=["codigo_peca", "etapa", "aprovado", "fck_corpo_prova", "data_inspecao", "inspetor"],
        order_by="data_inspecao desc")
    if obra:
        cods = {p.codigo_peca for p in frappe.get_all("Peca Pre-Moldada", filters={"obra": obra}, fields=["codigo_peca"])}
        checklists = [c for c in checklists if c.codigo_peca in cods]
    return {"success": True, "corpos_de_prova": checklists}


@endpoint()
def sugerir_carretas(codigo_obra):
    """Melhoria 3: cubagem/paginacao de carga - quantas carretas (do maior
    caminhao cadastrado pra baixo) sao necessarias pra levar o que ja esta
    liberado (fase 6) e ainda nao foi romaneado desta obra."""
    if not frappe.db.exists('Obra', codigo_obra):
        return {"success": False, "error": "Obra não encontrada"}

    pecas = frappe.get_all('Peca Pre-Moldada',
        filters={'obra': codigo_obra, 'fase_numero': 6, 'romaneio': ['in', ['', None]]},
        fields=['codigo_peca', 'peso_kg', 'comprimento_m'])
    if not pecas:
        return {"success": True, "pecas_pendentes": 0, "carretas_sugeridas": 0, "detalhe": []}

    caminhoes = frappe.get_all('Caminhao', fields=['placa', 'capacidade_kg'], order_by='capacidade_kg desc')
    if not caminhoes:
        return {"success": False, "error": "Nenhum caminhão cadastrado — cadastre a frota antes de simular carretas."}

    capacidade_padrao = caminhoes[0].capacidade_kg or 1
    restante = sorted([p.peso_kg or 0 for p in pecas], reverse=True)
    cargas = []
    for peso in restante:
        alocado = False
        for carga in cargas:
            if carga["peso"] + peso <= capacidade_padrao:
                carga["peso"] += peso
                carga["qtd"] += 1
                alocado = True
                break
        if not alocado:
            cargas.append({"peso": peso, "qtd": 1})

    peso_total = sum(restante)
    return {
        "success": True, "pecas_pendentes": len(pecas), "peso_total_kg": round(peso_total, 1),
        "capacidade_referencia_kg": capacidade_padrao, "carretas_sugeridas": len(cargas),
        "detalhe": [{"carreta": i + 1, "peso_kg": round(c["peso"], 1), "pecas": c["qtd"]} for i, c in enumerate(cargas)],
    }


@endpoint()
@_restaurar_usuario
def gerar_fatura_montagem(codigo_obra):
    """Melhoria 4: medicao/faturamento por peca MONTADA (fase 8), usando o
    preco_venda_sugerido ja calculado pelo orcador automatico - nao um
    preco fixo por kg."""
    _exigir_papel("Financeiro", "Direção")
    frappe.set_user("Administrator")
    if not frappe.db.exists('Obra', codigo_obra):
        return {"success": False, "error": "Obra não encontrada"}

    pecas = frappe.get_all('Peca Pre-Moldada',
        filters={'obra': codigo_obra, 'fase_numero': 8, 'faturado_montagem': 0},
        fields=['name', 'codigo_peca', 'tag', 'produto', 'preco_venda_sugerido'])
    if not pecas:
        return {"success": False, "error": "Nenhuma peça montada e ainda não faturada nesta obra."}

    customer = _ensure_customer_for_obra(codigo_obra)
    warehouse = _default_warehouse(tipo_hint="Produtos Acabados") or _default_warehouse()

    items = []
    for p in pecas:
        item_code = _ensure_item(f"PRECAST-{(p.produto or 'PECA')[:35]}", item_group='Products', stock_uom='Nos')
        items.append({
            "item_code": item_code, "item_name": p.tag or p.codigo_peca,
            "description": f"{p.tag or p.codigo_peca} — medição por montagem",
            "qty": 1, "uom": "Nos", "rate": p.preco_venda_sugerido or 0, "warehouse": warehouse,
        })

    invoice = frappe.get_doc({
        "doctype": "Sales Invoice", "customer": customer, "company": _default_company(),
        "currency": "BRL", "items": items, "update_stock": 0,
    })
    invoice.insert(ignore_permissions=True)

    for p in pecas:
        frappe.db.set_value('Peca Pre-Moldada', p.name, 'faturado_montagem', 1)

    frappe.db.commit()
    return {"success": True, "sales_invoice": invoice.name, "valor_total": invoice.grand_total,
            "pecas_faturadas": len(pecas), "message": "Fatura de medição por montagem gerada"}


@endpoint(allow_guest=True)
def get_status_publico_obra(codigo_obra, t=None):
    """Portal do cliente: andamento da obra, peças por situação, entregas e diário. Sem preços nem
    dados financeiros. Exige o token do link gerado por `get_link_portal`."""
    if not t or not hmac.compare_digest(str(t), _token_portal(codigo_obra)) or not frappe.db.exists('Obra', codigo_obra):
        return {"success": False, "error": "Link inválido ou expirado. Peça um novo link à empresa."}

    cfg = _config_portal(codigo_obra)
    if not cfg["ativo"]:
        return {"success": False, "error": "O acompanhamento desta obra não está disponível no momento. Fale com a empresa."}
    obra = frappe.get_doc('Obra', codigo_obra)
    pecas = frappe.get_all('Peca Pre-Moldada', filters={'obra': codigo_obra},
                           fields=['tag', 'produto', 'fase_numero', 'peso_kg', 'volume_m3', 'romaneio'], order_by='tag asc')
    romaneios = frappe.get_all('Romaneio', filters={'obra': codigo_obra},
                               fields=['codigo', 'status', 'data_expedicao', 'data_entrega', 'peso_total_kg', 'recebedor_nome'],
                               order_by='data_expedicao desc')
    entregues = {r.codigo for r in romaneios if r.status == "Entregue"}

    total = len(pecas)
    contagem = {"Em produção": 0, "Produzida": 0, "Expedida": 0, "Entregue": 0, "Montada": 0}
    peso = {"total": 0.0, "produzido": 0.0, "montado": 0.0}
    volume = {"total": 0.0, "produzido": 0.0, "montado": 0.0}
    por_produto = {}
    lista = []
    fases = {n: 0 for n in range(1, 9)}
    for p in pecas:
        fase = p.fase_numero or 1
        situacao = _situacao_da_peca(fase, p.romaneio in entregues)
        contagem[situacao] += 1
        fases[fase] = fases.get(fase, 0) + 1
        for chave, ok in (("total", True), ("produzido", fase >= 6), ("montado", fase >= 8)):
            if ok:
                peso[chave] += p.peso_kg or 0
                volume[chave] += p.volume_m3 or 0
        g = por_produto.setdefault(p.produto or "Outros", {"total": 0, "produzidas": 0, "montadas": 0})
        g["total"] += 1
        g["produzidas"] += 1 if fase >= 6 else 0
        g["montadas"] += 1 if fase >= 8 else 0
        lista.append({"tag": p.tag, "produto": p.produto, "situacao": situacao, "etapa": _ROTULO_FASE.get(fase)})

    produzidas = total - contagem["Em produção"]
    dados = {
        "success": True,
        "obra": {"codigo": obra.codigo_obra, "nome": obra.nome_obra, "cidade_uf": obra.cidade_uf, "status": obra.status},
        "total_pecas": total,
        "contagem": contagem,
        "fases": [{"numero": n, "etapa": _ROTULO_FASE[n], "pecas": fases.get(n, 0)} for n in range(1, 9)],
        "percentual_produzido": round(produzidas / total * 100, 1) if total else 0,
        "percentual_montado": round(contagem["Montada"] / total * 100, 1) if total else 0,
        "percentual_concluido": round(contagem["Montada"] / total * 100, 1) if total else 0,
        "peso_t": {k: round(v / 1000, 1) for k, v in peso.items()},
        "volume_m3": {k: round(v, 1) for k, v in volume.items()},
        "por_produto": [{"produto": k, **v} for k, v in sorted(por_produto.items())],
        "pecas": lista,
        "entregas": [{"codigo": r.codigo, "status": r.status, "data_expedicao": str(r.data_expedicao or ""), "data_entrega": str(r.data_entrega or "")[:10],
                      "peso_t": round((r.peso_total_kg or 0) / 1000, 1), "recebedor": r.recebedor_nome} for r in romaneios],
        "diario": _listar_diario(codigo_obra, 60),
        "em_fabricacao": contagem["Em produção"], "liberadas_patio": contagem["Produzida"],
        "em_transito": len([r for r in romaneios if r.status == "Despachado"]),
        "expedidas": contagem["Expedida"], "montadas": contagem["Montada"],
    }
    return _filtrar_portal(dados, cfg)


def _filtrar_portal(dados, cfg):
    """Tira do que sai para o cliente tudo o que o dono da obra desligou. O corte é no servidor."""
    sec = cfg["secoes"]
    saida = dict(dados)
    saida["secoes"] = sec
    saida["mensagem"] = cfg["mensagem"]
    if not sec["progresso"]:
        for k in ("percentual_produzido", "percentual_montado", "percentual_concluido"):
            saida[k] = None
    if not sec["pesos"]:
        saida["peso_t"] = None
        saida["volume_m3"] = None
    if not sec["situacao"]:
        for k in ("contagem", "em_fabricacao", "liberadas_patio", "em_transito", "expedidas", "montadas"):
            saida[k] = None
    if not sec["etapas"]:
        saida["fases"] = None
    if not sec["produtos"]:
        saida["por_produto"] = None
    if not sec["pecas"]:
        saida["pecas"] = None
    if not sec["entregas"]:
        saida["entregas"] = None
    diario = []
    if sec["diario"] or sec["fotos"]:
        for r in dados["diario"]:
            diario.append({**r, "resumo": r.get("resumo") if sec["diario"] else "", "fotos": r.get("fotos", []) if sec["fotos"] else []})
    saida["diario"] = diario if (sec["diario"] or sec["fotos"]) else None
    return saida


@endpoint(allow_guest=True)
def get_rg_publico(codigo_obra, t=None, tag=None):
    """Portal do cliente: o RG de uma peça da obra, sem dados internos. Só abre com o link válido e o dossiê ligado."""
    if not t or not hmac.compare_digest(str(t), _token_portal(codigo_obra)) or not frappe.db.exists('Obra', codigo_obra):
        return {"success": False, "error": "Link inválido ou expirado. Peça um novo link à empresa."}
    cfg = _config_portal(codigo_obra)
    if not cfg["ativo"] or not cfg["secoes"].get("dossie"):
        return {"success": False, "error": "O dossiê das peças não está disponível. Fale com a empresa."}
    codigo = frappe.db.get_value('Peca Pre-Moldada', {'obra': codigo_obra, 'tag': tag or ''}, 'name')
    if not codigo:
        return {"success": False, "error": "Peça não encontrada nesta obra."}
    from frappe.precast_qualidade import rg_publico
    return rg_publico(codigo)


@endpoint()
def abrir_nao_conformidade(codigo_peca, descricao, foto=None, aberto_por=None):
    """Melhoria 7: RNC com foto - abrir bloqueia a peça na expedição."""
    _exigir_papel("Produção", "Qualidade", "Direção")
    if not frappe.db.exists('Peca Pre-Moldada', codigo_peca):
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}

    doc = frappe.get_doc({
        "doctype": "Nao Conformidade", "codigo_peca": codigo_peca, "descricao": descricao,
        "foto": foto, "status": "Aberta", "aberto_por": aberto_por or frappe.session.user,
        "data_abertura": frappe.utils.now_datetime(),
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "name": doc.name, "message": "RNC aberta — peça bloqueada para expedição até aprovação do reparo."}


@endpoint()
def aprovar_nao_conformidade(name, receita_reparo=None):
    _exigir_papel("Qualidade", "Direção")
    if not frappe.db.exists('Nao Conformidade', name):
        return {"success": False, "error": "RNC não encontrada"}
    doc = frappe.get_doc('Nao Conformidade', name)
    doc.status = "Aprovada"
    doc.receita_reparo = receita_reparo or doc.receita_reparo
    doc.data_aprovacao = frappe.utils.now_datetime()
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "message": "RNC aprovada — peça liberada para expedição novamente."}


@endpoint()
def get_nao_conformidades(codigo_peca=None, status=None):
    filters = {}
    if codigo_peca:
        filters["codigo_peca"] = codigo_peca
    if status:
        filters["status"] = status
    rncs = frappe.get_all('Nao Conformidade', filters=filters,
        fields=['name', 'codigo_peca', 'descricao', 'foto', 'status', 'data_abertura', 'aberto_por'],
        order_by='data_abertura desc')
    return {"success": True, "nao_conformidades": rncs}


def _tem_rnc_aberta(codigo_peca):
    return bool(frappe.get_all('Nao Conformidade', filters={'codigo_peca': codigo_peca, 'status': ['!=', 'Aprovada']}, limit=1))


@endpoint()
def get_status_formas_pistas():
    """Melhoria 8/10: ciclo de vida das formas (giros) + OEE simplificado
    (tempo medio entre fases por forma, calculado do historico real)."""
    formas = frappe.get_all('Forma Pista', fields=['codigo', 'tipo', 'status', 'giros_realizados', 'giros_limite_manutencao'])
    for f in formas:
        f['precisa_manutencao'] = (f.giros_realizados or 0) >= (f.giros_limite_manutencao or 50)

        historico = frappe.get_all('Fase Historico', filters={'forma_pista': f.codigo},
            fields=['fase_nova', 'data_hora'], order_by='data_hora asc')
        if len(historico) >= 2:
            primeiro = frappe.utils.get_datetime(historico[0].data_hora)
            ultimo = frappe.utils.get_datetime(historico[-1].data_hora)
            horas_totais = (ultimo - primeiro).total_seconds() / 3600
            f['tempo_medio_ciclo_horas'] = round(horas_totais / max(len(historico) - 1, 1), 1)
        else:
            f['tempo_medio_ciclo_horas'] = None

    return {"success": True, "formas_pistas": formas}


@endpoint()
def estimar_carbono_peca(codigo_peca):
    """Melhoria 14: pegada de carbono estimada (ESG) por peça, a partir do
    consumo de cimento e aço ja calculados no orcador automatico."""
    if not frappe.db.exists('Peca Pre-Moldada', codigo_peca):
        return {"success": False, "error": f"Peça {codigo_peca} não encontrada"}

    FATOR_CO2_CIMENTO_KG = 0.83  # kg CO2 por kg de cimento CP (media setorial)
    FATOR_CO2_ACO_KG = 1.85  # kg CO2 por kg de aço CA-50 (media setorial)

    peca = frappe.get_doc('Peca Pre-Moldada', codigo_peca)
    orc = estimar_custo_peca(peca.produto, peca.volume_m3)

    co2_cimento = round(orc['cimento_kg'] * FATOR_CO2_CIMENTO_KG, 1)
    co2_aco = round(orc['peso_aco_kg'] * FATOR_CO2_ACO_KG, 1)
    co2_total_kg = round(co2_cimento + co2_aco, 1)

    return {
        "success": True, "codigo_peca": codigo_peca,
        "co2_cimento_kg": co2_cimento, "co2_aco_kg": co2_aco, "co2_total_kg": co2_total_kg,
        "co2_total_ton": round(co2_total_kg / 1000, 3),
        "nota": "Estimativa baseada em fatores médios setoriais (cimento e aço) — não inclui transporte."
    }


@endpoint()
def otimizar_corte_aco(comprimentos_necessarios, comprimento_barra=12.0):
    """Melhoria 16: nesting 1D - otimiza o corte de barras de aço (chegam
    com `comprimento_barra` metros da usina) pra minimizar sobra.
    Algoritmo first-fit-decreasing. `comprimentos_necessarios` e uma lista
    de comprimentos em metros (pode repetir)."""
    if isinstance(comprimentos_necessarios, str):
        comprimentos_necessarios = json.loads(comprimentos_necessarios)
    comprimento_barra = float(comprimento_barra)

    cortes = sorted([float(c) for c in comprimentos_necessarios if float(c) > 0], reverse=True)
    if not cortes:
        return {"success": False, "error": "Lista de cortes vazia"}
    if any(c > comprimento_barra for c in cortes):
        return {"success": False, "error": f"Existe corte maior que a barra de {comprimento_barra}m — não é possível atender."}

    from frappe.precast_corte import empacotar
    barras = [{"usado": b["usado"], "cortes": [c for _, c in b["cortes"]]}
              for b in empacotar([(i, c) for i, c in enumerate(cortes)], comprimento_barra)]

    total_consumido = len(barras) * comprimento_barra
    total_usado = sum(b["usado"] for b in barras)
    sobra_total = round(total_consumido - total_usado, 2)
    aproveitamento_pct = round((total_usado / total_consumido) * 100, 1) if total_consumido else 0

    return {
        "success": True, "barras_necessarias": len(barras), "comprimento_barra": comprimento_barra,
        "aproveitamento_pct": aproveitamento_pct, "sobra_total_m": sobra_total,
        "detalhe": [{"barra": i + 1, "cortes": b["cortes"], "usado_m": round(b["usado"], 2),
                     "sobra_m": round(comprimento_barra - b["usado"], 2)} for i, b in enumerate(barras)],
    }


@endpoint()
def confirmar_entrega_romaneio(codigo, assinatura_base64=None, recebedor_nome=None):
    """Melhoria 19: canhoto eletronico - confirma recebimento com
    assinatura na tela, sem depender de papel fisico."""
    _exigir_papel("Logística", "Direção")
    if not frappe.db.exists('Romaneio', codigo):
        return {"success": False, "error": "Romaneio não encontrado"}

    doc = frappe.get_doc('Romaneio', codigo)
    if doc.status != "Despachado":
        return {"success": False, "error": f"Romaneio precisa estar Despachado para confirmar entrega (está {doc.status})."}

    if assinatura_base64:
        import base64
        fname = f"assinatura_{codigo}.png"
        fpath = f"/home/frappe/frappe-bench/sites/frontend/public/files/{fname}"
        header_free = assinatura_base64.split(",", 1)[-1]
        with open(fpath, "wb") as f:
            f.write(base64.b64decode(header_free))
        doc.assinatura_recebedor = f"/files/{fname}"

    doc.recebedor_nome = recebedor_nome
    doc.data_entrega = frappe.utils.now_datetime()
    doc.status = "Entregue"
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"success": True, "message": "Entrega confirmada com canhoto eletrônico."}


# ============================================================
# Financeiro integrado: fluxo de caixa,
# funil comercial, RH e NF-e.
# ============================================================

@endpoint()
def get_resumo_financeiro():
    """Fluxo de caixa projetado + DRE simplificado, direto dos lançamentos
    reais do ERPNext (Sales Invoice / Purchase Invoice) — sem depender de
    relatório contábil configurado à parte."""
    _exigir_papel("Financeiro", "Direção")
    company = _default_company()
    hoje = frappe.utils.nowdate()

    receber = frappe.get_all("Sales Invoice",
        filters={"company": company, "docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "customer", "outstanding_amount", "due_date"])
    pagar = frappe.get_all("Purchase Invoice",
        filters={"company": company, "docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "supplier", "outstanding_amount", "due_date"])

    def _bucket(lancamentos):
        vencido = a_vencer_30 = a_vencer_60 = a_vencer_90_mais = 0.0
        for l in lancamentos:
            valor = l.outstanding_amount or 0
            dias = frappe.utils.date_diff(l.due_date, hoje) if l.due_date else 0
            if dias < 0:
                vencido += valor
            elif dias <= 30:
                a_vencer_30 += valor
            elif dias <= 60:
                a_vencer_60 += valor
            else:
                a_vencer_90_mais += valor
        return {"vencido": round(vencido, 2), "ate_30_dias": round(a_vencer_30, 2),
                "de_31_a_60_dias": round(a_vencer_60, 2), "acima_60_dias": round(a_vencer_90_mais, 2),
                "total": round(vencido + a_vencer_30 + a_vencer_60 + a_vencer_90_mais, 2)}

    receber_bucket = _bucket(receber)
    pagar_bucket = _bucket(pagar)

    inicio_mes = frappe.utils.get_first_day(hoje)
    faturamento_mes = frappe.db.sql("""
        select coalesce(sum(grand_total), 0) from `tabSales Invoice`
        where company=%s and docstatus=1 and posting_date >= %s
    """, (company, inicio_mes))[0][0]

    custo_producao_mes = frappe.db.sql("""
        select coalesce(sum(custo_estimado_peca), 0) from `tabPeca Pre-Moldada`
        where creation >= %s
    """, (inicio_mes,))[0][0]

    return {
        "success": True,
        "contas_a_receber": receber_bucket,
        "contas_a_pagar": pagar_bucket,
        "saldo_projetado_30_dias": round(receber_bucket["ate_30_dias"] - pagar_bucket["ate_30_dias"], 2),
        "dre_simplificado": {
            "faturamento_mes": round(float(faturamento_mes), 2),
            "custo_producao_estimado_mes": round(float(custo_producao_mes), 2),
            "resultado_bruto_estimado": round(float(faturamento_mes) - float(custo_producao_mes), 2),
        },
        "detalhe_receber": receber[:20],
        "detalhe_pagar": pagar[:20],
    }


@endpoint()
def criar_lead_comercial(nome, empresa=None, telefone=None, email=None, obra_interesse=None, fonte="Site"):
    """Melhoria: funil comercial (CRM) — cria um Lead de verdade no
    ERPNext, não só o registro informativo de contato."""
    if not nome:
        return {"success": False, "error": "Nome é obrigatório"}
    if fonte and not frappe.db.exists("UTM Source", fonte):
        frappe.get_doc({"doctype": "UTM Source"}).insert(ignore_permissions=True, set_name=fonte)
    doc = frappe.get_doc({
        "doctype": "CRM Lead" if frappe.db.exists("DocType", "CRM Lead") else "Lead",
        "lead_name": nome, "company_name": empresa, "email_id": email, "mobile_no": telefone,
        "utm_source": fonte, "status": "Lead",
    })
    doc.insert(ignore_permissions=True)
    if obra_interesse:
        try:
            doc.add_comment("Comment", f"Interesse: {obra_interesse}")
        except Exception:
            pass
    frappe.db.commit()
    return {"success": True, "lead": doc.name, "message": "Lead criado no funil comercial"}


@endpoint()
def converter_lead_em_oportunidade(lead_name):
    _exigir_papel("Comercial", "Direção")
    if not frappe.db.exists("Lead", lead_name):
        return {"success": False, "error": "Lead não encontrado"}
    lead = frappe.get_doc("Lead", lead_name)
    oportunidade = frappe.get_doc({
        "doctype": "Opportunity", "opportunity_from": "Lead", "party_name": lead_name,
        "company": _default_company(), "opportunity_type": "Sales", "status": "Open",
        "contact_email": lead.email_id, "customer_name": lead.company_name or lead.lead_name,
    })
    oportunidade.insert(ignore_permissions=True)
    lead.status = "Converted"
    lead.save(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "opportunity": oportunidade.name, "message": "Oportunidade criada a partir do lead"}


@endpoint()
def get_funil_comercial():
    _exigir_papel("Comercial", "Direção")
    leads = frappe.get_all("Lead", fields=["name", "lead_name", "company_name", "status", "utm_source", "creation"],
                            order_by="creation desc", limit_page_length=100)
    oportunidades = frappe.get_all("Opportunity", filters={"company": _default_company()},
        fields=["name", "party_name", "status", "opportunity_amount", "creation"],
        order_by="creation desc", limit_page_length=100)

    por_status = {}
    for l in leads:
        por_status.setdefault(l.status, 0)
        por_status[l.status] += 1

    return {
        "success": True, "leads": leads, "oportunidades": oportunidades,
        "total_leads": len(leads), "total_oportunidades": len(oportunidades),
        "leads_por_status": por_status,
    }


# ============================================================
# NF-e (Focus NFe) - integracao pronta, ativacao pendente
# ============================================================
# A Focus NFe eh o gateway ja escolhido nesta base (ver memoria do projeto
# erp-pre-moldados: "Integracao fiscal com Focus NFe"). Nao existe forma de
# emitir NF-e de verdade sem: 1) uma conta Focus NFe (ou outro gateway) com
# CNPJ homologado na SEFAZ, e 2) um certificado digital A1/A3 valido. Nada
# disso pode ser criado por aqui - por isso o token fica vazio ate o
# cliente configurar, e a funcao falha com erro claro em vez de fingir.

def _load_focus_nfe_token():
    """Le o token da Focus NFe do site_config.json (mecanismo nativo do
    Frappe pra secrets de site - vive dentro do container, nao no host).
    Vazio ate o cliente configurar: `bench --site frontend set-config
    focus_nfe_token "<token>"`."""
    return (frappe.conf.get("focus_nfe_token") or "").strip()


FOCUS_NFE_AMBIENTE_URL = "https://homologacao.focusnfe.com.br"  # homologacao ate ativar producao


@endpoint()
def emitir_nfe(sales_invoice_name):
    """Monta o payload da NF-e a partir da Sales Invoice real e envia pra
    Focus NFe (homologacao), ou direto pra SEFAZ via PyNFe se
    `nfe_metodo` estiver configurado como "pynfe". Sem token/certificado
    configurado, falha com erro claro - nunca finge sucesso."""
    _exigir_papel("Financeiro", "Direção")
    if _nfe_metodo() == "pynfe":
        return emitir_nfe_pynfe(sales_invoice_name)

    import requests

    token = _load_focus_nfe_token()
    if not token:
        return {
            "success": False,
            "error": "NF-e não configurada. Crie uma conta na Focus NFe (focusnfe.com.br), gere o token de homologação "
                     "e rode: bench --site frontend set-config focus_nfe_token \"<token>\". Também é necessário certificado "
                     "digital A1/A3 da empresa cadastrado lá antes de emitir de verdade.",
            "requer_configuracao": True,
        }

    if not frappe.db.exists("Sales Invoice", sales_invoice_name):
        return {"success": False, "error": "Fatura não encontrada"}

    invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
    customer = frappe.get_doc("Customer", invoice.customer)

    referencia = f"NFE-{invoice.name}"
    payload = {
        "natureza_operacao": "Venda de mercadoria",
        "data_emissao": frappe.utils.now_datetime().isoformat(),
        "tipo_documento": 1,
        "finalidade_emissao": 1,
        "cnpj_emitente": frappe.db.get_value("Company", _default_company(), "tax_id") or "",
        "nome_destinatario": customer.customer_name,
        "cpf_destinatario" if len(customer.get("tax_id") or "") <= 14 else "cnpj_destinatario":
            (customer.get("tax_id") or "").replace(".", "").replace("/", "").replace("-", ""),
        "items": [
            {
                "numero_item": idx + 1,
                "codigo_produto": item.item_code,
                "descricao": item.item_name or item.item_code,
                "cfop": "5102",
                "unidade_comercial": item.uom or "UN",
                "quantidade_comercial": item.qty,
                "valor_unitario_comercial": item.rate,
                "valor_bruto_produtos": item.amount,
                "unidade_tributavel": item.uom or "UN",
                "quantidade_tributavel": item.qty,
                "valor_unitario_tributavel": item.rate,
            }
            for idx, item in enumerate(invoice.items)
        ],
    }

    try:
        resp = requests.post(
            f"{FOCUS_NFE_AMBIENTE_URL}/v2/nfe?ref={referencia}",
            auth=(token, ""),
            json=payload,
            timeout=20,
        )
        resultado = resp.json()
    except Exception as e:
        return {"success": False, "error": f"Falha ao conectar com a Focus NFe: {e}"}

    doc = frappe.get_doc({
        "doctype": "Nota Fiscal", "sales_invoice": sales_invoice_name, "referencia": referencia,
        "status": resultado.get("status", "erro"), "numero_nf": resultado.get("numero"),
        "chave_acesso": resultado.get("chave_nfe"), "mensagem_erro": resultado.get("mensagem_sefaz") or resultado.get("erros"),
        "data_emissao": frappe.utils.now_datetime(), "ambiente": "Homologação",
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    if resp.status_code >= 400:
        return {"success": False, "error": resultado.get("mensagem") or resultado, "nota_fiscal": doc.name}

    return {"success": True, "nota_fiscal": doc.name, "status": resultado.get("status"),
            "message": "NF-e enviada para a SEFAZ (ambiente de homologação) — consulte o status em alguns segundos."}


@endpoint()
def consultar_nfe(referencia):
    _exigir_papel("Financeiro", "Direção")
    if _nfe_metodo() == "pynfe":
        return consultar_nfe_pynfe(referencia)

    import requests
    token = _load_focus_nfe_token()
    if not token:
        return {"success": False, "error": "NF-e não configurada (token ausente)."}
    try:
        resp = requests.get(f"{FOCUS_NFE_AMBIENTE_URL}/v2/nfe/{referencia}", auth=(token, ""), timeout=15)
        return {"success": True, "resultado": resp.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@endpoint()
def get_notas_fiscais(sales_invoice=None):
    _exigir_papel("Financeiro", "Direção")
    filters = {"sales_invoice": sales_invoice} if sales_invoice else {}
    notas = frappe.get_all("Nota Fiscal", filters=filters,
        fields=["name", "sales_invoice", "referencia", "status", "numero_nf", "chave_acesso", "mensagem_erro", "data_emissao"],
        order_by="data_emissao desc")
    return {"success": True, "notas_fiscais": notas}


# ============================================================
# NF-e via PyNFe (SEFAZ direto) - segundo metodo, sem gateway
# ============================================================
# PyNFe fala direto com a SEFAZ (sem Focus NFe nem qualquer mensalidade de
# terceiro). O unico custo que resta e o certificado digital e-CNPJ A1, que
# a lei exige de qualquer jeito - nenhum caminho de emissao escapa dele.
# Ate o certificado existir, `_pynfe_config()` retorna incompleto e as
# funcoes abaixo falham com erro claro, igual ao caminho da Focus NFe.
#
# Config (tudo via `bench --site frontend set-config <chave> "<valor>"`):
#   nfe_metodo               "focus" (padrao) ou "pynfe" - qual caminho usar
#   nfe_certificado_path      caminho do arquivo .pfx dentro do container
#   nfe_certificado_senha     senha do certificado A1
#   nfe_uf                    UF do emitente, ex "SP" (padrao SP)
#   nfe_homologacao           true/false (padrao true - ambiente de testes)
#   nfe_ie                    Inscricao Estadual da empresa (obrigatorio)
#   nfe_crt                   Codigo de Regime Tributario: 1=Simples Nacional
#                             (padrao), 2=Simples excesso sublimite, 3=Normal
#   nfe_cfop                  CFOP padrao dos itens (padrao "5102" venda)
#   nfe_ncm                   NCM padrao das pecas pre-moldadas (padrao
#                             "6810" - artefatos de concreto)
# O CSOSN/CST de ICMS e o CST de PIS/COFINS usados abaixo (102 e 49) sao o
# padrao usual de venda de mercadoria por empresa do Simples Nacional. Isso
# precisa ser revisado com o contador antes da primeira emissao real -
# nenhum software substitui essa checagem.

def _nfe_metodo():
    return (frappe.conf.get("nfe_metodo") or "focus").strip().lower()


def _pynfe_config():
    homologacao = frappe.conf.get("nfe_homologacao")
    return {
        "certificado_path": (frappe.conf.get("nfe_certificado_path") or "").strip(),
        "certificado_senha": (frappe.conf.get("nfe_certificado_senha") or "").strip(),
        "uf": (frappe.conf.get("nfe_uf") or "SP").strip().upper(),
        "homologacao": True if homologacao is None else bool(homologacao),
        "ie": (frappe.conf.get("nfe_ie") or "").strip(),
        "crt": (frappe.conf.get("nfe_crt") or "1").strip(),
        "cfop": (frappe.conf.get("nfe_cfop") or "5102").strip(),
        "ncm": (frappe.conf.get("nfe_ncm") or "6810").strip(),
    }


def _pynfe_config_pendencias(cfg):
    """Lista o que falta configurar. Vazio quando esta tudo pronto pra emitir."""
    faltando = []
    if not cfg["certificado_path"]:
        faltando.append("certificado digital (.pfx) - nfe_certificado_path")
    elif not os.path.isfile(cfg["certificado_path"]):
        faltando.append(f"arquivo do certificado não encontrado em {cfg['certificado_path']}")
    if not cfg["certificado_senha"]:
        faltando.append("senha do certificado - nfe_certificado_senha")
    if not cfg["ie"]:
        faltando.append("Inscrição Estadual da empresa - nfe_ie")
    if not frappe.db.get_value("Company", _default_company(), "tax_id"):
        faltando.append("CNPJ da empresa (cadastro da Company)")
    return faltando


def _endereco_padrao(link_doctype, link_name):
    """Endereco vinculado a um Company/Customer via Dynamic Link (padrao Frappe)."""
    rows = frappe.get_all(
        "Dynamic Link",
        filters={"link_doctype": link_doctype, "link_name": link_name, "parenttype": "Address"},
        fields=["parent"],
        limit=1,
    )
    return frappe.get_doc("Address", rows[0].parent) if rows else None


def _montar_emitente_pynfe(cfg):
    from pynfe.entidades.emitente import Emitente

    company = frappe.get_doc("Company", _default_company())
    endereco = _endereco_padrao("Company", _default_company())
    if not endereco:
        raise ValueError(f"A empresa '{_default_company()}' não tem endereço cadastrado (obrigatório na NF-e).")

    return Emitente(
        razao_social=company.company_name,
        nome_fantasia=company.company_name,
        cnpj=company.tax_id,
        inscricao_estadual=cfg["ie"],
        codigo_de_regime_tributario=cfg["crt"],
        endereco_logradouro=endereco.address_line1 or "",
        endereco_numero="S/N",
        endereco_complemento=endereco.address_line2 or "",
        endereco_bairro=endereco.city or "",
        endereco_cep=(endereco.pincode or "").replace("-", "").replace(".", ""),
        endereco_uf=(endereco.state or cfg["uf"])[:2].upper(),
        endereco_municipio=endereco.city or "",
        endereco_telefone=(endereco.phone or "").replace("(", "").replace(")", "").replace("-", "").replace(" ", ""),
    )


def _montar_cliente_pynfe(customer):
    from pynfe.entidades.cliente import Cliente

    endereco = _endereco_padrao("Customer", customer.name)
    if not endereco:
        raise ValueError(f"O cliente '{customer.customer_name}' não tem endereço cadastrado (obrigatório na NF-e).")

    documento = (customer.get("tax_id") or "").replace(".", "").replace("/", "").replace("-", "")
    return Cliente(
        razao_social=customer.customer_name,
        numero_documento=documento,
        indicador_ie=9,  # 9 = Nao Contribuinte (padrao pra consumidor final / obra)
        endereco_logradouro=endereco.address_line1 or "",
        endereco_numero="S/N",
        endereco_complemento=endereco.address_line2 or "",
        endereco_bairro=endereco.city or "",
        endereco_cep=(endereco.pincode or "").replace("-", "").replace(".", ""),
        endereco_pais="1058",
        endereco_uf=(endereco.state or "")[:2].upper(),
        endereco_municipio=endereco.city or "",
        endereco_telefone=(endereco.phone or "").replace("(", "").replace(")", "").replace("-", "").replace(" ", ""),
    )


def _montar_nota_fiscal_pynfe(invoice, cfg, numero_nf):
    from pynfe.entidades.notafiscal import NotaFiscal

    customer = frappe.get_doc("Customer", invoice.customer)
    emitente = _montar_emitente_pynfe(cfg)
    cliente = _montar_cliente_pynfe(customer)

    nota = NotaFiscal(
        modelo=55,
        serie="1",
        numero_nf=str(numero_nf),
        data_emissao=frappe.utils.now_datetime(),
        natureza_operacao="Venda de mercadoria",
        tipo_documento=1,  # saida
        finalidade_emissao=1,  # normal
        processo_emissao=0,
        forma_emissao="1",
        cliente_final=1,
        indicador_presencial=9,  # nao presencial / outros
        indicador_intermediador=0,
        indicador_destino=1 if cliente.endereco_uf == emitente.endereco_uf else 2,
        uf=emitente.endereco_uf,
        municipio=emitente.endereco_municipio,
        tipo_impressao_danfe=1,
        emitente=emitente,
        destinatario_remetente=cliente,
        produtos_e_servicos=[],
        transporte_volumes=[],
        transporte_modalidade_frete=9,  # sem frete
        duplicatas=[],
        observacoes_contribuinte=[],
        processos_referenciados=[],
        forma_pagamento=None,
    )

    for idx, item in enumerate(invoice.items):
        nota.adicionar_produto_servico(
            numero_item=str(idx + 1),
            codigo=item.item_code,
            descricao=item.item_name or item.item_code,
            ncm=cfg["ncm"],
            cfop=cfg["cfop"],
            unidade_comercial=item.uom or "UN",
            quantidade_comercial=item.qty,
            valor_unitario_comercial=item.rate,
            unidade_tributavel=item.uom or "UN",
            quantidade_tributavel=item.qty,
            valor_unitario_tributavel=item.rate,
            valor_total_bruto=item.amount,
            compoe_valor_total=1,
            # ICMS - CSOSN 102 (Simples Nacional, tributada sem credito)
            icms_modalidade="102" if cfg["crt"] == "1" else "40",
            icms_origem=0,
            icms_valor_base_calculo=0,
            icms_aliquota=0,
            icms_valor=0,
            # PIS/COFINS - CST 49 (fora do escopo, recolhido via DAS no Simples)
            pis_situacao_tributaria="49",
            pis_valor_base_calculo=0,
            pis_valor=0,
            cofins_situacao_tributaria="49",
            cofins_valor_base_calculo=0,
            cofins_valor=0,
        )

    nota.adicionar_pagamento(forma="90")  # 90 = sem pagamento (fatura ja emitida separadamente)
    return nota


@endpoint()
def testar_conexao_sefaz_pynfe():
    """Testa certificado + conectividade com a SEFAZ (status do servico), sem
    precisar de uma fatura real. Util pro cliente confirmar que o certificado
    comprado funciona antes da primeira emissao de verdade."""
    _exigir_papel("Financeiro", "Direção")
    cfg = _pynfe_config()
    pendencias = _pynfe_config_pendencias(cfg)
    if pendencias:
        return {"success": False, "error": "Configuração incompleta: " + "; ".join(pendencias), "requer_configuracao": True}

    try:
        from pynfe.entidades.certificado import CertificadoA1
        from pynfe.processamento.comunicacao import ComunicacaoSefaz
        from pynfe.utils.webservices import NFE

        certificado = CertificadoA1(caminho_arquivo=cfg["certificado_path"])
        comunicacao = ComunicacaoSefaz(cfg["uf"], certificado, cfg["certificado_senha"], homologacao=cfg["homologacao"])
        resp = comunicacao.status_servico(NFE, timeout=20)
        return {"success": True, "status_code": resp.status_code, "resposta": resp.text[:2000]}
    except Exception as e:
        return {"success": False, "error": f"Falha ao conectar com a SEFAZ: {e}"}


@endpoint()
def emitir_nfe_pynfe(sales_invoice_name):
    """Emite a NF-e direto na SEFAZ via PyNFe (sem gateway/mensalidade).
    Sem certificado configurado, falha com erro claro - nunca finge sucesso."""
    _exigir_papel("Financeiro", "Direção")
    cfg = _pynfe_config()
    pendencias = _pynfe_config_pendencias(cfg)
    if pendencias:
        return {
            "success": False,
            "error": "NF-e (PyNFe) não configurada: " + "; ".join(pendencias) + ". Compre o certificado e-CNPJ A1, "
                     "salve o .pfx no servidor e rode: bench --site frontend set-config nfe_certificado_path \"<caminho>\" "
                     "e nfe_certificado_senha \"<senha>\".",
            "requer_configuracao": True,
        }

    if not frappe.db.exists("Sales Invoice", sales_invoice_name):
        return {"success": False, "error": "Fatura não encontrada"}

    invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
    from frappe.model.naming import getseries
    numero_nf = getseries("NFE-PYNFE-", 6)
    referencia = f"NFE-{invoice.name}"

    try:
        from pynfe.entidades.certificado import CertificadoA1
        from pynfe.entidades.fonte_dados import _fonte_dados
        from pynfe.processamento.assinatura import AssinaturaA1
        from pynfe.processamento.comunicacao import ComunicacaoSefaz
        from pynfe.processamento.serializacao import SerializacaoXML
        from pynfe.utils.webservices import NFE

        nota = _montar_nota_fiscal_pynfe(invoice, cfg, numero_nf)

        xml_nota = SerializacaoXML(_fonte_dados, homologacao=cfg["homologacao"]).exportar(retorna_string=False)[0]

        certificado = CertificadoA1(caminho_arquivo=cfg["certificado_path"])
        xml_assinado = AssinaturaA1(certificado, cfg["certificado_senha"]).assinar(xml_nota)

        comunicacao = ComunicacaoSefaz(cfg["uf"], certificado, cfg["certificado_senha"], homologacao=cfg["homologacao"])
        resp = comunicacao.autorizacao(modelo=NFE, nota_fiscal=xml_assinado)
    except Exception as e:
        return {"success": False, "error": f"Falha ao emitir via PyNFe/SEFAZ: {e}"}

    sucesso = isinstance(resp, tuple) and resp[0] is not None
    doc = frappe.get_doc({
        "doctype": "Nota Fiscal", "sales_invoice": sales_invoice_name, "referencia": referencia,
        "status": "autorizado" if sucesso else "erro_autorizacao",
        "numero_nf": str(numero_nf), "chave_acesso": nota.identificador_unico.replace("NFe", "") if hasattr(nota, "identificador_unico") else None,
        "mensagem_erro": None if sucesso else str(resp),
        "data_emissao": frappe.utils.now_datetime(),
        "ambiente": "Homologação" if cfg["homologacao"] else "Produção",
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    if not sucesso:
        return {"success": False, "error": str(resp), "nota_fiscal": doc.name}

    return {"success": True, "nota_fiscal": doc.name, "numero_nf": str(numero_nf),
            "message": "NF-e autorizada direto na SEFAZ (PyNFe) — sem gateway."}


@endpoint()
def consultar_nfe_pynfe(chave_acesso):
    _exigir_papel("Financeiro", "Direção")
    cfg = _pynfe_config()
    pendencias = _pynfe_config_pendencias(cfg)
    if pendencias:
        return {"success": False, "error": "NF-e (PyNFe) não configurada: " + "; ".join(pendencias)}

    try:
        from pynfe.entidades.certificado import CertificadoA1
        from pynfe.processamento.comunicacao import ComunicacaoSefaz
        from pynfe.utils.webservices import NFE

        certificado = CertificadoA1(caminho_arquivo=cfg["certificado_path"])
        comunicacao = ComunicacaoSefaz(cfg["uf"], certificado, cfg["certificado_senha"], homologacao=cfg["homologacao"])
        resp = comunicacao.consulta_nota(modelo=NFE, chave=chave_acesso)
        return {"success": True, "status_code": resp.status_code, "resposta": resp.text[:3000]}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# Backup diario automatico + alerta
# ============================================================
def backup_diario_com_alerta():
    """Roda todo dia (hook em scheduler_events.daily_long) - faz backup
    completo (banco + arquivos), criptografado com a chave do site, e avisa
    por WhatsApp se der certo ou se falhar. Sem isso, um problema de
    infraestrutura só seria percebido quando alguém precisasse restaurar."""
    from frappe.utils.backups import new_backup

    empresa = _default_company() or frappe.local.site
    try:
        backup = new_backup(ignore_files=False, force=True)
        tamanho_mb = round((os.path.getsize(backup.backup_path_db) if backup.backup_path_db else 0) / (1024 * 1024), 1)
        _enviar_whatsapp(
            _whatsapp_config()["numero_admin"],
            f"✅ Backup diário ok — {empresa}\nBanco: {tamanho_mb} MB\nData: {frappe.utils.now_datetime().strftime('%d/%m/%Y %H:%M')}",
        )
    except Exception as e:
        frappe.log_error(title="Falha no backup diário", message=str(e))
        _enviar_whatsapp(
            _whatsapp_config()["numero_admin"],
            f"🚨 Falha no backup diário — {empresa}\nErro: {e}\nVerifique o servidor.",
        )


