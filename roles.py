from fastapi import HTTPException

def require_role(user: dict, required_role: str):
    if user.get("role") != required_role:
        raise HTTPException(status_code=403, detail="Insufficient permissions")