import os
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Union

from pydantic import BaseModel
from database import db, create_document, get_documents
from schemas import Property

app = FastAPI(title="Loved Homes API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Utility helpers

def to_public(doc):
    if not doc:
        return doc
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    return d


def parse_path(path_param: Optional[Union[str, List[int]]]) -> List[int]:
    if path_param is None:
        return []
    if isinstance(path_param, list):
        return [int(x) for x in path_param]
    if isinstance(path_param, str):
        if path_param.strip() == "":
            return []
        return [int(x) for x in path_param.split(',') if x.strip() != ""]
    return []


# Pydantic request models
class PropertyCreate(BaseModel):
    name: str
    photo_url: Optional[str] = None


class PropertyUpdate(BaseModel):
    name: Optional[str] = None
    photo_url: Optional[str] = None


class NodeCreate(BaseModel):
    title: str
    kind: str = "item"  # "item" or "folder"
    parent_path: List[int] = []  # path of indices to reach parent (e.g., [0,2])


class NodeUpdate(BaseModel):
    title: Optional[str] = None
    kind: Optional[str] = None


# Routes
@app.get("/")
def read_root():
    return {"message": "Loved Homes Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


# Properties CRUD
@app.get("/api/properties")
async def list_properties():
    docs = get_documents("property")
    return [to_public(d) for d in docs]


@app.post("/api/properties", response_model=dict)
async def create_property(payload: PropertyCreate):
    prop = Property(name=payload.name, photo_url=payload.photo_url, checklist=[])
    new_id = create_document("property", prop)
    return {"id": new_id}


@app.patch("/api/properties/{prop_id}")
async def update_property(prop_id: str, payload: PropertyUpdate):
    from bson import ObjectId
    try:
        oid = ObjectId(prop_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid property id")

    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not updates:
        return {"updated": False}
    updates["updated_at"] = __import__("datetime").datetime.utcnow()
    res = db["property"].update_one({"_id": oid}, {"$set": updates})
    return {"updated": res.modified_count == 1}


@app.delete("/api/properties/{prop_id}")
async def delete_property(prop_id: str):
    from bson import ObjectId
    try:
        oid = ObjectId(prop_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid property id")
    res = db["property"].delete_one({"_id": oid})
    return {"deleted": res.deleted_count == 1}


# Checklist tree helpers

def get_property_or_404(prop_id: str):
    from bson import ObjectId
    try:
        oid = ObjectId(prop_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid property id")
    doc = db["property"].find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Property not found")
    return doc


def get_node_by_path(checklist: list, path: List[int]):
    node_list = checklist
    parent = None
    for idx in path:
        if idx < 0 or idx >= len(node_list):
            raise HTTPException(status_code=400, detail="Path out of range")
        parent = node_list[idx]
        node_list = parent.get("children", []) or []
    return parent, node_list


@app.get("/api/properties/{prop_id}/checklist")
async def get_checklist(prop_id: str):
    doc = get_property_or_404(prop_id)
    return to_public(doc).get("checklist", [])


@app.post("/api/properties/{prop_id}/checklist")
async def add_node(prop_id: str, payload: NodeCreate):
    doc = get_property_or_404(prop_id)
    checklist = doc.get("checklist", [])

    parent, node_list = get_node_by_path(checklist, payload.parent_path)

    new_node = {
        "id": str(uuid.uuid4()),
        "title": payload.title,
        "kind": payload.kind if payload.kind in ("item", "folder") else "item",
    }
    if new_node["kind"] == "folder":
        new_node["children"] = []

    # If parent_path points to a node, append into its children, else at root
    if payload.parent_path:
        if parent is not None:
            parent.setdefault("children", [])
            parent["children"].append(new_node)
    else:
        checklist.append(new_node)

    oid = __import__("bson").ObjectId(prop_id)
    db["property"].update_one({"_id": oid}, {"$set": {"checklist": checklist}})
    return {"added": True, "node": new_node}


@app.patch("/api/properties/{prop_id}/checklist")
async def update_node(prop_id: str, path: Optional[Union[str, List[int]]] = None, payload: NodeUpdate = None):
    path_list = parse_path(path)
    if not path_list:
        raise HTTPException(status_code=400, detail="Path required")

    doc = get_property_or_404(prop_id)
    checklist = doc.get("checklist", [])

    parent, node_list = get_node_by_path(checklist, path_list[:-1]) if path_list else (None, checklist)
    idx = path_list[-1]
    if idx < 0 or idx >= len(node_list):
        raise HTTPException(status_code=400, detail="Index out of range")

    node = node_list[idx]
    if payload is not None:
        if payload.title is not None:
            node["title"] = payload.title
        if payload.kind in ("item", "folder"):
            if payload.kind == "folder" and "children" not in node:
                node["children"] = []
            if payload.kind == "item" and "children" in node:
                node.pop("children", None)
            node["kind"] = payload.kind

    oid = __import__("bson").ObjectId(prop_id)
    db["property"].update_one({"_id": oid}, {"$set": {"checklist": checklist}})
    return {"updated": True, "node": node}


@app.delete("/api/properties/{prop_id}/checklist")
async def delete_node(prop_id: str, path: Optional[Union[str, List[int]]] = None):
    path_list = parse_path(path)
    if not path_list:
        raise HTTPException(status_code=400, detail="Path required")

    doc = get_property_or_404(prop_id)
    checklist = doc.get("checklist", [])

    parent, node_list = get_node_by_path(checklist, path_list[:-1]) if path_list else (None, checklist)
    idx = path_list[-1]
    if idx < 0 or idx >= len(node_list):
        raise HTTPException(status_code=400, detail="Index out of range")

    removed = node_list.pop(idx)

    oid = __import__("bson").ObjectId(prop_id)
    db["property"].update_one({"_id": oid}, {"$set": {"checklist": checklist}})
    return {"deleted": True, "removed": removed}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
