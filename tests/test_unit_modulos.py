import pytest
from src.rag.retriever import NexusRetriever
from src.agents.prompts.redactor import construir_prompt_redator
from src.agents.prompts.auditor import construir_prompt_auditor
from src.agents.parsers import separar_mensagem_e_fonte, extrair_json_auditoria

class TestUnitarioParsersEPrompts:
    """Testes unitários rápidos (sem chamada de LLM ou banco) para validar contratos."""

    def test_fatiamento_chunk_completo(self):
        texto_manual = (
            "### Conta Invadida\n"
            "**Contexto e Sintomas:** Cliente relata invasão.\n"
            "**Resolução N1 (Autoatendimento e Políticas):** Clique em Bloquear Conta.\n"
            "**Critério de Escalonamento (N2 / N3):** Transferir para N2 se falhar."
        )
        fatias = NexusRetriever._fatiar_conteudo(texto_manual)

        assert fatias["sintomas"] == "Cliente relata invasão."
        assert fatias["resolucao_n1"] == "Clique em Bloquear Conta."
        assert fatias["escalonamento"] == "Transferir para N2 se falhar."

    def test_separar_mensagem_e_fonte_oculta(self):
        resposta_llm = (
            "<think>Pensamento interno</think>\n"
            "Olá! Acesse o painel para resolver.\n\n"
            "[[FONTE: MAN-TECH-001-SEC-03]]"
        )
        resultado = separar_mensagem_e_fonte(resposta_llm)

        assert resultado["fonte_citada"] == "MAN-TECH-001-SEC-03"
        assert "[[FONTE:" not in resultado["mensagem_cliente"]
        assert "<think>" not in resultado["mensagem_cliente"]
        assert resultado["mensagem_cliente"] == "Olá! Acesse o painel para resolver."

    def test_separar_mensagem_sem_fonte_retorna_nao_citada(self):
        resposta_llm = "Olá! Esqueci de colocar a tag no final."
        resultado = separar_mensagem_e_fonte(resposta_llm)

        assert resultado["fonte_citada"] == "NÃO_CITADA"

    def test_prompt_redator_fora_de_escopo(self):
        # Quando o Retriever não acha nada (score < 0.30), envia lista vazia []
        prompts = construir_prompt_redator(
            pergunta_cliente="Me dê uma receita de bolo de chocolate.",
            chunks_fatiados=[],
        )
        assert "FORA_DE_ESCOPO" in prompts["user_prompt"]

    def test_prompt_auditor_fora_de_escopo(self):
        prompts = construir_prompt_auditor(
            pergunta_cliente="Qual a previsão do tempo?",
            resposta_redator="Vou transferir para um especialista. [[FONTE: FORA_DE_ESCOPO]]",
            chunks_fatiados=[],
        )
        assert "[FORA_DE_ESCOPO]" in prompts["user_prompt"]

    def test_extrair_json_auditoria_com_markdown_sujo(self):
        saida_suja = (
            "Aqui está o laudo:\n"
            "```json\n"
            '{"analise_raciocinio": "Ok", "aprovado_para_envio": true, '
            '"redator_alucinou": false, "citou_fonte": true, '
            '"nivel_escalonamento": "N1", "feedback_correcao": ""}\n'
            "```"
        )
        dados = extrair_json_auditoria(saida_suja)
        assert dados["aprovado_para_envio"] is True
        assert dados["nivel_escalonamento"] == "N1"