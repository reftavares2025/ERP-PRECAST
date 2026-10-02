;;; =========================================================================
;;; RBR ENGENHARIA / ERP INDUSTRIAL DE PRÉ-FABRICADOS (NBR 9062)
;;; Módulo: Extração e Isolamento Autêntico de Prancha (DWG + PDF)
;;; =========================================================================

(vl-load-com)

(defun c:RBR_EXTRAIR_PRANCHA (/ *error* old_cmdecho old_filedia old_cmddia
                               pt1 pt2 ss cod_peca dir_obra dwg_out pdf_out
                               pmin pmax ll ur lay_cur)

  ;; Tratamento de Erros e Restauração de Variáveis
  (defun *error* (msg)
    (if old_cmdecho (setvar "CMDECHO" old_cmdecho))
    (if old_filedia (setvar "FILEDIA" old_filedia))
    (if old_cmddia  (setvar "CMDDIA"  old_cmddia))
    (if (not (wcmatch (strcase msg t) "*break*,*cancel*,*exit*"))
      (princ (strcat "\n[ERRO RBR]: " msg))
    )
    (princ)
  )

  ;; Salva variáveis de sistema do AutoCAD
  (setvar "EXPERT" 5)
  (setq old_cmdecho (getvar "CMDECHO"))
  (setq old_filedia (getvar "FILEDIA"))
  (setq old_cmddia  (getvar "CMDDIA"))

  (setvar "CMDECHO" 0)
  (setvar "FILEDIA" 0)
  (setvar "CMDDIA"  0)

  (princ "\n=== RBR ERP: ISOLADOR DE PRANCHAS DE FABRICAÇÃO ===")

  ;; 1. Solicitação do Código da Peça e Diretório de Saída
  (setq cod_peca (getstring "\nIdentificador/Código da Peça (Ex: PIL-01, VIG-12): "))
  (if (= cod_peca "") (setq cod_peca "PECA_SEM_CODIGO"))

  ;; Diretório atual do desenho como base para a pasta /output
  (setq dir_obra (getvar "DWGPREFIX"))
  (setq dwg_out (strcat dir_obra cod_peca "_PRANCHA.dwg"))
  (setq pdf_out (strcat dir_obra cod_peca "_PRANCHA.pdf"))

  ;; 2. Seleção da Janela da Prancha (Ponto Inferior Esquerdo e Superior Direito)
  (initget 1)
  (setq pt1 (getpoint "\nSelecione o Canto 1 da Moldura da Prancha: "))
  (initget 1)
  (setq pt2 (getcorner pt1 "\nSelecione o Canto Oposto da Moldura: "))

  ;; Converte coordenadas para World Coordinate System (WCS)
  (setq pt1 (trans pt1 1 0))
  (setq pt2 (trans pt2 1 0))

  ;; Garante Ponto Mínimo e Máximo corretos
  (setq pmin (list (min (car pt1) (car pt2)) (min (cadr pt1) (cadr pt2)) 0.0))
  (setq pmax (list (max (car pt1) (car pt2)) (max (cadr pt1) (cadr pt2)) 0.0))

  ;; 3. Seleção dos Objetos contidos na Janela (Crossing Window)
  (setq ss (ssget "_C" pmin pmax))

  (if (not ss)
    (progn
      (princ "\n[ERRO]: Nenhum elemento encontrado dentro da moldura especificada.")
      (*error* "Seleção vazia")
    )
  )

  ;; 4. EXPORTAÇÃO DO DWG LIMPO (WBLOCK)
  (if (findfile dwg_out)
    (vl-file-delete dwg_out) ; Remove versão anterior para não travar
  )

  (princ (strcat "\n[1/2] Gravando DWG Isolado: " dwg_out "..."))
  
  ;; Chama WBLOCK passando Ponto Base (PMin), Arquivo de Destino e Seleção
  (vl-cmdf "_.-WBLOCK" dwg_out "" pmin ss "")
  
  ;; O WBLOCK apaga a seleção no desenho ativo por padrão; desfazemos imediatamente em memória:
  (vl-cmdf "_.OOPS")

  ;; 5. PLOTAGEM DIRETA PARA PDF AUTÊNTICO (DWG to PDF.pc3)
  (princ (strcat "\n[2/2] Gerando PDF Autêntico da Prancha: " pdf_out "..."))

  ;; Configuração do comando -PLOT em linha de comando (Sem janelas)
  (vl-cmdf "_.-PLOT"
           "Y"                              ; Configuração detalhada? [Yes]
           "Model"                          ; Nome do Layout [Model]
           "DWG To PDF.pc3"                 ; Nome da Plotadora / Impressora
           "ISO_full_bleed_A1_(841.00_x_594.00_MM)" ; Formato da Folha
           "M"                              ; Unidade do desenho [Millimeters]
           "L"                              ; Orientação [Landscape/Paisagem]
           "N"                              ; Inverter plotagem? [No]
           "W"                              ; Área de plotagem [Window/Janela]
           pmin                             ; Canto 1 WCS
           pmax                             ; Canto 2 WCS
           "F"                              ; Escala [Fit / Ajustar ou "1=1"]
           "C"                              ; Centro da plotagem [Center]
           "Y"                              ; Plotar com estilos de traço? [Yes]
           "monochrome.ctb"                 ; Tabela de Estilo de Penas (CTB)
           "Y"                              ; Plotar espessura de linhas (lineweights)? [Yes]
           "N"                              ; Plotagem sombreada (Shaded)? [No]
           pdf_out                          ; Nome do Arquivo de Saída PDF
           "N"                              ; Salvar alterações na configuração? [No]
           "Y"                              ; Prosseguir com a plotagem? [Yes]
  )

  ;; Restaura configurações de sistema
  (setvar "CMDECHO" old_cmdecho)
  (setvar "FILEDIA" old_filedia)
  (setvar "CMDDIA"  old_cmddia)

  (princ "\n=======================================================")
  (princ (strcat "\n[SUCESSO] Prancha isolada com sucesso!"))
  (princ (strcat "\nDWG da Peça : " dwg_out))
  (princ (strcat "\nPDF Original: " pdf_out))
  (princ "\nArquivos prontos para ingestão no TrueQR e ERP Plannix.")
  (princ "\n=======================================================\n")
  (princ)
)

;; Função de Extração Automática Paramétrica (Batch / Headless para o ERP)
(defun RBR_EXTRAIR_AUTO (cod_peca x1 y1 x2 y2 dwg_out pdf_out / *error* pmin pmax ss)
  (defun *error* (msg) (princ (strcat "\n[ERRO AUTO]: " msg)) (princ))
  (setvar "CMDECHO" 0)
  (setvar "FILEDIA" 0)
  (setvar "EXPERT" 5)

  (setq pmin (list (min x1 x2) (min y1 y2) 0.0))
  (setq pmax (list (max x1 x2) (max y1 y2) 0.0))

  (setq ss (ssget "_C" pmin pmax))
  (if (not ss) (setq ss (ssget "_X")))

  (if (findfile dwg_out) (vl-file-delete dwg_out))
  (if (findfile pdf_out) (vl-file-delete pdf_out))

  (if ss
    (progn
      ;; 1. WBLOCK DWG
      (vl-cmdf "_.-WBLOCK" dwg_out "" pmin ss "")
      (vl-cmdf "_.OOPS")

      ;; 2. PLOT PDF
      (vl-cmdf "_.-PLOT" "Y" "Model" "DWG To PDF.pc3" "ISO_full_bleed_A1_(841.00_x_594.00_MM)" "M" "L" "N" "W" pmin pmax "F" "C" "Y" "monochrome.ctb" "Y" "N" pdf_out "N" "Y")
    )
  )
  (princ "\n[OK AUTO EXPORTED]")
  (princ)
)

(princ "\nRotina RBR_EXTRAIR_PRANCHA carregada com sucesso. Digite RBR_EXTRAIR_PRANCHA para rodar.")
(princ)
