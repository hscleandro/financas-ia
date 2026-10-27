# Finanças IA Web — Especificação de requisitos para agente implementador

**Versão:** 1.0 (escopo funcional acordado em 27/10/2026)  
**Projeto existente:** https://github.com/hscleandro/financas-ia  
**Estado:** pronto para iniciar inspeção do repositório e implementação, sujeito às verificações técnicas descritas abaixo.

## 1. Instruções ao agente implementador

Você é o agente responsável por implementar a primeira versão web do projeto Finanças IA. **Antes de editar código**, examine a arquitetura, os modelos, as migrações, os testes, os serviços e as convenções do repositório. Não presuma nomes de tabelas, endpoints, tecnologias ou campos não verificados. Reutilize o backend, a base de dados e os serviços existentes sempre que possível. Não interrompa o bot do Telegram nem crie um banco financeiro paralelo.

Implemente incrementalmente, com testes. Se encontrar ambiguidades que impeçam uma implementação correta, registre-as explicitamente e solicite decisão em vez de inventar regras financeiras. As regras de negócio abaixo prevalecem sobre sugestões técnicas.

## 2. Objetivo e escopo

Criar uma aplicação web responsiva, para celular e desktop, integrada ao banco de dados existente do Finanças IA na AWS, com:

1. **Dashboard inicial de despesas**, alimentado pelos dados já existentes.
2. **Importação de fatura PDF do cartão Bradesco**, seleção de lançamentos do titular desejado, conciliação com despesas de cartão de crédito já registradas via Telegram e revisão antes da gravação.
3. **Entrada de navegação “Importar extrato bancário”**, visualmente presente, identificada como “Em breve”, mas sem upload funcional nem backend nesta versão.

**Fora do escopo da V1:** processamento de extratos, conciliação de Pix/débito, dashboards de receitas, entradas/saídas e saldo consolidado. Receitas podem existir no banco, mas não devem ser implementadas no dashboard V1.

## 3. Dashboard de despesas

A tela inicial deve apresentar gráficos/indicadores de despesas, utilizando a estrutura e classificações já existentes no banco:

- Total de despesas no período selecionado.
- Despesas por categoria.
- Despesas por tipo/forma de pagamento (cartão de crédito, Pix e outros tipos existentes).
- Evolução temporal dos gastos.

A conciliação de fatura restringe-se a cartão de crédito, **mas o dashboard pode exibir todas as formas de pagamento**. Respeitar nomenclaturas reais de campos e categorias do projeto. Não inventar categorias. Interface responsiva.

## 4. Importação da fatura e filtragem por titular

- Permitir envio de arquivo PDF de fatura do Bradesco.
- Ler os lançamentos e metadados relevantes: titular, identificação mascarada do cartão, data, descrição do estabelecimento, valor em centavos e indicação de parcela quando houver.
- Uma mesma fatura pode conter transações de mais de um titular (usuário e esposa). **Somente os lançamentos do titular/cartão selecionado participam da conciliação V1**.
- Exemplo fornecido pelo usuário: titular **Leandro Henrique Santos Corrêa**, cartão com final **3006**. Esses valores são exemplos, **não constantes fixas no código**. A identificação do titular/cartão deve ser configurável ou selecionável.
- Se não for possível associar com segurança um lançamento a um titular/cartão, não incluí-lo automaticamente na conciliação: sinalizar para revisão.
- Suportar lançamentos parcelados: **cada parcela presente na fatura é um lançamento daquele mês**. O usuário não pretende cadastrar manualmente essas parcelas via Telegram.
- Preservar referência à fatura/importação e informações necessárias para auditoria e prevenção de reprocessamento.

## 5. Conjunto elegível do banco

Consultar **apenas despesas classificadas como cartão de crédito**, relativas ao cartão/titular correspondente e ao período pertinente à fatura. Não comparar nem excluir Pix, débito ou outras modalidades. Verificar no esquema real como identificar forma de pagamento, titular e cartão. Caso o banco não possua vínculo confiável por cartão, sinalizar a lacuna e propor uma estratégia de configuração/identificação sem assumir que todo gasto em cartão pertence ao titular selecionado.

## 6. Regra de correspondência

Candidatos à conciliação devem satisfazer:

- **Mesmo valor exato em centavos**.
- **Diferença de datas de no máximo ±2 dias**, inclusive, entre a data da compra na fatura e a data cadastrada no banco.
- **Correspondência estritamente 1:1**: um lançamento da fatura pode corresponder no máximo a um registro do banco e vice-versa.
- Descrição do estabelecimento não é critério obrigatório de igualdade: o texto digitado no Telegram pode divergir do nome na fatura.

Quando houver múltiplos candidatos com mesmo valor e datas próximas, apresentá-los para escolha/revisão; **não aplicar associação 1:N ou N:1**. Nunca reutilizar o mesmo registro em mais de uma correspondência aprovada. Uma sugestão de correspondência não é confirmação definitiva.

## 7. Interface de conciliação: três seções separadas

Após ler a fatura e filtrar o titular, mostrar as seguintes seções/abas ou painéis:

### A. Só na fatura
Lançamentos da fatura sem correspondência aprovada no banco. Mostrar dados relevantes da fatura. **Pré-selecionar para inserção**; permitir desmarcar individualmente. Inserir somente os selecionados após confirmação final.

### B. Na fatura e no banco
Pares candidatos ou confirmados entre fatura e banco. Mostrar lado a lado as informações de ambas as fontes, especialmente data, valor e descrição. Permitir marcar/desmarcar e resolver ambiguidades 1:1. Para correspondências aprovadas, **não inserir duplicata**; atualizar no registro existente a **data** e a **descrição do estabelecimento** com os valores da fatura. Preservar outros campos existentes, salvo necessidade técnica explicitamente validada.

### C. Só no banco
Despesas elegíveis de cartão de crédito sem correspondência na fatura. Exibir para revisão e permitir ao usuário **aprovar explicitamente exclusões**. Não excluir registros de Pix/débito nem registros de outro cartão/titular ou fora do período pertinente. Não excluir registros automaticamente durante a leitura.

As três seções devem permitir revisão antes de qualquer mutação. O usuário poderá ver os dados extraídos da fatura e os resultados da conciliação de forma separada e clara.

## 8. Confirmação e persistência

- **Nenhuma inserção, atualização ou exclusão ocorre ao carregar o PDF ou ao marcar/desmarcar opções**.
- Disponibilizar uma ação final única: **“Confirmar conciliação”**.
- Ao confirmar, executar apenas as ações aprovadas: inserções de A, atualizações de B e exclusões aprovadas de C.
- Revalidar as correspondências 1:1 e as condições de elegibilidade antes de persistir.
- Garantir consistência transacional: evitar estado parcialmente aplicado se ocorrer falha. Usar transação quando compatível com o armazenamento real; caso contrário, implementar estratégia segura de recuperação/idempotência.
- Impedir duplicidade ao reenviar a mesma fatura ou repetir a confirmação. Não presumir que data + valor isoladamente identificam uma transação única.
- Registrar resultados da operação e apresentar ao usuário um resumo de inseridos, atualizados, excluídos, ignorados e erros.
- Para exclusões, preservar rastreabilidade e respeitar os padrões existentes no repositório; confirmar a estratégia técnica (exclusão lógica ou física) antes de implementá-la se não houver convenção estabelecida.

## 9. Tratamento de erros e segurança

- Validar PDF, leitura, valores, datas, cabeçalhos de titular e lançamentos incompletos.
- Quando a extração for ambígua, **não inventar dados nem executar ações destrutivas**; sinalizar os itens e exigir revisão.
- Tratar corretamente valores monetários em centavos, datas locais e eventuais estornos/créditos de fatura conforme os padrões reais identificados; se a regra não estiver definida, destacar a pendência.
- Proteger a interface e as operações financeiras conforme os mecanismos de autenticação/autorização do projeto. Não expor credenciais nem dados financeiros em logs públicos.
- A interface deve ser utilizável em telas móveis.

## 10. Critérios de aceite mínimos

1. Dashboard exibe despesas reais agrupadas por categoria, forma de pagamento e período, sem incluir receitas na V1.
2. Upload de PDF Bradesco identifica titulares/cartões e permite processar somente o titular escolhido.
3. Compras da esposa não entram na conciliação do cartão selecionado.
4. Pix e débito não entram na comparação nem são candidatos à exclusão.
5. Mesmo valor e datas com diferença de 0, 1 ou 2 dias geram candidatos; diferença de 3 dias não gera.
6. Valores distintos não geram correspondência, mesmo com datas iguais.
7. Dois registros de R$ 50 na mesma data não são fundidos nem ligados automaticamente ao mesmo lançamento.
8. Cada correspondência aprovada é 1:1; conflitos são bloqueados e apresentados para resolução.
9. Registro existente aprovado não é duplicado; sua data e descrição passam a refletir a fatura somente após a confirmação final.
10. Lançamentos apenas na fatura aparecem pré-marcados, podem ser desmarcados e são inseridos somente após a confirmação.
11. Registros apenas no banco são mostrados e só são excluídos mediante seleção/aprovação e confirmação final.
12. Nenhuma mutação acontece durante o upload ou revisão.
13. Reenvio da mesma fatura ou repetição de confirmação não gera duplicatas nem alterações indevidas.
14. Parcelas constantes da fatura são tratadas como lançamentos daquele mês.
15. Menu “Importar extrato bancário” aparece como “Em breve”, sem backend/upload funcional.
16. Bot do Telegram continua operando sem regressões.

## 11. Sequência sugerida de implementação

1. Inspecionar o repositório e documentar o mapeamento real entre modelos, banco, categorias, serviços e APIs.
2. Construir ou adaptar consultas de despesas e dashboard responsivo.
3. Implementar parser de fatura e seleção de titular/cartão; criar testes com amostras anonimizadas.
4. Implementar motor de correspondência 1:1 com tolerância ±2 dias e classificação nas três seções.
5. Implementar interface de revisão e resolução de conflitos.
6. Implementar confirmação única, validação, idempotência, rastreabilidade e persistência segura.
7. Adicionar entrada visual “Importar extrato bancário — Em breve”.
8. Executar testes automatizados, regressão do bot e validação ponta a ponta.

## 12. Pendências que o agente deve verificar, não presumir

- Esquema efetivo da base de dados e identificação de titular/cartão em despesas já existentes.
- Formato exato e variações do PDF Bradesco; a imagem fornecida na conversa era parcial e não substitui um PDF de teste.
- Como determinar o período pertinente à fatura (datas de compra versus ciclo de fechamento), especialmente para a seção “Só no banco”.
- Semântica de estornos, pagamentos, tarifas e créditos, se presentes.
- Convenção atual de exclusão física/lógica e mecanismo transacional do banco.
- Comportamento preciso de itens desmarcados na seção B: **não alterar** até que sejam aprovados; não inferir exclusão ou inserção automática a partir de uma rejeição.
- Autenticação e hospedagem da aplicação web de acordo com a infraestrutura existente.

**Princípio norteador:** fatura do cartão selecionado é a fonte da verdade para lançamentos de cartão de crédito do ciclo analisado; toda alteração no banco depende de revisão e confirmação explícita do usuário.


## 13. Hospedagem e disponibilização web na AWS (requisito adicional)

O projeto existente já opera continuamente na AWS para atender ao bot do Telegram. O usuário acredita utilizar **Amazon Lightsail** (nome do serviço a confirmar no ambiente real). A aplicação Finanças IA Web deverá, **preferencialmente**, ser hospedada na infraestrutura AWS já contratada, evitando custos e serviços adicionais desnecessários.

**Instruções obrigatórias ao agente:**

1. Inspecionar a configuração atual de implantação (instância Lightsail ou outro serviço AWS), sistema operacional, serviços/processos do bot, portas, proxy reverso, DNS, containers, certificados e recursos disponíveis. Não presumir que o código estar no GitHub significa que ele está hospedado lá ou que o servidor tem capacidade livre.
2. Avaliar se a mesma instância pode servir a aplicação web e sua API **sem prejudicar a disponibilidade 24/7 do bot Telegram**. Considerar CPU, RAM, disco, portas, reinício, logs, backup e segurança.
3. Se for viável, reutilizar a instância, expondo a aplicação por uma **URL HTTPS acessível pelo navegador**, com servidor web/proxy reverso e processos independentes do bot. A URL pode usar domínio/subdomínio configurado pelo usuário; não inventar um domínio existente.
4. Configurar HTTPS/TLS, autenticação e autorização para proteger informações financeiras. Não expor diretamente banco de dados, credenciais, serviços internos ou endpoints administrativos à internet.
5. Planejar execução persistente e reinicialização automática dos serviços, além de deploy e rollback sem interrupção indevida do Telegram.
6. Documentar as etapas de configuração, variáveis de ambiente, DNS, certificado, firewall, deploy, atualização e manutenção, seguindo as convenções já adotadas no repositório.
7. Se a instância atual não suportar o app com segurança ou desempenho aceitável, apresentar alternativas AWS e estimativa de custo **antes** de provisionar novos recursos. Não contratar nem alterar infraestrutura de produção sem autorização.

**Critérios de aceite adicionais:** aplicação web acessível por URL HTTPS autenticada; bot Telegram permanece funcional; dados e credenciais protegidos; instruções de deploy reproduzíveis; ausência de custos novos sem aprovação.

**Observação:** a viabilidade de hospedar ambos na mesma instância é uma hipótese a verificar, não uma garantia.
