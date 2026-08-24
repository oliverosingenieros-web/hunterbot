"""Adaptador de base de datos en la nube usando Firebase Cloud Firestore."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from hunterbot.models import Item, OpportunityScore

logger = logging.getLogger(__name__)

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    HAS_FIREBASE = True
except ImportError:
    HAS_FIREBASE = False


class FirestoreDatabase:
    """Gestiona el almacenamiento y sincronización con Cloud Firestore."""

    def __init__(self, service_account_path: str | None = None) -> None:
        self.enabled = False
        if not HAS_FIREBASE:
            logger.warning("Librería 'firebase-admin' no instalada. Usando SQLite local como fallback.")
            return

        try:
            if not firebase_admin._apps:
                if service_account_path:
                    cred = credentials.Certificate(service_account_path)
                    firebase_admin.initialize_app(cred)
                else:
                    firebase_admin.initialize_app()
            self.db = firestore.client()
            self.enabled = True
            logger.info("🔥 Conectado a Cloud Firestore exitosamente.")
        except Exception as e:
            logger.error("No se pudo inicializar Firebase Firestore: %s", e)

    def is_message_already_processed(self, update_id: int | str, message_id: int | str) -> bool:
        """Comprueba si un update_id o message_id de Telegram ya fue procesado para evitar duplicados."""
        if not self.enabled:
            return False

        key = f"{update_id}_{message_id}"
        doc_ref = self.db.collection("processed_messages").document(str(key))
        try:
            doc = doc_ref.get()
            if doc.exists:
                return True
            # Registrarlo con TTL implícito
            doc_ref.set({
                "update_id": str(update_id),
                "message_id": str(message_id),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return False
        except Exception as e:
            logger.warning("Error verificando deduplicación en Firestore: %s", e)
            return False

    def save_opportunity(self, opp: OpportunityScore) -> bool:
        """Guarda o actualiza una oportunidad en Firestore."""
        if not self.enabled:
            return False

        item = opp.item
        doc_ref = self.db.collection("opportunities").document(item.id.replace("/", "_"))

        data = {
            "id": item.id,
            "provider": item.provider,
            "category": item.category.value,
            "title": item.title,
            "price": item.price,
            "currency": item.currency,
            "url": item.url,
            "location": item.location or "",
            "size_m2": item.size_m2,
            "price_per_m2": item.price_per_m2,
            "length_m": item.length_m,
            "score": opp.score,
            "label": opp.label,
            "reasons": opp.reasons,
            "image_url": item.image_url or "",
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }

        try:
            doc_ref.set(data, merge=True)
            # Registrar en subcolección de historial de precios
            doc_ref.collection("price_history").add({
                "price": item.price,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return True
        except Exception as e:
            logger.error("Error guardando oportunidad en Firestore: %s", e)
            return False
