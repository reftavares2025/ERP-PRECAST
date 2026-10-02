# 🏗️ SISTEMA ERP PRÉ-FABRICADO (RBR OpenPrecast ERP)

Plataforma de Gestão Industrial e Rastreabilidade 100% Automatizada para a Indústria de Concreto Pré-Fabricado (NBR 9062).

---

## 📁 Estrutura de Pastas do Projeto

```
C:\SISTEMA ERP PRÉ-FABRICADO\
├── 📂 cad_engine/          # Motor Parser de Arquivos DWG/DXF (Extração Automática de Peças e Aço)
├── 📂 backend/             # APIs REST, Microsserviços e Banco de Dados Cloud
├── 📂 frontend/            # Interface Web & PWA Offline-First (Next.js / React)
├── 📂 zpl/                 # Gerador de Etiquetas Térmicas ZPL (Zebra) com 8 Fases Selecionáveis
├── 📂 docs/                # Documentação do Projeto, Diagramas e Especificações Técnicas
└── 📂 uploads_dwg/         # Diretório para recepção e processamento de DWGs dos projetos
```

---

## 🚀 Funcionalidades Principais

1. **Leitura Automática de DWG/DXF:** Upload do projeto sem necessidade de digitação manual de peças.
2. **Arquitetura Nuvem + Offline-First:** Sincronização automática via PWA quando houver internet.
3. **Vínculo das Pranchas em PDF:** Acesso ao detalhamento técnico de cada peça diretamente na tela/tablet do encarregado.
4. **Etiqueta ZPL com 8 Fases:** Quadradinhos `[X]` marcados automaticamente por bipagem QR Code.
5. **Rastreabilidade por Setor:** Apontamento em tempo real por operador logado em cada etapa da fábrica.
6. **Dashboard Executivo:** Painel de controle com funil de peças em tempo real.
