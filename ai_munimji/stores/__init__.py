"""The engine's stores on this site's DocTypes (Phase 4b).

    from ai_munimji.stores import frappe_core_stores, frappe_stock_stores
    core = frappe_core_stores()                 # as the signed-in person: the DocTypes' permission rows decide
    stock = frappe_stock_stores(core)
    core = frappe_core_stores(system=True)      # the scheduled job's mode (Administrator only); built only by ai_munimji.jobs.system_stores()

docs/STORES.md has the table of DocTypes, who may do what to each, and how the Frappe stores differ from the SQLite ones.
"""

from ai_munimji.stores.core import frappe_core_stores
from ai_munimji.stores.stock import frappe_stock_stores

__all__ = ["frappe_core_stores", "frappe_stock_stores"]
