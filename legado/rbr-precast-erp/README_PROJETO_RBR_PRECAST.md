# 🏗️ RBR OpenPrecast ERP • Sistema Único Integrado NBR 9062

Plataforma Industrial de Gestão de Elementos Pré-Fabricados de Concreto, Rastreabilidade TrueQR™ e Parser Automatizado de Pranchas DXF/DWG integrada diretamente ao **ERPNext v16**.

---

## 🌐 Painéis e Acessos do Sistema

| Módulo / Interface | URL de Acesso | Descrição |
| :--- | :--- | :--- |
| **🏭 Terminal Chão de Fábrica** | `http://localhost:5050` | Leitor QR Code por Câmera (Vídeo ao Vivo) + Pistola USB, Baixa Automática, Identificação de Operador e Funil Industrial. |
| **💼 ERPNext Core (Gestão Total)** | `http://localhost:8088` | ERP Corporativo em **Português (Brasil)**. Usuário: `Administrator` / Senha: `admin`. |
| **📋 Peças Pré-Moldadas** | `http://localhost:8088/app/peca-pre-moldada` | Lista com as 88 peças reais da obra, volumes $m^3$, pesos em toneladas e emissão de etiquetas. |
| **⚡ Importador de Projetos DXF** | `http://localhost:8088/app/importador-de-projeto-dxf` | Leitor de arquivos DXF até 500MB com extração automática de vigas, pilares e lajes. |
| **📊 Histórico de Rastreabilidade** | `http://localhost:8088/app/apontamento-rastreabilidade` | Auditoria completa de quem bipou, qual peça, data, hora e controle de qualidade (CQ). |

---

## 📁 Estrutura de Arquivos no SSD (`C:\RBR_PRECAST_ERP\`)

```
C:\RBR_PRECAST_ERP\
├── 📂 backups/                  # Backups compactados do banco MariaDB e arquivos do ERPNext
│   ├── 20260923_001713-frontend-database.sql.gz
│   ├── 20260923_001713-frontend-files.tar
│   └── 20260923_001713-frontend-site_config_backup.json
├── 📂 cad_engine/               # Motor Python de leitura e extração geométrica DXF/DWG (ezdxf)
│   └── dxf_parser.py
├── 📂 trueqr_engine/            # Criptografia SHA-256 anti-fraude e gerador ZPL para Zebra
│   └── engine.py
├── 📂 operator_station/         # Interface Web do Terminal de Produção (HTML5 / QR Camera Scanner)
│   └── index.html
├── cad_importer_engine.py       # Módulo integrado no backend do ERPNext para processamento CAD
├── terminal_engine.py           # API REST do Terminal de Bipagem conectado ao MariaDB
├── create_print_format.py       # Gerador do layout de impressão da Etiqueta Térmica NBR 9062
├── server.py                    # Servidor local do Terminal de Fábrica (Porta 5050)
└── README_PROJETO_RBR_PRECAST.md# Documentação geral do sistema
```

---

## 🏷️ Etiqueta Térmica NBR 9062 (Zebra / PDF)

Formato oficial de etiqueta criado no ERPNext (`100x75mm`):
- Tag da Peça em destaque (`P-01`, `V-01`, `L-01`)
- Obra, Tipo de Elemento, Volume ($m^3$), Peso ($t$), Seção e $f_{ck}$ ($35\text{ MPa}$)
- QR Code TrueQR 2D com Hash criptográfico
- Matriz com os Checkboxes das 8 Fases:
  1. *Corte e Dobra de Aço*
  2. *Armação Estrutural*
  3. *Fôrmas & Embutidos*
  4. *Concretagem*
  5. *Cura & Desmolde*
  6. *Acabamento & CQ*
  7. *Expedição & Pátio*
  8. *Execução na Obra*

---

## 🚀 Como Iniciar / Retomar o Sistema

1. **Garantir que o Docker Desktop está aberto.**
2. **Subir a stack do ERPNext (se necessário):**
   ```powershell
   cd D:\erpnext-pre-fabricado
   docker compose -f pwd.yml up -d
   ```
3. **Iniciar o Terminal de Produção:**
   ```powershell
   cd C:\RBR_PRECAST_ERP
   python server.py
   ```
4. **Acessar:**
   - Terminal: `http://localhost:5050`
   - ERPNext: `http://localhost:8088`
