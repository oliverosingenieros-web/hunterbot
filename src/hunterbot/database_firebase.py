"""Adaptador de base de datos en la nube usando Firebase Cloud Firestore."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from hunterbot.models import OpportunityScore

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
            logger.warning(
                "Librería 'firebase-admin' no instalada. Usando SQLite local como fallback."
            )
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

    def is_message_already_processed(
        self, update_id: int | str, message_id: int | str
    ) -> bool:
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
            doc_ref.set(
                {
                    "update_id": str(update_id),
                    "message_id": str(message_id),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            return False
        except Exception as e:
            logger.warning("Error verificando deduplicación en Firestore: %s", e)
            return False

    def save_opportunity(self, opp: OpportunityScore) -> bool:
        """Guarda o actualiza una oportunidad en Firestore."""
        if not self.enabled:
            return False

        item = opp.item
        doc_ref = self.db.collection("opportunities").document(
            item.id.replace("/", "_")
        )

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
            "last_seen": datetime.now(UTC).isoformat(),
        }

        try:
            doc_ref.set(data, merge=True)
            # Registrar en subcolección de historial de precios
            doc_ref.collection("price_history").add(
                {
                    "price": item.price,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            return True
        except Exception as e:
            logger.error("Error guardando oportunidad en Firestore: %s", e)
            return False

    def log_interaction(
        self,
        chat_id: int,
        thread_id: int | None,
        user_text: str,
        bot_reply: str,
        event_type: str = "search",
    ) -> None:
        """Guarda un registro de la conversación en Firestore para auditoría y depuración."""
        if not self.enabled:
            return
        try:
            self.db.collection("chat_history").add(
                {
                    "chat_id": chat_id,
                    "thread_id": thread_id,
                    "user_text": user_text,
                    "bot_reply": bot_reply[:1000],
                    "event_type": event_type,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        except Exception as e:
            logger.debug("No se pudo guardar log de chat: %s", e)

    def track_provider_health(self, provider_name: str, success: bool) -> int:
        """
        Trackea los fallos de un provider en Firestore.
        Si success=True, resetea a 0.
        Si success=False, incrementa fallos y devuelve el contador actual.
        """
        if not self.enabled:
            return 0
        try:
            doc_ref = self.db.collection("system_health").document(provider_name)
            doc = doc_ref.get()
            current_fails = 0
            
            if doc.exists:
                current_fails = doc.to_dict().get("consecutive_fails", 0)

            if success:
                if current_fails > 0:
                    doc_ref.set({"consecutive_fails": 0, "last_success": datetime.now(UTC).isoformat()}, merge=True)
                return 0
            
            new_fails = current_fails + 1
            doc_ref.set({"consecutive_fails": new_fails, "last_fail": datetime.now(UTC).isoformat()}, merge=True)
            return new_fails
        except Exception as e:
            logger.debug("Error trackeando salud del provider %s: %s", provider_name, e)
            return 0
