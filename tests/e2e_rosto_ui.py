"""Entrada pelo rosto no celular (/bipar), com o reconhecimento facial de verdade rodando no navegador.
Usa uma foto pública de exemplo com três pessoas (baixada na primeira execução) e recorta o rosto de cada uma."""
import json, os, sys, tempfile, time, urllib.request
import requests
from PIL import Image
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
FOTO = "https://raw.githubusercontent.com/vladmandic/face-api/master/demo/sample3.jpg"
PASTA = os.path.join(tempfile.gettempdir(), "precast_rosto_teste")
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


os.makedirs(PASTA, exist_ok=True)
origem = os.path.join(PASTA, "grupo.jpg")
if not os.path.exists(origem):
    urllib.request.urlretrieve(FOTO, origem)
img = Image.open(origem).convert("RGB")
k = img.width / 900.0
caixas = {"ana": (200, 100, 480, 370), "bia": (470, 60, 690, 300), "caio": (650, 100, 870, 320)}
arquivos = {}
for nome, (a, b, c, d) in caixas.items():
    for sufixo, margem, escala in (("", 25, 0.8), ("_2", 45, 1.0)):  # duas fotos da mesma pessoa, enquadramentos diferentes
        r = img.crop((max(0, int((a - margem) * k)), max(0, int((b - margem) * k)), int(c * k), min(img.height, int((d + margem) * k))))
        arquivos[nome + sufixo] = os.path.join(PASTA, f"{nome}{sufixo}.jpg")
        r.resize((int(r.width * escala), int(r.height * escala))).save(arquivos[nome + sufixo], quality=88)

adm = requests.Session()
adm.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    return adm.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo).json().get("message", {})


def limpar():
    for o in api("listar_rostos").get("operadores", []):
        if o["nome"].startswith("Teste Rosto"):
            api("gerir_rosto", usuario=o["usuario"], acao="remover")


limpar()
api("gerir_rosto", acao="zerar_tentativas")
api("gerir_rosto", acao="cadastro_aberto", aberto=True)


GESTOS = {"Olhe de frente": {"yaw": 0.01, "boca": 0.04, "largura_boca": 0.38}, "Vire a cabeça": {"yaw": 0.30, "boca": 0.04, "largura_boca": 0.36},
          "Agora vire": {"yaw": -0.30, "boca": 0.04, "largura_boca": 0.36}, "Sorria": {"yaw": 0.0, "boca": 0.10, "largura_boca": 0.46},
          "Abra bem": {"yaw": 0.0, "boca": 0.32, "largura_boca": 0.38}}

# Sem câmera ao vivo (como numa página http no celular): o desafio vem em uma foto por passo. O reconhecimento do rosto é
# o de verdade; só as medidas do gesto são trocadas, porque uma foto de exemplo não gira a cabeça nem sorri sob comando.
PREPARO = """
Object.defineProperty(navigator, 'mediaDevices', { value: undefined });
window.__simular = %s;
window.addEventListener('load', () => {
  const GESTOS = %s;
  const esperar = setInterval(() => {
    if (!window.analisarQuadro) return;
    clearInterval(esperar);
    const real = window.analisarQuadro;
    window.analisarQuadro = async (f, d) => {
      const q = await real(f, d);
      if (q.erro || !window.__simular) return q;
      const texto = document.getElementById('rostoFotoTexto').textContent;
      const chave = Object.keys(GESTOS).find(k => texto.includes(k));
      if (chave) q.metricas = GESTOS[chave];
      return q;
    };
  }, 50);
});
"""


def entrar(pw, nome, setor, foto, esperar, simular=True, consente=True):
    ctx = pw.chromium.launch(channel="chrome").new_context(viewport={"width": 420, "height": 850})
    pg = ctx.new_page()
    pg.add_init_script(PREPARO % ("true" if simular else "false", json.dumps(GESTOS)))
    pg.goto(URL + "/bipar", wait_until="domcontentloaded"); pg.wait_for_selector("#telaRosto", state="visible", timeout=20000)
    pg.wait_for_function("!!window.analisarQuadro || true")
    pg.fill("#rostoNome", nome); pg.select_option("#rostoSetor", setor)
    if consente:
        pg.check("#rostoConsentimento")
    pg.click("#rostoIniciar")
    passos, fim = 0, time.time() + 240
    while time.time() < fim:
        if pg.locator("#rostoFotoBtn").is_visible():
            pg.evaluate("window.analisarQuadro = window.analisarQuadro; 0")
            pg.set_input_files("#rostoFoto", arquivos[foto]); passos += 1
            pg.wait_for_timeout(1500 if passos == 1 else 400)
            if not simular and passos >= 2:
                pg.wait_for_timeout(3000); break
        msg = pg.inner_text("#rostoMsg")
        if msg.startswith(("Cadastro feito", "Olá")) or "vinculado" in msg or msg.startswith(("Os passos", "A verificação", "O rosto", "Não ")) or "termo de consentimento" in msg:
            break
        pg.wait_for_timeout(300)
    msg = pg.inner_text("#rostoMsg")
    pg.wait_for_timeout(2500)
    liberou = not pg.locator("#telaRosto").is_visible()
    pg.context.browser.close()
    return msg, liberou, passos


with sync_playwright() as pw:
    print("[Foto parada não passa na prova de vida]")
    msg, liberou, passos = entrar(pw, "Teste Rosto Ana", "Armação", "ana", False, simular=False)
    ok("uma foto comum não cumpre os gestos pedidos", not liberou and "não mostra o gesto" in msg and passos >= 2, f"{passos} passos | {msg}")
    print("[Cadastro sem aceitar o termo]")
    msg, liberou, passos = entrar(pw, "Teste Rosto Eva", "Cura", "caio", False, consente=False)
    ok("sem marcar o termo, o cadastro novo é recusado e o termo abre", not liberou and "termo" in msg.lower(), f"{passos} passos | {msg}")
    print("[Primeiro acesso]")
    msg, liberou, passos = entrar(pw, "Teste Rosto Ana", "Armação", "ana", True)
    ok("rosto + nome + setor + gestos: cadastra e entra", "Cadastro feito" in msg and liberou and passos == 4, f"{passos} passos | {msg}")
    print("[Voltando com outra foto da mesma pessoa]")
    msg, liberou, _ = entrar(pw, "Teste Rosto Ana", "Armação", "ana_2", True)
    ok("reconhece a mesma pessoa em outra foto", ("Olá" in msg) and liberou, msg)
    print("[Outro setor]")
    msg, liberou, _ = entrar(pw, "Teste Rosto Ana", "Forma", "ana_2", False)
    ok("mesma pessoa em outro setor é barrada", "já está vinculado" in msg.lower() or "vinculado" in msg and not liberou, msg)
    ok("barrada continua na tela de entrada", not liberou)
    print("[Outra pessoa]")
    msg, liberou, _ = entrar(pw, "Teste Rosto Bia", "Forma", "bia", True)
    ok("outra pessoa se cadastra em outro setor", "Cadastro feito" in msg and liberou, msg)
    msg, liberou, _ = entrar(pw, "Teste Rosto Bia", "Forma", "bia_2", True)
    ok("e é reconhecida depois", "Olá" in msg and liberou, msg)

mapa = {o["nome"]: o["setores"] for o in api("listar_rostos")["operadores"]}
ok("a gestão mostra cada pessoa no seu setor", mapa.get("Teste Rosto Ana") == ["Armação"] and mapa.get("Teste Rosto Bia") == ["Forma"], str(mapa))
limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
