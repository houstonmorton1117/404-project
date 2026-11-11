# Kept as a thin re-export so modules doing `from db import get_connection`
# keep working. The single real implementation is in backend/config/db.py.
# Merged 11/11/26 by Obi Achebe

from config.db import get_connection

__all__ = ["get_connection"]
