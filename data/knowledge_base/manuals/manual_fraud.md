# Manual Operacional NexusTech: Fraud

### Tentativa de Phishing

**Contexto e Sintomas:** O cliente recebeu um e-mail não solicitado simulando "NexusTech Support", com remetente desconhecido e link solicitando credenciais de acesso ao ERP. O cliente não interagiu nem forneceu dados, mas identificou a tentativa de phishing ao notar domínio inconsistente e ausência de assinatura digital oficial. O problema envolve risco potencial de exposição de credenciais e acesso não autorizado ao ambiente corporativo.

**Resolução N1 (Autoatendimento e Políticas):** No painel do ERP NexusTech, o cliente deve acessar o menu lateral "Segurança e Compliance" → "Alertas de Phishing" e clicar em "Registrar Tentativa de Phishing", selecionando "Remetente Bloqueado". Política N1: Alterar imediatamente credenciais pelo módulo "Minhas Credenciais" e ativar autenticação de dois fatores (2FA). SLA: Confirmação de bloqueio em até 24 horas úteis. Custo: Nenhuma cobrança adicional para ação de autoatendimento. O N1 nunca acessa logs ou bancos de dados; todas as ações são autônomas pelo portal do cliente.

**Critério de Escalonamento (N2 / N3):** Transfira para N2 (Backoffice) se o cliente clicar no link, inserir credenciais ou houver relato de mais de 3 usuários da mesma empresa sobre o mesmo domínio suspeito. Transfira para N3 (Engenharia/Segurança) se o e-mail contiver anexo malicioso, domínio oficial da NexusTech for falsificado com intenção de fraude financeira, ou houver indício de comprometimento de sistema. N3 conduz análise forense e bloqueio de domínio junto a provedores. Regra absoluta: qualquer dado sensível exposto dispara N3 imediatamente.

### Cartao Roubado

**Contexto e Sintomas:** O cliente relata que seu cartão de crédito foi utilizado em transações no site da NexusTech sem sua autorização, indicando possível clonagem ou roubo. O sintoma principal é a aparição de cobranças desconhecidas no extrato do cartão, correspondendo a compras realizadas na plataforma, das quais o cliente não tem memória ou consentimento. Não há indicação de falha técnica no site, mas de uso indevido de dados de pagamento. O cliente deve verificar o histórico de transações em sua conta NexusTech e comparar com o extrato bancário para identificar a operação ilícita.

**Resolução N1 (Autoatendimento e Políticas):** O cliente deve acessar o painel da NexusTech, navegar até 'Minha Conta' → 'Histórico de Transações', selecionar a operação suspeita e clicar em 'Relatar Fraude' ou 'Contestar Cobrança'. O N1 nunca lê logs ou acessa bancos de dados; a orientação é guiar o cliente para o formulário de disputa automática. SLA: reconhecimento em 24h úteis e análise preliminar em 72h. Taxa zero para disputas de fraude comprovada. Limite de reembolso assistido pelo N1: R$ 1.000,00. Sem acesso ao painel? Direcione ao chat institucional para verificação de perfil.

**Critério de Escalonamento (N2 / N3):** Transferir para N2 (Backoffice) quando o cliente anexar comprovante de boletim de ocorrência ou comprovação de roubo/clonagem, ou quando a transação ultrapassar R$ 500,00 sem identificação do dispositivo. Transferir para N3 (Engenharia/Segurança) se houver padrão de múltiplas fraudes no mesmo período, suspeita de brecha de sistema ou requisição de bloqueio de merchant específico. N2 trata documentação, reembolso provisório e comunicação com instituições financeiras. N3 realiza análise forense, bloqueio de IPs/accounts e atualização de regras de segurança do sistema.

### Conta Invadida

**Contexto e Sintomas:** O cliente relata que sua conta NexusTech foi acessada por terceiros não autorizados, resultando em transações financeiras não reconhecidas. O problema se manifesta por alterações inesperadas de dados de contato, cobranças inexplicáveis no extrato e bloqueio temporário de acesso seguro. O cliente solicita ação imediata para impedir novos débitos e proteger seus dados.

**Resolução N1 (Autoatendimento e Políticas):** No painel da NexusTech, o cliente deve acessar 'Segurança' → 'Minha Conta' → 'Proteção contra Fraude' e selecionar 'Bloquear Conta Imediatamente'. O bloqueio é automático e ocorre em até 5 minutos. Política vigente: contas bloqueadas por fraude têm 24 horas para recuperação mediante envio de documento de identidade e selfie com data atual. SLA de segurança: 5 minutos para ativação do bloqueio. N1 nunca consulta logs ou bancos de dados; a ação é executada por regras de segurança configuradas no painel. Se o botão não estiver disponível, verifique se o e-mail cadastrado está validado.

**Critério de Escalonamento (N2 / N3):** Escalonamento N2: transfira para o Backoffice se o cliente não conseguir bloquear a conta via painel N1, se houver necessidade de reversão de transações já processadas ou se solicitar relatório detalhado de movimentações. SLA N2: resposta inicial em até 4 horas. Escalonamento N3: transfira para Engenharia/Segurança se houver indícios de vulnerabilidade sistêmica, falha no mecanismo automático de bloqueio ou padrão de fraude coordenada. SLA N3: análise técnica em até 24 horas. N1 nunca encaminha casos diretamente para N3 sem passar por N2.

### Dispositivo Desconhecido

**Contexto e Sintomas:**  
O cliente identifica, no painel de sessões ativas do ERP NexusTech, um dispositivo desconhecido conectado à sua conta. O sintoma é a presença de um equipamento não reconhecido na lista de logins ativos, o que pode indicar acesso não autorizado ou sessão remanescente. O cliente não consegue identificar o nome, IP ou tipo do dispositivo, gerando preocupação sobre segurança da conta.

**Resolução N1 (Autoatendimento e Políticas):**  
O cliente deve acessar o módulo "Segurança" no painel do ERP NexusTech e selecionar "Minhas Sessões Ativas". Em seguida, localizar o dispositivo desconhecido e clicar em "Desconectar" ou "Remover Sessão". Política SLA: ação de remoção de dispositivo não autorizado deve ser concluída em até 15 minutos após identificação. Não há custo adicional para o cliente; a operação é gratuita e não requer acesso a logs ou backend pelo atendente N1, seguindo a política de autoatendimento de primeira linha.

**Critério de Escalonamento (N2 / N3):**  
Transferir para N2 (Backoffice) se: o cliente não conseguir remover o dispositivo via painel após 2 tentativas, ou identificar mais de 3 dispositivos desconhecidos simultâneos, ou solicitar análise forense básica de sessões. Transferir para N3 (Engenharia/Segurança) se: houver indícios de padrão de ataque coordenado, dispositivo com endereço MAC/IP suspeito fora da região de atuação do cliente, ou violação de compliance regulatório de dados. Regra exata: N1 encaminha para N2 após 2 falhas consecutivas de remoção autoatendida.

### Alerta de Seguranca

**Contexto e Sintomas:** Cliente recebe notificação de alerta de segurança no painel do ERP NexusTech informando sobre um login originário da Rússia. O cliente afirma não ter realizado esse acesso, indicando possível tentativa de entrada não autorizada ou comprometimento de credenciais. O sistema de monitoramento de segurança detectou a atividade fora do padrão geográfico habitual do usuário, acionando notificação automática. O problema reside na necessidade de validação da autenticidade do login e adoção de medidas de proteção imediatas para evitar acesso não autorizado à conta corporativa.

**Resolução N1 (Autoatendimento e Políticas):** O cliente deve acessar o módulo "Segurança" no painel do ERP NexusTech e selecionar a opção "Não foi eu" no alerta de login internacional. Caso o alerta persista, o sistema bloqueia temporariamente o acesso por 30 minutos conforme SLA de segurança padrão. Políticas exigem troca de senha dentro de 15 minutos após confirmação de acesso não autorizado, com obrigatoriedade de autenticação em dois fatores (2FA) na próxima sessão. O N1 não acessa logs ou bancos de dados; a resolução é totalmente guiada pelo painel do cliente, com tempo máximo de 5 minutos para conclusão.

**Critério de Escalonamento (N2 / N3):** Caso o cliente confirme acesso não autorizado ou informe duas ou mais tentativas de login de países de risco em um período de 24 horas, o caso deve ser transferido imediatamente para o N2 (Backoffice) para verificação de atividade suspeita e bloqueio temporário da conta. Se houver indícios de comprometimento sistêmico, vazamento de credenciais em massa ou padrão de ataque coordenado, escalonar para o N3 (Engenharia/Segurança) dentro de 1 hora, com relatório forense obrigatório. O N2 não realiza análise de logs profundos; o N3 atua com ferramentas de bloqueio de IP e atualização de regras de firewall.

### Transacao Suspeita

**Contexto e Sintomas:** O cliente acessa o painel do ERP NexusTech e visualiza a mensagem "Suspicious activity detected on my billing history" ou cobranças não reconhecidas no histórico de faturamento. Sintomas incluem transações com status inédito, valores alterados sem autorização ou cobranças de serviços não contratados. Este cenário pertence à categoria Fraud/Transacao Suspeita e requer verificação imediata pela interface de autoatendimento, sem que o N1 acesse logs ou bancos de dados.

**Resolução N1 (Autoatendimento e Políticas):** No N1, o cliente deve navegar até o menu principal 'Faturamento', depois submenu 'Histórico de Transações' e localizar a aba 'Alertas de Segurança'. Se a transação aparecer com status 'Em Análise', o cliente clica em 'Confirmar Autorização' usando validação 2FA. Política SLA: resolução automática em até 24 horas após confirmação do cliente. Valores: revisão de autorização é gratuita (R$ 0,00); reabertura manual após 24h incorre taxa de R$ 25,00. O N1 nunca consulta logs ou bancos de dados; todas as ações são guiadas por regras de negócio configuradas no painel.

**Critério de Escalonamento (N2 / N3):** Escalonamento para N2 (Backoffice) ocorre quando: valor da transação > R$ 5.000,00; cliente não confirmar a autorização dentro de 24h; ou padrão de múltiplas transações suspeitas (>3 em 1 hora). Em casos de flag do sistema 'High Risk Fraud' ou suspeita de vazamento de dados, o N1 deve transferir imediatamente para N3 (Engenharia/Segurança). Regra de ouro: N1 resolve sozinho transações únicas de baixo valor com confirmação do cliente; qualquer flag sistêmica ou valor acima do limite dispara encaminhamento automático para N2 ou N3 conforme critério acima.
