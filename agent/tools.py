"""Constrói LangChain tools a partir do ExpenseService.

Substitui o MultiServerMCPClient — cada tool é um wrapper sobre o service.
"""
from datetime import date
from typing import Optional

from langchain_core.tools import tool

from services.expense_service import ExpenseService


def build_tools(service: ExpenseService) -> list:
    """Constrói lista de tools LangChain injetadas com ExpenseService.

    Args:
        service: ExpenseService já inicializado com conn e user_id

    Returns:
        Lista de tools prontas para bind no LLM
    """

    @tool
    def record_expense(
        amount: float,
        description: str,
        category: str,
        method: str,
        expense_date: Optional[str] = None,
    ) -> dict:
        """Registra um gasto no banco de dados financeiro pessoal.

        Args:
            amount: Valor do gasto em reais (ex: 55.90)
            description: Descrição do gasto (ex: "almoço no restaurante")
            category: Categoria do gasto (deve ser uma das categorias válidas)
            method: Método de pagamento — use list_payment_methods para ver os disponíveis
            expense_date: Data do gasto no formato YYYY-MM-DD (padrão: hoje)
        """
        return service.record_expense(amount, description, category, method, expense_date)

    @tool
    def query_expenses(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        method: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> list[dict]:
        """Consulta gastos ativos com filtros opcionais.

        Args:
            start_date: Data inicial no formato YYYY-MM-DD
            end_date: Data final no formato YYYY-MM-DD
            category: Filtrar por categoria específica
            method: Filtrar por método de pagamento
            keyword: Palavra-chave para busca textual na descrição
        """
        return service.query_expenses(start_date, end_date, category, method, keyword)

    @tool
    def get_summary(
        start_date: str,
        end_date: str,
        group_by: str = "category",
    ) -> dict:
        """Retorna resumo de gastos agrupados por dimensão.

        Args:
            start_date: Data inicial no formato YYYY-MM-DD
            end_date: Data final no formato YYYY-MM-DD
            group_by: Dimensão de agrupamento: 'category', 'method', 'day' ou 'month'
        """
        return service.get_summary(start_date, end_date, group_by)

    @tool
    def list_categories() -> list[str]:
        """Retorna a lista de categorias de gastos disponíveis."""
        return service.list_categories()

    @tool
    def list_payment_methods() -> list[str]:
        """Retorna a lista de métodos de pagamento disponíveis."""
        return service.list_payment_methods()

    @tool
    def create_payment_method(name: str, confirmed: bool) -> dict:
        """Cria um novo método de pagamento definido pelo usuário.

        ATENÇÃO: confirmed=True somente após confirmação explícita do usuário nessa mensagem.
        Métodos do sistema (is_system=1) não podem ser substituídos.

        Args:
            name: Nome do novo método (será normalizado para lowercase)
            confirmed: True apenas se o usuário confirmou explicitamente agora
        """
        return service.create_payment_method(name, confirmed)

    @tool
    def create_category(name: str, confirmed: bool) -> dict:
        """Cria uma nova categoria de gastos definida pelo usuário.

        ATENÇÃO: confirmed=True somente após confirmação explícita do usuário nessa mensagem.
        Categorias do sistema (is_system=1) não podem ser substituídas; esta tool só cria
        categorias novas (is_system=0).

        Args:
            name: Nome da nova categoria (será normalizado para title case)
            confirmed: True apenas se o usuário confirmou explicitamente agora
        """
        return service.create_category(name, confirmed)

    @tool
    def find_expense_candidates(
        keyword: str,
        expense_date: Optional[str] = None,
    ) -> dict:
        """Busca registros candidatos para edição ou exclusão.

        Use esta tool ANTES de delete_expense ou update_expense.

        - Com expense_date: retorna registros daquela data que contêm o keyword.
        - Sem expense_date: retorna registros da DATA MAIS RECENTE que contém o keyword.

        Args:
            keyword: Palavra-chave da descrição (ex: "almoço", "uber", "farmácia")
            expense_date: Data em YYYY-MM-DD. Só informe se o usuário mencionou data específica.
        """
        return service.find_expense_candidates(keyword, expense_date)

    @tool
    def delete_expense(expense_id: int, confirmed: bool) -> dict:
        """Exclui um único registro de gasto (soft delete — dado preservado no banco).

        Use após identificar o registro com find_expense_candidates.
        O sistema de confirmação HITL gerencia o parâmetro confirmed automaticamente.

        Args:
            expense_id: ID único do registro a ser excluído
            confirmed: gerenciado pelo sistema — não altere manualmente
        """
        return service.delete_expense(expense_id, confirmed)

    @tool
    def update_expense(
        expense_id: int,
        confirmed: bool,
        amount: Optional[float] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        method: Optional[str] = None,
        expense_date: Optional[str] = None,
    ) -> dict:
        """Atualiza campos de um único registro de gasto.

        Use após identificar o registro com find_expense_candidates.
        O sistema de confirmação HITL gerencia o parâmetro confirmed automaticamente.

        Args:
            expense_id: ID único do registro a ser atualizado
            confirmed: gerenciado pelo sistema — não altere manualmente
            amount: Novo valor em reais (opcional)
            description: Nova descrição (opcional)
            category: Nova categoria (opcional)
            method: Novo método de pagamento (opcional)
            expense_date: Nova data em YYYY-MM-DD (opcional)
        """
        return service.update_expense(
            expense_id, confirmed, amount, description, category, method, expense_date
        )

    return [
        record_expense,
        query_expenses,
        get_summary,
        list_categories,
        list_payment_methods,
        create_payment_method,
        create_category,
        find_expense_candidates,
        delete_expense,
        update_expense,
    ]
