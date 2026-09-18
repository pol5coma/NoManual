from uuid import UUID

from pydantic import BaseModel, ConfigDict

from nomanual.models.enums import ProductType


class ProductSchema(BaseModel):
    """What the API returns for a product.

    Shaped for the picker the user sees before asking anything: brand, model
    and type are what populate it, and the id is what the client sends back
    with the question so retrieval can be scoped to this appliance.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    brand: str
    model: str
    name: str | None = None
    type: ProductType
