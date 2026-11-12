from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Fact(Record):
    period: str
    value: float
    raw_value: str
    unit: str | None = None
    scale: int = 0
    currency: str | None = None
    unit_basis: str | None = None
    start: str | None = None
    end: str | None = None
    instant: bool = False
    context_id: str | None = None
    entity_identifier: str | None = None
    entity_scheme: str | None = None
    concept: str | None = None
    dimensions: dict[str, str] = Field(default_factory=dict)
    cell: int


class SourceText(Record):
    text: str
    locator: str
    filing_hash: str


class EvidenceRow(Record):
    evidence_id: str
    filing_hash: str
    source: str
    statement: str
    table: int
    row: int
    label: str
    text: str
    raw_cells: list[str] = Field(default_factory=list)
    nearby_context: str = ""
    statement_heading: SourceText | None = None
    row_group_heading: SourceText | None = None
    scope_declarations: list[SourceText] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)


class Filing(Record):
    source: str
    content_hash: str
    local_path: str
    metadata: dict = Field(default_factory=dict)
