# Revisao de conciliacao

A tela reutiliza a aplicacao FastAPI, o parser Bradesco, as despesas do bot e o
catalogo de categorias existentes. A referencia visual e
`docs/financas_ia_conciliacao_descricoes_telegram.html`; esse prototipo nao e
modificado nem usado para armazenar dados reais.

## Operacoes

- Os tres cards filtram os itens pendentes. A selecao pertence a aba atual.
- **So na fatura:** aprovar insere a despesa com uma categoria cadastrada.
- **Conciliados:** aprovar confirma o vinculo, preservando as descricoes,
  datas e valores originais dos dois registros.
- **So no banco:** aprovar registra a revisao sem criar outra despesa.
- **Ignorar:** registra a decisao, sem inserir, alterar ou excluir despesas.
- Alteracoes de categoria sao salvas como rascunho. Para registros existentes,
  a categoria somente e aplicada a despesa ao aprovar, com auditoria.
- Cada lote usa uma unica transacao. Uma falha desfaz todas as decisoes do lote;
  a interface conserva a selecao e apresenta o erro.

A regra central permanece valor exato em centavos e diferenca de ate dois dias,
com pareamento individual. Um cartao conhecido nao e associado a outro cartao
conhecido diferente. Correspondencias ambiguas exigem uma escolha explicita.
Linhas sem cartao identificado permanecem sinalizadas, sem inferir um cartao a
partir da selecao do usuario.

## Persistencia

A migration `0013` acrescenta:

- `statement_review_items`: estado, categoria, identificadores, snapshots das
  origens e data da decisao para as tres abas.
- `statement_review_batches`: pedidos idempotentes e resultado do processamento.
- `card_statements.review_warnings`: avisos persistidos da importacao.
- Unicidade da importacao por usuario, arquivo e conjunto de cartoes, em vez da
  restricao global entre usuarios.

O historico mostra as duas descricoes originais dos matches e os IDs dos registros.
Contadores e progresso sao calculados no servidor, incluindo os itens so no banco.
Nao ha `localStorage` como fonte de estado. A pagina principal permite retomar uma
revisao pendente sem enviar novamente o PDF.

Reenviar os mesmos bytes preserva as ocorrencias, seus IDs, categorias e decisoes.
Adicionar cartoes a selecao nao apaga o trabalho anterior. Compras legitimamente
repetidas no mesmo documento continuam como ocorrencias distintas.

## Categorias

O historico exige descricao normalizada igual e categoria valida, sem conflito.
Tambem reutiliza decisoes aprovadas que associaram o estabelecimento da fatura a
uma descricao diferente cadastrada pelo Telegram. Sem historico confiavel, o
classificador usa a configuracao compartilhada do agente, sem ferramentas de
escrita e com possibilidade de nao sugerir nada. Sugestoes atrasadas nao substituem
uma escolha ou limpeza manual.

## API

- `GET /api/reconciliation/{statement_id}`: pendencias, historico, progresso e catalogo.
- `POST /api/reconciliation/{statement_id}/category`: salva `{id, category}`.
- `POST /api/reconciliation/{statement_id}/batch`: recebe `section`
  (`new`, `matched`, `bank`), `action` (`approve`, `ignore`), `items` e `request_id`.
- Um item tem `id` (`tx:123` ou `expense:123`), categoria opcional e, para matches,
  `expense_id`. Repetir o mesmo pedido com a mesma chave nao reaplica a operacao;
  reutilizar a chave com conteudo diferente e rejeitado.

Os endpoints individuais anteriores continuam delegando ao mesmo servico. A nova
tela nao chama o metodo legado que permite exclusoes explicitas.

## Atualizacao E Testes

O startup web executa `alembic upgrade head`. Faca backup antes de atualizar um
banco utilizado; nao e necessario apaga-lo ou reimportar as faturas pendentes.
A migration recusa downgrade destrutivo do historico.

As fixtures de teste usam bancos temporarios, parser sintetico e modelos falsos,
sem exigir PDF privado ou chamadas de IA. A regressao local pode ser executada com:

```bash
source venv/bin/activate
pytest tests --ignore=tests/test_telegram_connection.py
node --check web/static/reconciliation.js
git diff --check
```

`test_telegram_connection.py` faz uma chamada real ao Telegram e deve ser executado
separadamente com credenciais e rede disponiveis.

## Limites Do Legado

Se uma versao anterior sobrescreveu a descricao do Telegram, a migration recupera
o original apenas quando existe auditoria inequivoca. Caso contrario, apresenta
um aviso e indica a descricao como indisponivel, sem copiar o texto da fatura para
ambas as origens. Categorias legadas apenas sugeridas nao viram fatos aprovados.

Estado apagado por reimportacoes antigas nao pode ser reconstruido integralmente.
Arquivos com bytes diferentes nao sao considerados automaticamente a mesma
importacao, e importacoes legadas separadas nao sao fundidas silenciosamente.
