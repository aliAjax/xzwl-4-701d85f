from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import json

from ..models.audit import AuditLog, AuditAction
from ..models.user import User


class AuditLogger:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        action: AuditAction,
        resource_type: str,
        resource_id: Optional[str] = None,
        user: Optional[User] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        changes = None
        if old_values and new_values:
            changes = {}
            for key in set(old_values.keys()) | set(new_values.keys()):
                old_val = old_values.get(key)
                new_val = new_values.get(key)
                if old_val != new_val:
                    changes[key] = {"old": old_val, "new": new_val}

        def serialize_value(val):
            if isinstance(val, datetime):
                return val.isoformat()
            return val

        old_values_serialized = {k: serialize_value(v) for k, v in old_values.items()} if old_values else None
        new_values_serialized = {k: serialize_value(v) for k, v in new_values.items()} if new_values else None
        changes_serialized = None
        if changes:
            changes_serialized = {}
            for k, v in changes.items():
                changes_serialized[k] = {
                    "old": serialize_value(v["old"]),
                    "new": serialize_value(v["new"]),
                }

        audit_log = AuditLog(
            user_id=user.id if user else None,
            action=action.value if hasattr(action, "value") else action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            old_values=old_values_serialized,
            new_values=new_values_serialized,
            changes=changes_serialized,
            description=description,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(audit_log)
        self.db.commit()
        self.db.refresh(audit_log)
        return audit_log

    def log_create(self, resource_type: str, resource_id: str, user: User, new_values: Dict[str, Any], **kwargs) -> AuditLog:
        return self.log(
            action=AuditAction.CREATE,
            resource_type=resource_type,
            resource_id=resource_id,
            user=user,
            new_values=new_values,
            **kwargs,
        )

    def log_update(self, resource_type: str, resource_id: str, user: User, old_values: Dict[str, Any], new_values: Dict[str, Any], **kwargs) -> AuditLog:
        return self.log(
            action=AuditAction.UPDATE,
            resource_type=resource_type,
            resource_id=resource_id,
            user=user,
            old_values=old_values,
            new_values=new_values,
            **kwargs,
        )

    def log_delete(self, resource_type: str, resource_id: str, user: User, old_values: Dict[str, Any], **kwargs) -> AuditLog:
        return self.log(
            action=AuditAction.DELETE,
            resource_type=resource_type,
            resource_id=resource_id,
            user=user,
            old_values=old_values,
            **kwargs,
        )

    def log_status_change(self, resource_type: str, resource_id: str, user: User, old_status: str, new_status: str, **kwargs) -> AuditLog:
        return self.log(
            action=AuditAction.STATUS_CHANGE,
            resource_type=resource_type,
            resource_id=resource_id,
            user=user,
            old_values={"status": old_status},
            new_values={"status": new_status},
            description=f"Status changed from {old_status} to {new_status}",
            **kwargs,
        )

    def log_login(self, user: User, **kwargs) -> AuditLog:
        return self.log(
            action=AuditAction.LOGIN,
            resource_type="user",
            resource_id=str(user.id),
            user=user,
            description=f"User {user.username} logged in",
            **kwargs,
        )

    def log_logout(self, user: User, **kwargs) -> AuditLog:
        return self.log(
            action=AuditAction.LOGOUT,
            resource_type="user",
            resource_id=str(user.id),
            user=user,
            description=f"User {user.username} logged out",
            **kwargs,
        )
