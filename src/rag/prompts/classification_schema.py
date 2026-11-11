from pydantic import BaseModel, Field

class TicketClassification(BaseModel):
    category: str = Field(description="Obrigatório ser estritamente uma destas: Technical, Billing, Account, Fraud ou General Inquiry")
    priority: str = Field(description="Obrigatório ser estritamente uma destas: Baixa, Media, Alta, Critica")
    initial_level: str = Field(description="Obrigatório ser estritamente um destes: N1, N2, N3")
    triage_justification: str = Field(description="Motivo resumido da classificação em no máximo 2 frases")