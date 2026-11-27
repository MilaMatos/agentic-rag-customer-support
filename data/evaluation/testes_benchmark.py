import json
from pathlib import Path

# (categoria, subcategoria, pergunta_en, pergunta_pt, nivel_escalonamento)
CATALOGO_BILINGUE = [
    # Account
    ("Account", "Falha no 2FA", "2FA is not working, I don't get the code.", "O 2FA não está funcionando, não recebo o código.", "N1"),
    ("Account", "Perda de Dispositivo 2FA", "I need to change my email address, but the 2FA is linked to my old phone.", "Preciso alterar meu e-mail, mas o 2FA está vinculado ao meu celular antigo.", "N1"),
    ("Account", "Redefinicao de Senha", "I forgot my password and the reset link is expired.", "Esqueci minha senha e o link de redefinição expirou.", "N1"),
    ("Account", "Upgrade Enterprise", "How can I upgrade my subscription to the Enterprise plan?", "Como faço upgrade da minha assinatura para o plano Enterprise?", "N1"),
    ("Account", "Foto de Perfil", "How do I update my profile picture?", "Como eu atualizo a minha foto de perfil?", "N1"),
    ("Account", "Exclusao de Conta", "Please delete my account and all associated data immediately.", "Por favor, exclua minha conta e todos os dados associados imediatamente.", "N1"),
    # Billing
    ("Billing", "Status de Reembolso", "I requested a refund 5 days ago, where is it?", "Solicitei um reembolso há 5 dias, qual é o status?", "N1"),
    ("Billing", "Atualizacao de Pagamento", "Payment method update failed. I cannot add my new Visa card.", "A atualização do método de pagamento falhou. Não consigo adicionar meu novo cartão Visa.", "N1"),
    ("Billing", "Divergencia na Fatura", "The invoice amount is higher than the agreed contract.", "O valor da fatura veio mais alto do que o contrato acordado.", "N1"),
    ("Billing", "Segunda Via de Fatura", "Can you send me the invoice for transaction #99283?", "Vocês podem me enviar a segunda via da fatura da transação #99283?", "N1"),
    ("Billing", "Cancelamento e Renovacao", "My subscription renewed automatically, but I wanted to cancel.", "Minha assinatura renovou automaticamente, mas eu queria cancelar.", "N1"),
    ("Billing", "Cobranca Duplicada", "I was charged twice for the same month. Here is the receipt.", "Fui cobrado duas vezes no mesmo mês. Aqui está o comprovante.", "N1"),
    # Technical
    ("Technical", "Falha de Sincronizacao", "Syncing data between mobile and desktop is failing.", "A sincronização de dados entre o celular e o desktop está falhando.", "N1"),
    ("Technical", "Erro 500 no Login", "I am getting Error 500 when trying to log in, even after resetting my password.", "Estou recebendo Erro 500 ao tentar fazer login, mesmo após redefinir minha senha.", "N1"),
    ("Technical", "Travamento do Dashboard", "The dashboard is not loading any data, just a spinning wheel.", "O painel não está carregando nenhum dado, fica só uma bolinha girando.", "N1"),
    ("Technical", "Integracao de API", "API returns 500 Internal Server Error when fetching user list.", "A API retorna erro 500 Internal Server Error ao buscar a lista de usuários.", "N1"),
    ("Technical", "Instalacao de Patch", "I cannot install the latest patch on Windows 11.", "Não consigo instalar o patch mais recente no Windows 11.", "N1"),
    ("Technical", "Fechamento nas Configuracoes", "The app crashes every time I open the settings tab.", "O aplicativo fecha sozinho toda vez que abro a aba de configurações.", "N1"),
    # Fraud
    ("Fraud", "Tentativa de Phishing", "I received a phishing email pretending to be your support team.", "Recebi um e-mail de phishing se passando pela equipe de suporte de vocês.", "N1"),
    ("Fraud", "Cartao Roubado", "My credit card was used on your site without my permission, it was stolen.", "Meu cartão de crédito foi usado no site de vocês sem minha permissão, ele foi roubado.", "N1"),
    ("Fraud", "Conta Invadida", "My account was hacked! Someone made transactions I didn't authorize. Block it now!", "Minha conta foi invadida! Alguém fez transações que não autorizei. Bloqueiem agora!", "N1"),
    ("Fraud", "Dispositivo Desconhecido", "There is an unrecognized device logged into my account.", "Há um dispositivo desconhecido conectado na minha conta.", "N1"),
    ("Fraud", "Alerta de Seguranca", "I got a security alert notification about a login from Russia, it wasn't me.", "Recebi um alerta de segurança sobre um login vindo da Rússia, não fui eu.", "N1"),
    ("Fraud", "Transacao Suspeita", "Suspicious activity detected on my billing history.", "Atividade suspeita detectada no meu histórico de faturamento.", "N1"),
    # General Inquiry
    ("General Inquiry", "Horario de Atendimento", "What are your hours of operation for phone support?", "Qual é o horário de funcionamento do suporte por telefone?", "N1"),
    ("General Inquiry", "Endereco da Sede", "Where is your main office located?", "Onde fica localizado o escritório principal de vocês?", "N1"),
    ("General Inquiry", "Desconto para ONGs", "Do you offer discounts for non-profit organizations?", "Vocês oferecem descontos para organizações sem fins lucrativos?", "N1"),
    ("General Inquiry", "Roadmap de Produto", "Is there a roadmap for new features coming this year?", "Existe um roadmap com os novos recursos previstos para este ano?", "N1"),
    ("General Inquiry", "Solicitacao de Demo", "I would like to request a live demo for my team.", "Gostaria de solicitar uma demonstração ao vivo para a minha equipe.", "N1"),
    ("General Inquiry", "Planos e Precos", "How do the pricing tiers work for teams?", "Como funcionam os planos e faixas de preço para equipes?", "N1"),
]

CASOS_ESCALONAMENTO_E_BORDA = [
    ("EDGE-01", "Fraud", "pt", "Eu tentei seguir os passos para bloquear minha conta invadida, mas o botão 'Bloquear Conta Imediatamente' não aparece no meu painel de jeito nenhum, e meu e-mail já tá validado!", "N2"),
    ("EDGE-02", "Account", "pt", "Perdi meu celular com o autenticador 2FA e também não tenho mais aqueles códigos de recuperação. Como entro na conta?", "N2"),
    ("EDGE-03", "Billing", "pt", "Estou tentando atualizar meu cartão de crédito no painel, mas o sistema diz 'Cartão Rejeitado' sendo que eu acabei de ligar no banco e eles disseram que tá tudo certo lá.", "N2"),
    ("EDGE-04", "Fraud", "pt", "Recebi um e-mail de vocês pedindo para redefinir a senha e cliquei no link, mas achei a URL meio estranha depois. Acho que caí num golpe de phishing.", "N2"),
    ("EDGE-05", "Account", "pt", "Tenho duas contas separadas com e-mails diferentes e queria saber se é possível mesclar (merge) as duas em um único login.", "N2"),
    ("EDGE-06", "Billing", "pt", "Minha nota fiscal saiu com o CNPJ errado, preciso que vocês cancelem e emitam uma nova urgente para a contabilidade não travar o pagamento.", "N2"),
    ("EDGE-07", "Technical", "en", "I'm trying to export my reports to CSV, but the file downloaded is completely empty. PDF export works fine though.", "N2"),
    ("EDGE-08", "General Inquiry", "pt", "Vocês possuem algum programa de parcerias para agências ou sistema de afiliados (white-label) que eu possa revender a plataforma?", "N2"),
]


def gerar() -> None:
    casos = []
    for idx, (cat, sub, en, pt, nivel) in enumerate(CATALOGO_BILINGUE, start=1):
        casos.append({
            "id_teste": f"CAN-EN-{idx:02d}",
            "grupo": "canonico",
            "idioma": "en",
            "categoria": cat,
            "subcategoria": sub,
            "pergunta": en,
            "esperado": {"nivel_escalonamento": nivel},
        })
        casos.append({
            "id_teste": f"CAN-PT-{idx:02d}",
            "grupo": "canonico",
            "idioma": "pt",
            "categoria": cat,
            "subcategoria": sub,
            "pergunta": pt,
            "esperado": {"nivel_escalonamento": nivel},
        })

    for cid, cat, idioma, pergunta, nivel in CASOS_ESCALONAMENTO_E_BORDA:
        casos.append({
            "id_teste": cid,
            "grupo": "borda_n2",
            "idioma": idioma,
            "categoria": cat,
            "subcategoria": "Escalonamento/Fora de Escopo",
            "pergunta": pergunta,
            "esperado": {"nivel_escalonamento": nivel},
        })

    destino = Path("data/evaluation/testes_benchmark.json")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(casos, f, indent=2, ensure_ascii=False)

    print(f"Dataset gerado com {len(casos)} casos em: {destino.resolve()}")


if __name__ == "__main__":
    gerar()