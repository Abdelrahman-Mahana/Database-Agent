"""
Database Connection Manager.
Handles URL generation for PostgreSQL, MySQL, SQL Server, SQLite, and MongoDB,
credential encryption via Fernet, and profile storage.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import Fernet
from pydantic import BaseModel
from sqlalchemy import create_engine, inspect, text


def _get_fernet_key() -> bytes:
    """Derive a stable 32-byte url-safe base64 key from environment SECRET_KEY or fallback."""
    raw_secret = os.getenv("SECRET_KEY", "database-analyst-agent-default-secure-key-2026")
    key_bytes = hashlib.sha256(raw_secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(key_bytes)


class ConnectionProfile(BaseModel):
    connection_id: str
    db_type: str
    display_name: str
    database_name: str
    encrypted_credentials: str
    masked_url: str
    created_at: float
    updated_at: float


class ConnectionManager:
    """Manages database connection strings, validation, and encrypted saved profiles."""

    def __init__(self, storage_path: Optional[Path] = None):
        if storage_path is None:
            backend_dir = Path(__file__).resolve().parents[2]
            storage_path = backend_dir / "connection_profiles.json"
        self.storage_path = storage_path
        self._fernet = Fernet(_get_fernet_key())

    def _encrypt(self, text_data: str) -> str:
        return self._fernet.encrypt(text_data.encode("utf-8")).decode("utf-8")

    def _decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")

    def build_connection_url(
        self,
        db_type: str,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        file_path: Optional[str] = None,
        ssl_enabled: bool = False,
        ssl_mode: Optional[str] = None,
        connection_url: Optional[str] = None,
    ) -> str:
        """Construct a valid connection URI based on database type and configuration."""
        if connection_url and connection_url.strip():
            return connection_url.strip()

        db_type = db_type.lower().strip()

        if db_type == "sqlite":
            path = (file_path or database or "app.db").strip()
            if not path.startswith("sqlite:"):
                # Handle relative or absolute sqlite paths
                if path.startswith("/"):
                    return f"sqlite:///{path}"
                return f"sqlite:///{path}"
            return path

        user_part = ""
        if username:
            if password:
                user_part = f"{username}:{password}@"
            else:
                user_part = f"{username}@"

        host_part = host or "localhost"
        db_name = database or ""

        if db_type == "postgresql" or db_type == "postgres":
            p = port or 5432
            query_params = []
            if ssl_enabled:
                mode = ssl_mode or "require"
                query_params.append(f"sslmode={mode}")
            query_str = f"?{'&'.join(query_params)}" if query_params else ""
            return f"postgresql://{user_part}{host_part}:{p}/{db_name}{query_str}"

        elif db_type == "mysql":
            p = port or 3306
            query_params = []
            if ssl_enabled:
                query_params.append("ssl=true")
            query_str = f"?{'&'.join(query_params)}" if query_params else ""
            return f"mysql+pymysql://{user_part}{host_part}:{p}/{db_name}{query_str}"

        elif db_type == "sqlserver" or db_type == "mssql":
            p = port or 1433
            query_params = ["driver=ODBC+Driver+17+for+SQL+Server"]
            if ssl_enabled:
                query_params.append("Encrypt=yes")
                query_params.append("TrustServerCertificate=no")
            else:
                query_params.append("TrustServerCertificate=yes")
            query_str = f"?{'&'.join(query_params)}"
            return f"mssql+pyodbc://{user_part}{host_part}:{p}/{db_name}{query_str}"

        elif db_type == "mongodb" or db_type == "mongo":
            p = port or 27017
            query_params = []
            if ssl_enabled:
                query_params.append("tls=true")
            query_str = f"?{'&'.join(query_params)}" if query_params else ""
            return f"mongodb://{user_part}{host_part}:{p}/{db_name}{query_str}"

        else:
            raise ValueError(f"Unsupported database engine type: {db_type}")

    def mask_connection_url(self, url: str) -> str:
        """Sanitize password details from connection string for safe API output."""
        if not url:
            return ""
        if "@" in url and "://" in url:
            prefix, rest = url.split("://", 1)
            user_info, host_info = rest.split("@", 1)
            if ":" in user_info:
                user, _ = user_info.split(":", 1)
                return f"{prefix}://{user}:••••••••@{host_info}"
            return f"{prefix}://••••••••@{host_info}"
        return url

    def validate_connection(self, url: str, db_type: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validate connectivity to target database with clear diagnostic messages.
        Returns (success: bool, error_message: str, details: dict).
        """
        db_type_upper = db_type.upper()
        if db_type.lower() in ["mongodb", "mongo"]:
            try:
                import pymongo
                client = pymongo.MongoClient(url, serverSelectionTimeoutMS=3000)
                client.admin.command("ping")
                db_name = url.rsplit("/", 1)[-1].split("?")[0] or "mongodb"
                cols = client[db_name].list_collection_names()
                return True, "", {
                    "database_name": db_name.capitalize(),
                    "database_type": "MONGODB",
                    "object_count": len(cols),
                }
            except Exception as e:
                msg = str(e)
                if "ServerSelectionTimeoutError" in msg or "Connection refused" in msg:
                    return False, f"Could not connect to MongoDB server at host/port: {msg}", {}
                if "AuthenticationFailed" in msg or "auth failed" in msg.lower():
                    return False, "MongoDB Authentication Failed: Invalid username or password.", {}
                return False, f"MongoDB connection error: {msg}", {}
        else:
            try:
                engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5} if "sqlite" not in url else {})
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                insp = inspect(engine)
                table_names = insp.get_table_names()
                
                # Determine database name
                db_name = "Database"
                if hasattr(engine.url, "database") and engine.url.database:
                    db_name = os.path.splitext(os.path.basename(str(engine.url.database)))[0].capitalize()

                return True, "", {
                    "database_name": db_name,
                    "database_type": engine.dialect.name.upper(),
                    "object_count": len(table_names),
                }
            except Exception as e:
                err_str = str(e)
                if "Password authentication failed" in err_str or "Access denied" in err_str:
                    return False, f"Connection failed for {db_type}: Password authentication failed. Please verify your username and password.", {}
                if "could not connect to server" in err_str or "Connection refused" in err_str or "Is the server running" in err_str:
                    return False, f"Connection failed for {db_type}: Could not reach database server. Check host, port, and network firewall.", {}
                if "database" in err_str and "does not exist" in err_str:
                    return False, f"Connection failed for {db_type}: Specified database does not exist.", {}
                return False, f"Connection error for {db_type}: {err_str}", {}

    def save_profile(self, db_type: str, display_name: str, connection_url: str) -> ConnectionProfile:
        """Store an encrypted connection profile safely on disk."""
        import time

        connection_id = hashlib.sha256(connection_url.encode("utf-8")).hexdigest()[:12]
        encrypted_url = self._encrypt(connection_url)
        masked = self.mask_connection_url(connection_url)

        # Extract db name
        db_name = "Database"
        if "sqlite:///" in connection_url:
            db_name = os.path.splitext(os.path.basename(connection_url.replace("sqlite:///", "")))[0].capitalize()
        elif "/" in connection_url:
            raw_db = connection_url.rsplit("/", 1)[-1].split("?")[0]
            if raw_db:
                db_name = raw_db.capitalize()

        disp_name = display_name or f"{db_type.capitalize()} ({db_name})"

        profile_data = {
            "connection_id": connection_id,
            "db_type": db_type.upper(),
            "display_name": disp_name,
            "database_name": db_name,
            "encrypted_credentials": encrypted_url,
            "masked_url": masked,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        profiles = self._read_profiles()
        profiles[connection_id] = profile_data
        self._write_profiles(profiles)

        return ConnectionProfile(**profile_data)

    def get_profile_url(self, connection_id: str) -> Optional[str]:
        """Decrypt connection URL for a saved profile by ID."""
        profiles = self._read_profiles()
        if connection_id not in profiles:
            return None
        encrypted = profiles[connection_id]["encrypted_credentials"]
        return self._decrypt(encrypted)

    def list_saved_profiles(self) -> List[Dict[str, Any]]:
        """List all saved profiles (without raw passwords)."""
        profiles = self._read_profiles()
        res = []
        for p in profiles.values():
            res.append({
                "connection_id": p["connection_id"],
                "db_type": p["db_type"],
                "display_name": p["display_name"],
                "database_name": p["database_name"],
                "masked_url": p["masked_url"],
                "updated_at": p.get("updated_at", 0),
            })
        # Sort newest first
        res.sort(key=lambda x: x["updated_at"], reverse=True)
        return res

    def _read_profiles(self) -> Dict[str, Any]:
        if not self.storage_path.exists():
            return {}
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_profiles(self, data: Dict[str, Any]) -> None:
        self.storage_path.parent.mkdir(exist_ok=True, parents=True)
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


connection_manager = ConnectionManager()
