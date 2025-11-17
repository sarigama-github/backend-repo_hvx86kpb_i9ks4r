"""
Database Schemas for Loved Homes

Each Pydantic model represents a collection in MongoDB.
Model name lowercased is the collection name.
"""

from pydantic import BaseModel, Field
from typing import List, Literal, Optional


class ChecklistNode(BaseModel):
    id: str = Field(..., description="Unique node id (uuid)")
    title: str = Field(..., description="Display title")
    kind: Literal["item", "folder"] = Field("item", description="Node type")
    children: Optional[List["ChecklistNode"]] = Field(default=None, description="Child nodes if folder")


ChecklistNode.model_rebuild()


class Property(BaseModel):
    """
    Collection name: "property"
    Represents a vacation home managed by Loved Homes
    """
    name: str = Field(..., description="Property display name")
    photo_url: Optional[str] = Field(None, description="Public URL of the uploaded cover photo")
    checklist: List[ChecklistNode] = Field(default_factory=list, description="Root-level checklist nodes")
