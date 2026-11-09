import base64
import binascii
from datetime import datetime, timedelta, timezone
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError
from pymongo import ASCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.rag.providers import EMBEDDING_MODEL
from app.storage.json_store import (
    CancellationConsistencyError,
    ConversationOwnershipError,
    DamageReportConflictError,
    DataStoreError,
    SupportTicketConflictError,
)
from app.storage.models import (
    CancellationEvent,
    ConversationMemory,
    CustomerAccount,
    DamageReport,
    Delivery,
    Order,
    Payment,
    PolicyChunk,
    PolicyDocument,
    Product,
    Review,
    SupportAgentAccount,
    SupportTicket,
    SupportTicketStatus,
)
from app.storage.repository import SupportRepository

ModelT = TypeVar("ModelT", bound=BaseModel)
ResultT = TypeVar("ResultT")


def _bson_datetime_precision(value: object) -> object:
    if isinstance(value, datetime):
        return value.replace(microsecond=(value.microsecond // 1000) * 1000)
    if isinstance(value, dict):
        return {key: _bson_datetime_precision(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_bson_datetime_precision(item) for item in value]
    return value


def _normalize_policy_chunk_timestamp(document: dict[str, object]) -> None:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        return
    timestamp = metadata.get("updated_at")
    if not isinstance(timestamp, str):
        return
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataStoreError("Policy chunk has an invalid updated_at timestamp.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    parsed = parsed.replace(microsecond=(parsed.microsecond // 1000) * 1000)
    metadata["updated_at"] = parsed.isoformat()


COLLECTIONS = {
    "conversation_memory": "conversationmemory",
    "cancellation_history": "cancellationhistory",
    "customer_accounts": "customers",
    "support_agents": "supportagents",
    "support_tickets": "supporttickets",
    "damage_reports": "damagereports",
    "orders": "orders",
    "deliveries": "deliveries",
    "payments": "payments",
    "products": "products",
    "reviews": "reviews",
    "policy_documents": "policydocuments",
    "policy_chunks": "policychunks",
}


class MongoRepository(SupportRepository):
    def __init__(
        self,
        uri: str,
        database_name: str,
        vector_index_name: str = "policy_vector_index",
        conversation_ttl: timedelta = timedelta(minutes=30),
        max_conversation_turns: int = 12,
        cancellation_history_retention: timedelta = timedelta(days=365),
        server_selection_timeout_ms: int = 5000,
        search_index_name: str = "policy_bm25_index",
    ) -> None:
        if not uri.strip():
            raise ValueError("MongoDB connection URI must not be empty.")
        if not database_name.strip():
            raise ValueError("MongoDB database name must not be empty.")
        if not vector_index_name.strip():
            raise ValueError("MongoDB vector index name must not be empty.")
        if not search_index_name.strip():
            raise ValueError("MongoDB BM25 search index name must not be empty.")
        if conversation_ttl <= timedelta(0):
            raise ValueError("Conversation TTL must be positive.")
        if not 1 <= max_conversation_turns <= 200:
            raise ValueError("Conversation memory must retain between 1 and 200 turns.")
        if cancellation_history_retention <= timedelta(0):
            raise ValueError("Cancellation history retention must be positive.")

        self._client = MongoClient(
            uri,
            tz_aware=True,
            serverSelectionTimeoutMS=server_selection_timeout_ms,
        )
        self._database = self._client[database_name]
        self._vector_index_name = vector_index_name
        self._search_index_name = search_index_name
        self._conversation_ttl = conversation_ttl
        self._max_conversation_turns = max_conversation_turns
        self._cancellation_history_retention = cancellation_history_retention
        self._run("connect to MongoDB", lambda: self._client.admin.command("ping"))
        self._ensure_indexes()

    def close(self) -> None:
        self._client.close()

    def _run(self, operation: str, action: Callable[[], ResultT]) -> ResultT:
        try:
            return action()
        except DataStoreError:
            raise
        except PyMongoError as exc:
            raise DataStoreError(f"MongoDB operation failed: {operation}.") from exc

    def _collection(self, name: str):
        return self._database[COLLECTIONS[name]]

    def _ensure_indexes(self) -> None:
        collection = self._collection("policy_chunks")
        for keys, options in (
            ([("chunk_id", ASCENDING)], {"unique": True}),
            ([("document_id", ASCENDING)], {}),
        ):
            self._run(
                f"create indexes on {COLLECTIONS['policy_chunks']}",
                lambda keys=keys, options=options: collection.create_index(
                    keys,
                    **options,
                )
            )

    def _document(self, model: BaseModel, id_field: str) -> dict[str, object]:
        raw_document = model.model_dump(mode="python")
        document = {
            key: _bson_datetime_precision(value)
            for key, value in raw_document.items()
        }
        if id_field not in document:
            raise DataStoreError(f"MongoDB record is missing its {id_field} identifier.")
        if isinstance(model, PolicyChunk):
            _normalize_policy_chunk_timestamp(document)
        if isinstance(model, (CustomerAccount, SupportAgentAccount)):
            document["email_normalized"] = model.email.casefold()
        return document

    def _model(self, document: dict[str, object], model: type[ModelT]) -> ModelT:
        record = {
            key: value
            for key, value in document.items()
            if key not in {
                "_id",
                "email_normalized",
                "image_base64",
                "image_bytes",
            }
        }
        try:
            return model.model_validate(record)
        except ValidationError as exc:
            raise DataStoreError(
                f"MongoDB returned an invalid {model.__name__} record."
            ) from exc

    def _records(
        self,
        collection_name: str,
        model: type[ModelT],
        query: dict[str, object] | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[ModelT]:
        def find_records() -> list[ModelT]:
            cursor = self._collection(collection_name).find(query or {})
            if sort:
                cursor = cursor.sort(sort)
            return [self._model(document, model) for document in cursor]

        return self._run(f"read {COLLECTIONS[collection_name]}", find_records)

    def _insert(
        self,
        collection_name: str,
        model: BaseModel,
        id_field: str,
    ) -> None:
        document = self._document(model, id_field)
        self._run(
            f"write {COLLECTIONS[collection_name]}",
            lambda: self._collection(collection_name).insert_one(document),
        )

    def import_migration_record(
        self,
        collection_name: str,
        document: dict[str, object],
        identifier_field: str,
    ) -> bool:
        if collection_name not in COLLECTIONS:
            raise ValueError(f"Unknown MongoDB migration collection: {collection_name}.")
        identifier = document.get(identifier_field)
        if identifier is None:
            raise DataStoreError(f"Migration record is missing {identifier_field}.")
        document = {
            key: _bson_datetime_precision(value)
            for key, value in document.items()
        }
        if collection_name == "policy_chunks":
            _normalize_policy_chunk_timestamp(document)
        collection = self._collection(collection_name)
        existing = self._run(
            f"check {COLLECTIONS[collection_name]} migration record",
            lambda: collection.find_one({identifier_field: identifier}),
        )
        if existing is not None:
            existing.pop("_id", None)
            return False
        try:
            self._run(
                f"import into {COLLECTIONS[collection_name]}",
                lambda: collection.insert_one(document),
            )
        except DataStoreError as exc:
            if isinstance(exc.__cause__, DuplicateKeyError):
                raise DataStoreError(
                    f"MongoDB contains a conflicting record in "
                    f"{COLLECTIONS[collection_name]}."
                ) from exc
            raise
        return True

    def migration_collection_is_empty(self, collection_name: str) -> bool:
        if collection_name not in COLLECTIONS:
            raise ValueError(f"Unknown MongoDB migration collection: {collection_name}.")
        return self._run(
            f"check whether {COLLECTIONS[collection_name]} is empty",
            lambda: self._collection(collection_name).find_one(
                {}, projection={"_id": 1}
            ) is None,
        )

    def get_conversation_memory(
        self,
        conversation_id: str,
        owner_id: str,
    ) -> ConversationMemory | None:
        self.expire_old_conversations()
        result = self._run(
            "read conversation memory",
            lambda: self._collection("conversation_memory").find_one(
                {"conversation_id": conversation_id, "owner_id": owner_id}
            ),
        )
        return self._model(result, ConversationMemory) if result else None

    def save_conversation_memory(
        self,
        memory: ConversationMemory,
    ) -> ConversationMemory:
        now = datetime.now(timezone.utc)
        self.expire_old_conversations(now)
        existing = self._run(
            "read conversation memory",
            lambda: self._collection("conversation_memory").find_one(
                {"conversation_id": memory.conversation_id}
            ),
        )
        if existing and existing["owner_id"] != memory.owner_id:
            raise ConversationOwnershipError(
                "Conversation ID belongs to a different customer."
            )
        saved = ConversationMemory.model_validate(
            memory.model_dump()
            | {
                "turns": memory.turns[-self._max_conversation_turns :],
                "created_at": existing.get("created_at", memory.created_at)
                if existing
                else memory.created_at,
                "updated_at": now,
                "expires_at": now + self._conversation_ttl,
            }
        )
        document = self._document(saved, "conversation_id")
        self._run(
            "save conversation memory",
            lambda: self._collection("conversation_memory").replace_one(
                {"conversation_id": memory.conversation_id},
                document,
                upsert=True,
            ),
        )
        return saved

    def expire_old_conversations(self, now: datetime | None = None) -> int:
        result = self._run(
            "expire conversation memory",
            lambda: self._collection("conversation_memory").delete_many(
                {"expires_at": {"$lte": now or datetime.now(timezone.utc)}}
            ),
        )
        return result.deleted_count

    def append_cancellation_event(self, event: CancellationEvent) -> None:
        try:
            self._insert("cancellation_history", event, "event_id")
        except DataStoreError as exc:
            if isinstance(exc.__cause__, DuplicateKeyError):
                raise DataStoreError("Cancellation event ID already exists.") from exc
            raise

    def update_cancellation_event(self, event: CancellationEvent) -> None:
        result = self._run(
            "update cancellation event",
            lambda: self._collection("cancellation_history").replace_one(
                {"event_id": event.event_id, "request_id": event.request_id},
                self._document(event, "event_id"),
            ),
        )
        if result.matched_count:
            return
        existing = self._run(
            "read cancellation event",
            lambda: self._collection("cancellation_history").find_one(
                {"event_id": event.event_id}
            ),
        )
        if existing is None:
            raise DataStoreError("Cancellation event could not be found.")
        raise DataStoreError("Cancellation request ID does not match.")

    def expire_old_cancellation_events(
        self,
        now: datetime | None = None,
    ) -> int:
        cutoff = (now or datetime.now(timezone.utc)) - self._cancellation_history_retention
        result = self._run(
            "expire cancellation history",
            lambda: self._collection("cancellation_history").delete_many(
                {"requested_at": {"$lte": cutoff}}
            ),
        )
        return result.deleted_count

    def append_support_ticket(self, ticket: SupportTicket) -> None:
        try:
            self._insert("support_tickets", ticket, "ticket_id")
        except DataStoreError as exc:
            if isinstance(exc.__cause__, DuplicateKeyError):
                raise DataStoreError("Support ticket ID already exists.") from exc
            raise

    def get_support_ticket(self, ticket_id: str) -> SupportTicket | None:
        result = self._run(
            "read support ticket",
            lambda: self._collection("support_tickets").find_one(
                {"ticket_id": ticket_id}
            ),
        )
        return self._model(result, SupportTicket) if result else None

    def get_support_tickets(self) -> list[SupportTicket]:
        return self._records("support_tickets", SupportTicket)

    def update_support_ticket(
        self,
        ticket: SupportTicket,
        expected_status: SupportTicketStatus,
        expected_updated_at: datetime | None = None,
    ) -> SupportTicket | None:
        query: dict[str, object] = {
            "ticket_id": ticket.ticket_id,
            "status": expected_status,
            "customer_id": ticket.customer_id,
        }
        if expected_updated_at is not None:
            query["updated_at"] = expected_updated_at
        result = self._run(
            "update support ticket",
            lambda: self._collection("support_tickets").replace_one(
                query,
                self._document(ticket, "ticket_id"),
            ),
        )
        if result.matched_count:
            return ticket
        existing = self.get_support_ticket(ticket.ticket_id)
        if existing is None:
            return None
        if existing.customer_id != ticket.customer_id:
            raise DataStoreError("Support ticket owner cannot be changed.")
        if existing.status != expected_status:
            raise SupportTicketConflictError(
                "Support ticket status changed before the update was saved."
            )
        if expected_updated_at is not None and existing.updated_at != expected_updated_at:
            raise SupportTicketConflictError(
                "Support ticket changed before the update was saved."
            )
        return None

    def get_latest_support_ticket_for_conversation(
        self,
        conversation_id: str,
        customer_id: str,
    ) -> SupportTicket | None:
        records = self._records(
            "support_tickets",
            SupportTicket,
            {"conversation_id": conversation_id, "customer_id": customer_id},
            [("created_at", -1)],
        )
        return records[0] if records else None

    def get_order(self, order_id: str) -> Order | None:
        result = self._run(
            "read order",
            lambda: self._collection("orders").find_one({"order_id": order_id}),
        )
        return self._model(result, Order) if result else None

    def create_damage_report(
        self,
        report: DamageReport,
        image_bytes: bytes,
    ) -> tuple[DamageReport, bool]:
        collection = self._collection("damage_reports")
        existing = self._run(
            "read damage report",
            lambda: collection.find_one({"idempotency_key": report.idempotency_key}),
        )
        if existing:
            if existing["request_fingerprint"] != report.request_fingerprint:
                raise DamageReportConflictError(
                    "Idempotency key was already used for a different report."
                )
            return self._model(existing, DamageReport), False

        document = self._document(report, "report_id")
        document["image_base64"] = base64.b64encode(image_bytes).decode("ascii")
        try:
            self._run("save damage report", lambda: collection.insert_one(document))
        except DataStoreError as exc:
            if isinstance(exc.__cause__, DuplicateKeyError):
                existing = self._run(
                    "read damage report",
                    lambda: collection.find_one(
                        {"idempotency_key": report.idempotency_key}
                    ),
                )
                if existing and existing["request_fingerprint"] == report.request_fingerprint:
                    return self._model(existing, DamageReport), False
                if existing:
                    raise DamageReportConflictError(
                        "Idempotency key was already used for a different report."
                    ) from exc
                raise DataStoreError("Damage report ID already exists.") from exc
            raise
        return report, True

    def get_damage_report_image(self, report_id: str) -> bytes | None:
        document = self._run(
            "read damage report image",
            lambda: self._collection("damage_reports").find_one(
                {"report_id": report_id},
                projection={"image_base64": 1, "image_bytes": 1},
            ),
        )
        if document is None:
            return None
        image_base64 = document.get("image_base64")
        if isinstance(image_base64, str):
            try:
                return base64.b64decode(image_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise DataStoreError(
                    "Damage report image is missing or invalid."
                ) from exc
        image_bytes = document.get("image_bytes")
        if not isinstance(image_bytes, bytes):
            raise DataStoreError("Damage report image is missing or invalid.")
        return image_bytes

    def ensure_damage_report_image_base64(
        self,
        report_id: str,
        image_base64: str,
    ) -> bool:
        collection = self._collection("damage_reports")
        existing = self._run(
            "check damage report image",
            lambda: collection.find_one(
                {"report_id": report_id},
                projection={"image_base64": 1, "image_bytes": 1},
            ),
        )
        if existing is None:
            raise DataStoreError("Damage report could not be found.")
        if (
            existing.get("image_base64") is not None
            or existing.get("image_bytes") is not None
        ):
            return False
        result = self._run(
            "store damage report image",
            lambda: collection.update_one(
                {
                    "report_id": report_id,
                    "image_base64": {"$exists": False},
                    "image_bytes": {"$exists": False},
                },
                {"$set": {"image_base64": image_base64}},
            ),
        )
        return result.modified_count > 0

    def migrate_damage_report_images_to_base64(self) -> int:
        collection = self._collection("damage_reports")

        def migrate_images() -> int:
            migrated = 0
            cursor = collection.find(
                {
                    "image_bytes": {"$type": "binData"},
                    "image_base64": {"$exists": False},
                },
                projection={"_id": 1, "image_bytes": 1},
            )
            for document in cursor:
                image_bytes = document.get("image_bytes")
                if not isinstance(image_bytes, bytes):
                    raise DataStoreError(
                        "Damage report image is missing or invalid."
                    )
                result = collection.update_one(
                    {
                        "_id": document["_id"],
                        "image_base64": {"$exists": False},
                    },
                    {
                        "$set": {
                            "image_base64": base64.b64encode(
                                image_bytes
                            ).decode("ascii")
                        },
                        "$unset": {"image_bytes": ""},
                    },
                )
                migrated += result.modified_count
            return migrated

        return self._run("migrate damage report images to base64", migrate_images)

    def remove_policy_documents(self, document_ids: list[str]) -> tuple[int, int]:
        if not document_ids:
            return 0, 0
        chunks = self._run(
            "remove obsolete policy chunks",
            lambda: self._collection("policy_chunks").delete_many(
                {"document_id": {"$in": document_ids}}
            ),
        )
        documents = self._run(
            "remove obsolete policy documents",
            lambda: self._collection("policy_documents").delete_many(
                {"document_id": {"$in": document_ids}}
            ),
        )
        return documents.deleted_count, chunks.deleted_count

    def get_customer_accounts(self) -> list[CustomerAccount]:
        return self._records("customer_accounts", CustomerAccount)

    def create_customer_account(self, account: CustomerAccount) -> None:
        if self._run(
            "check customer account order",
            lambda: self._collection("orders").find_one(
                {"customer_id": account.customer_id}, {"_id": 1}
            ),
        ) is None:
            raise DataStoreError("The account must be linked to a known customer.")
        try:
            self._insert("customer_accounts", account, "customer_id")
        except DataStoreError as exc:
            if isinstance(exc.__cause__, DuplicateKeyError):
                raise DataStoreError(
                    "A customer account already exists for that email address or customer."
                ) from exc
            raise

    def get_support_agent_accounts(self) -> list[SupportAgentAccount]:
        return self._records("support_agents", SupportAgentAccount)

    def create_support_agent_account(self, account: SupportAgentAccount) -> None:
        try:
            self._insert("support_agents", account, "staff_id")
        except DataStoreError as exc:
            if isinstance(exc.__cause__, DuplicateKeyError):
                raise DataStoreError(
                    "A support-agent account already exists for that email address or staff ID."
                ) from exc
            raise

    def get_orders(self) -> list[Order]:
        return self._records("orders", Order)

    def get_deliveries_for_order(self, order_id: str) -> list[Delivery]:
        return self._records("deliveries", Delivery, {"order_id": order_id})

    def get_payments_for_order(self, order_id: str) -> list[Payment]:
        return self._records("payments", Payment, {"order_id": order_id})

    def get_product(self, product_id: str) -> Product | None:
        result = self._run(
            "read product",
            lambda: self._collection("products").find_one(
                {"product_id": product_id}
            ),
        )
        return self._model(result, Product) if result else None

    def get_products(self) -> list[Product]:
        return self._records("products", Product)

    def get_reviews(self) -> list[Review]:
        return self._records("reviews", Review)

    def get_policy_documents(self) -> list[PolicyDocument]:
        return self._records("policy_documents", PolicyDocument)

    def get_policy_chunks(self) -> list[PolicyChunk]:
        return self._records("policy_chunks", PolicyChunk)

    def replace_policy_chunks(
        self,
        document_id: str,
        chunks: list[PolicyChunk],
    ) -> None:
        ids = [chunk.chunk_id for chunk in chunks]
        if len(ids) != len(set(ids)):
            raise DataStoreError("Replacement policy chunks contain duplicate IDs.")
        if any(chunk.document_id != document_id for chunk in chunks):
            raise DataStoreError("Replacement chunks contain a different document ID.")

        collection = self._collection("policy_chunks")
        try:
            with self._client.start_session() as session:
                with session.start_transaction():
                    if set(ids).intersection(
                        self._run(
                            "check policy chunk identifiers",
                            lambda: collection.distinct(
                                "chunk_id",
                                {"document_id": {"$ne": document_id}},
                                session=session,
                            ),
                        )
                    ):
                        raise DataStoreError(
                            "Replacement policy chunk ID already exists."
                        )
                    collection.delete_many({"document_id": document_id}, session=session)
                    if chunks:
                        collection.insert_many(
                            [self._document(chunk, "chunk_id") for chunk in chunks],
                            ordered=True,
                            session=session,
                        )
        except DataStoreError:
            raise
        except PyMongoError as exc:
            raise DataStoreError("Could not replace MongoDB policy chunks.") from exc

    def vector_search_policy_chunks(
        self,
        query_vector: list[float],
        embedding_model: str = EMBEDDING_MODEL,
        limit: int = 5,
        document_versions: dict[str, str] | None = None,
    ) -> list[tuple[PolicyChunk, float]]:
        candidate_limit = max(limit * 5, 50)
        filters: list[dict[str, object]] = [
            {"embedding_model": embedding_model},
            {"metadata.approved": True},
        ]
        if document_versions is not None:
            filters.append(
                {
                    "$or": [
                        {
                            "$and": [
                                {"document_id": document_id},
                                {"metadata.updated_at": updated_at},
                            ]
                        }
                        for document_id, updated_at in document_versions.items()
                    ]
                }
            )
        pipeline = [
            {
                "$vectorSearch": {
                    "index": self._vector_index_name,
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": max(candidate_limit * 20, 100),
                    "limit": candidate_limit,
                    "filter": {"$and": filters},
                }
            },
            {"$addFields": {"_vector_score": {"$meta": "vectorSearchScore"}}},
        ]
        documents = self._run(
            "search policy chunks with Atlas Vector Search",
            lambda: list(self._collection("policy_chunks").aggregate(pipeline)),
        )
        results: list[tuple[PolicyChunk, float]] = []
        for document in documents:
            score = document.pop("_vector_score")
            chunk = self._model(document, PolicyChunk)
            cosine_score = (float(score) * 2.0) - 1.0
            results.append((chunk, cosine_score))
        return results

    def bm25_search_policy_chunks(
        self,
        query: str,
        limit: int = 5,
        document_versions: dict[str, str] | None = None,
    ) -> list[PolicyChunk]:
        if not query.strip():
            return []
        if limit < 1:
            raise ValueError("limit must be positive.")

        filters: list[dict[str, object]] = [
            {"equals": {"path": "metadata.approved", "value": True}}
        ]
        if document_versions is not None:
            version_filters = [
                {
                    "compound": {
                        "filter": [
                            {
                                "equals": {
                                    "path": "document_id",
                                    "value": document_id,
                                }
                            },
                            {
                                "equals": {
                                    "path": "metadata.updated_at",
                                    "value": updated_at,
                                }
                            },
                        ]
                    }
                }
                for document_id, updated_at in document_versions.items()
            ]
            if not version_filters:
                return []
            filters.append(
                {
                    "compound": {
                        "should": version_filters,
                        "minimumShouldMatch": 1,
                    }
                }
            )

        pipeline = [
            {
                "$search": {
                    "index": self._search_index_name,
                    "compound": {
                        "must": [
                            {
                                "text": {
                                    "query": query,
                                    "path": ["text", "title"],
                                }
                            }
                        ],
                        "filter": filters,
                    },
                }
            },
            {"$limit": limit},
        ]
        documents = self._run(
            "search policy chunks with Atlas Search BM25",
            lambda: list(self._collection("policy_chunks").aggregate(pipeline)),
        )
        return [self._model(document, PolicyChunk) for document in documents]

    def validate_references(self) -> None:
        orders = self.get_orders()
        deliveries = self._records("deliveries", Delivery)
        payments = self._records("payments", Payment)
        products = self.get_products()
        reviews = self.get_reviews()
        order_ids = {order.order_id for order in orders}
        product_ids = {product.product_id for product in products}

        if any(
            item.product_id not in product_ids
            for order in orders
            for item in order.items
        ):
            raise DataStoreError("An order references a missing product.")
        if any(delivery.order_id not in order_ids for delivery in deliveries):
            raise DataStoreError("A delivery references a missing order.")
        if any(payment.order_id not in order_ids for payment in payments):
            raise DataStoreError("A payment references a missing order.")
        if any(review.product_id not in product_ids for review in reviews):
            raise DataStoreError("A review references a missing product.")

    def cancel_order_if_eligible(
        self,
        order_id: str,
        customer_id: str,
        updated_at: datetime,
        expected_updated_at: datetime,
        cancellation_event: CancellationEvent | None = None,
    ) -> Order | None:
        try:
            with self._client.start_session() as session:
                with session.start_transaction():
                    result = self._collection("orders").find_one_and_update(
                        {
                            "order_id": order_id,
                            "customer_id": customer_id,
                            "cancellation_allowed": True,
                            "order_status": "processing",
                            "updated_at": expected_updated_at,
                        },
                        {
                            "$set": {
                                "order_status": "cancelled",
                                "cancellation_allowed": False,
                                "updated_at": updated_at,
                            }
                        },
                        return_document=ReturnDocument.AFTER,
                        session=session,
                    )
                    if result is None:
                        return None
                    if cancellation_event is not None:
                        update = self._collection("cancellation_history").replace_one(
                            {
                                "event_id": cancellation_event.event_id,
                                "request_id": cancellation_event.request_id,
                            },
                            self._document(cancellation_event, "event_id"),
                            session=session,
                        )
                        if not update.matched_count:
                            raise CancellationConsistencyError(
                                "Order and cancellation history could not be synchronized."
                            )
                    return self._model(result, Order)
        except DataStoreError:
            raise
        except PyMongoError as exc:
            raise DataStoreError("Could not cancel the MongoDB order.") from exc
