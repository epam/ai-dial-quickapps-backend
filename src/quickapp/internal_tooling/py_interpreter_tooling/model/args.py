from pydantic import BaseModel, Field


class DataSampleConfig(BaseModel):
    sample_data: bool = Field(default=True)
    page: int = Field(default=0)
    page_size: int = Field(default=3000)


class InterpreterParameters(BaseModel):
    """Data class for execution inputs with Pydantic validation"""

    code: str
    # FIXME: error: Argument "default_factory" to "Field" has incompatible type "type[list[_T]]"; expected "Callable[[], Never] | Callable[[dict[str, Any]], Never]"  [arg-type]
    attachment_urls: list[str] | None = Field(default=None)
    data_sample_config: DataSampleConfig | None = Field(default=None)
