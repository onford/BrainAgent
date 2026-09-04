from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CredentialFieldType(StrEnum):
    TEXT = "text"
    EMAIL = "email"
    SECRET = "secret"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SELECT = "select"


class CredentialRequirement(StrEnum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


class CredentialOption(BaseModel):
    label: str
    value: str


class CredentialFieldDefinition(BaseModel):
    key: str
    label: str
    type: CredentialFieldType
    required: bool = False
    description: str | None = None
    placeholder: str | None = None
    options: list[CredentialOption] = Field(default_factory=list)

    @property
    def is_secret(self) -> bool:
        return self.type == CredentialFieldType.SECRET


class CostPolicy(BaseModel):
    tier: str
    summary: str
    requires_user_approval: bool = False


class ValidationRequest(BaseModel):
    path: str
    params: dict[str, Any] = Field(default_factory=dict)


class CredentialBinding(BaseModel):
    field: str
    location: str
    name: str
    prefix: str = ""


class ToolDefinition(BaseModel):
    id: str
    name: str
    description: str
    category: str
    base_url: str
    credential_requirement: CredentialRequirement
    credential_schema: list[CredentialFieldDefinition] = Field(default_factory=list)
    cost_policy: CostPolicy
    client_kind: str = "http"
    headers: dict[str, str] = Field(default_factory=dict)
    credential_bindings: list[CredentialBinding] = Field(default_factory=list)
    validation: ValidationRequest


FREE = CostPolicy(tier="free", summary="免费公共 API；仍受服务方速率限制。")


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        id="github",
        name="GitHub",
        description="搜索代码仓库、Issue 与公开项目元数据。",
        category="code",
        base_url="https://api.github.com",
        credential_requirement=CredentialRequirement.OPTIONAL,
        credential_schema=[
            CredentialFieldDefinition(
                key="token",
                label="Personal access token",
                type=CredentialFieldType.SECRET,
                description="可选。提高速率限制，并允许访问令牌有权读取的资源。",
                placeholder="github_pat_…",
            )
        ],
        cost_policy=FREE,
        client_kind="github",
        headers={"X-GitHub-Api-Version": "2022-11-28"},
        credential_bindings=[
            CredentialBinding(
                field="token", location="header", name="Authorization", prefix="Bearer "
            )
        ],
        validation=ValidationRequest(path="/rate_limit"),
    ),
    ToolDefinition(
        id="semantic_scholar",
        name="Semantic Scholar",
        description="检索论文、作者、引用关系与开放获取元数据。",
        category="literature",
        base_url="https://api.semanticscholar.org/graph/v1",
        credential_requirement=CredentialRequirement.OPTIONAL,
        credential_schema=[
            CredentialFieldDefinition(
                key="api_key",
                label="API key",
                type=CredentialFieldType.SECRET,
                description="可选但推荐；通过 x-api-key 请求头发送。",
            )
        ],
        cost_policy=FREE,
        credential_bindings=[
            CredentialBinding(field="api_key", location="header", name="x-api-key")
        ],
        validation=ValidationRequest(
            path="/paper/search", params={"query": "neuroscience", "limit": 1}
        ),
    ),
    ToolDefinition(
        id="openalex",
        name="OpenAlex",
        description="检索学术作品、作者、机构、来源与主题。",
        category="literature",
        base_url="https://api.openalex.org",
        credential_requirement=CredentialRequirement.OPTIONAL,
        credential_schema=[
            CredentialFieldDefinition(
                key="api_key", label="API key", type=CredentialFieldType.SECRET
            ),
            CredentialFieldDefinition(
                key="email",
                label="Contact email",
                type=CredentialFieldType.EMAIL,
                description="可选，用于标识礼貌请求。",
            ),
        ],
        cost_policy=FREE,
        credential_bindings=[
            CredentialBinding(field="api_key", location="query", name="api_key"),
            CredentialBinding(field="email", location="query", name="mailto"),
        ],
        validation=ValidationRequest(path="/works", params={"per-page": 1}),
    ),
    ToolDefinition(
        id="crossref",
        name="Crossref",
        description="检索 DOI、出版物及引用元数据。",
        category="literature",
        base_url="https://api.crossref.org",
        credential_requirement=CredentialRequirement.OPTIONAL,
        credential_schema=[
            CredentialFieldDefinition(
                key="email",
                label="Polite pool email",
                type=CredentialFieldType.EMAIL,
                description="可选但推荐；作为 mailto 参数发送。",
            )
        ],
        cost_policy=FREE,
        credential_bindings=[
            CredentialBinding(field="email", location="query", name="mailto")
        ],
        validation=ValidationRequest(path="/works", params={"rows": 0}),
    ),
    ToolDefinition(
        id="europe_pmc",
        name="Europe PMC",
        description="检索生命科学论文、预印本、基金和开放全文信息。",
        category="literature",
        base_url="https://www.ebi.ac.uk/europepmc/webservices/rest",
        credential_requirement=CredentialRequirement.NONE,
        credential_schema=[],
        cost_policy=FREE,
        validation=ValidationRequest(
            path="/search", params={"query": "neuroscience", "pageSize": 1, "format": "json"}
        ),
    ),
    ToolDefinition(
        id="arxiv",
        name="arXiv",
        description="检索 arXiv 预印本及其基础元数据。",
        category="literature",
        base_url="https://export.arxiv.org/api",
        credential_requirement=CredentialRequirement.NONE,
        credential_schema=[],
        cost_policy=FREE,
        validation=ValidationRequest(
            path="/query", params={"search_query": "all:neuroscience", "max_results": 1}
        ),
    ),
    ToolDefinition(
        id="unpaywall",
        name="Unpaywall",
        description="通过 DOI 查找论文的合法开放获取版本。",
        category="literature",
        base_url="https://api.unpaywall.org/v2",
        credential_requirement=CredentialRequirement.REQUIRED,
        credential_schema=[
            CredentialFieldDefinition(
                key="email",
                label="Email",
                type=CredentialFieldType.EMAIL,
                required=True,
                description="Unpaywall REST API 要求每次请求携带联系邮箱。",
            )
        ],
        cost_policy=FREE,
        credential_bindings=[
            CredentialBinding(field="email", location="query", name="email")
        ],
        validation=ValidationRequest(path="/10.1038/nature12373"),
    ),
)


TOOL_DEFINITION_BY_ID = {definition.id: definition for definition in TOOL_DEFINITIONS}
