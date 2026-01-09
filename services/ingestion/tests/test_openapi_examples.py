"""OpenAPI schema examples tests (US-2.8).

Validates that all Pydantic schemas include examples that appear in OpenAPI spec.
This ensures Swagger UI displays helpful examples for API consumers.

Run with: pytest tests/test_openapi_examples.py
"""

import sys
from pathlib import Path

# Add service directories to path for imports
services_dir = Path(__file__).parent.parent.parent
ingestion_dir = services_dir / "ingestion"
shared_dir = services_dir / "shared"

sys.path.insert(0, str(ingestion_dir))
sys.path.insert(0, str(shared_dir))


class TestIngestSchemaExamples:
    """Tests that ingest schemas include OpenAPI examples."""

    def test_ingest_request_has_examples(self):
        """Verify IngestRequest schema has examples."""
        from api.schemas.ingest import IngestRequest

        schema = IngestRequest.model_json_schema()
        assert "examples" in schema, "IngestRequest should have examples"
        example = schema["examples"][0]
        assert "source_type" in example
        assert "source_config" in example
        assert "acl" in example

    def test_ingest_response_has_examples(self):
        """Verify IngestResponse schema has examples."""
        from api.schemas.ingest import IngestResponse

        schema = IngestResponse.model_json_schema()
        assert "examples" in schema, "IngestResponse should have examples"
        example = schema["examples"][0]
        assert "job_id" in example
        assert "status" in example

    def test_sync_request_has_examples(self):
        """Verify SyncRequest schema has examples matching architecture.md."""
        from api.schemas.ingest import SyncRequest

        schema = SyncRequest.model_json_schema()
        assert "examples" in schema, "SyncRequest should have examples"
        example = schema["examples"][0]
        assert "tenant_id" in example
        assert "source_type" in example
        assert "source_config" in example

    def test_sync_response_has_examples(self):
        """Verify SyncResponse schema has examples."""
        from api.schemas.ingest import SyncResponse

        schema = SyncResponse.model_json_schema()
        assert "examples" in schema, "SyncResponse should have examples"
        example = schema["examples"][0]
        assert "job_id" in example
        assert "status" in example

    def test_reembed_request_has_examples(self):
        """Verify ReembedRequest schema has examples matching architecture.md."""
        from api.schemas.ingest import ReembedRequest

        schema = ReembedRequest.model_json_schema()
        assert "examples" in schema, "ReembedRequest should have examples"
        example = schema["examples"][0]
        assert "embedding_model" in example
        assert "target_scope" in example

    def test_reembed_response_has_examples(self):
        """Verify ReembedResponse schema has examples."""
        from api.schemas.ingest import ReembedResponse

        schema = ReembedResponse.model_json_schema()
        assert "examples" in schema, "ReembedResponse should have examples"
        example = schema["examples"][0]
        assert "job_id" in example
        assert "embedding_job_id" in example

    def test_job_status_response_has_examples(self):
        """Verify JobStatusResponse schema has examples."""
        from api.schemas.ingest import JobStatusResponse

        schema = JobStatusResponse.model_json_schema()
        assert "examples" in schema, "JobStatusResponse should have examples"
        example = schema["examples"][0]
        assert "job_id" in example
        assert "status" in example

    def test_processing_options_has_examples(self):
        """Verify ProcessingOptions schema has examples."""
        from api.schemas.ingest import ProcessingOptions

        schema = ProcessingOptions.model_json_schema()
        assert "examples" in schema, "ProcessingOptions should have examples"
        example = schema["examples"][0]
        assert "chunking_strategy" in example

    def test_acl_context_has_examples(self):
        """Verify ACLContext schema has examples."""
        from api.schemas.ingest import ACLContext

        schema = ACLContext.model_json_schema()
        assert "examples" in schema, "ACLContext should have examples"
        example = schema["examples"][0]
        assert "tenant_id" in example
        assert "visibility" in example


class TestDocumentSchemaExamples:
    """Tests that document schemas include OpenAPI examples."""

    def test_document_response_has_examples(self):
        """Verify DocumentResponse schema has examples."""
        from api.schemas.documents import DocumentResponse

        schema = DocumentResponse.model_json_schema()
        assert "examples" in schema, "DocumentResponse should have examples"
        example = schema["examples"][0]
        assert "document_id" in example
        assert "source_type" in example
        assert "tenant_id" in example

    def test_document_list_response_has_examples(self):
        """Verify DocumentListResponse schema has examples."""
        from api.schemas.documents import DocumentListResponse

        schema = DocumentListResponse.model_json_schema()
        assert "examples" in schema, "DocumentListResponse should have examples"
        example = schema["examples"][0]
        assert "documents" in example
        assert "total" in example
        assert "page" in example

    def test_document_delete_response_has_examples(self):
        """Verify DocumentDeleteResponse schema has examples."""
        from api.schemas.documents import DocumentDeleteResponse

        schema = DocumentDeleteResponse.model_json_schema()
        assert "examples" in schema, "DocumentDeleteResponse should have examples"
        example = schema["examples"][0]
        assert "document_id" in example
        assert "deleted" in example
        assert "chunks_deleted" in example

    def test_reindex_request_has_examples(self):
        """Verify ReindexRequest schema has examples."""
        from api.schemas.documents import ReindexRequest

        schema = ReindexRequest.model_json_schema()
        assert "examples" in schema, "ReindexRequest should have examples"


class TestSourceConfigExamples:
    """Tests that source configuration schemas include examples."""

    def test_filesystem_source_config_has_examples(self):
        """Verify FilesystemSourceConfig schema has examples."""
        from api.schemas.ingest import FilesystemSourceConfig

        schema = FilesystemSourceConfig.model_json_schema()
        assert "examples" in schema, "FilesystemSourceConfig should have examples"
        example = schema["examples"][0]
        assert "path" in example

    def test_database_source_config_has_examples(self):
        """Verify DatabaseSourceConfig schema has examples."""
        from api.schemas.ingest import DatabaseSourceConfig

        schema = DatabaseSourceConfig.model_json_schema()
        assert "examples" in schema, "DatabaseSourceConfig should have examples"
        example = schema["examples"][0]
        assert "connection_string" in example
        assert "query" in example

    def test_web_source_config_has_examples(self):
        """Verify WebSourceConfig schema has examples."""
        from api.schemas.ingest import WebSourceConfig

        schema = WebSourceConfig.model_json_schema()
        assert "examples" in schema, "WebSourceConfig should have examples"
        example = schema["examples"][0]
        assert "start_urls" in example

    def test_api_source_config_has_examples(self):
        """Verify APISourceConfig schema has examples."""
        from api.schemas.ingest import APISourceConfig

        schema = APISourceConfig.model_json_schema()
        assert "examples" in schema, "APISourceConfig should have examples"
        example = schema["examples"][0]
        assert "base_url" in example


class TestExamplesMatchArchitecture:
    """Tests that examples match architecture.md specification."""

    def test_sync_request_example_has_architecture_fields(self):
        """Verify SyncRequest example matches architecture.md POST /api/v1/ingest/sync."""
        from api.schemas.ingest import SyncRequest

        schema = SyncRequest.model_json_schema()
        examples = schema.get("examples", [])
        assert len(examples) >= 1, "SyncRequest should have at least one example"

        # Architecture specifies: tenant_id, source_type, source_config
        example = examples[0]
        assert "tenant_id" in example, "Example should have tenant_id per architecture"
        assert "source_type" in example, "Example should have source_type per architecture"
        assert "source_config" in example, "Example should have source_config per architecture"

    def test_reembed_request_example_has_architecture_fields(self):
        """Verify ReembedRequest example matches architecture.md POST /api/v1/ingest/reembed."""
        from api.schemas.ingest import ReembedRequest

        schema = ReembedRequest.model_json_schema()
        examples = schema.get("examples", [])
        assert len(examples) >= 1, "ReembedRequest should have at least one example"

        # Architecture specifies: embedding_model, target_scope
        example = examples[0]
        assert "embedding_model" in example, "Example should have embedding_model per architecture"
        assert "target_scope" in example, "Example should have target_scope per architecture"

    def test_ingest_response_example_has_architecture_fields(self):
        """Verify IngestResponse example matches architecture.md POST /api/v1/ingest response."""
        from api.schemas.ingest import IngestResponse

        schema = IngestResponse.model_json_schema()
        examples = schema.get("examples", [])
        assert len(examples) >= 1, "IngestResponse should have at least one example"

        # Architecture specifies: document_id (job_id in our impl), status
        example = examples[0]
        assert "job_id" in example, "Example should have job_id per architecture"
        assert "status" in example, "Example should have status per architecture"


class TestExampleValuesAreValid:
    """Tests that example values can be parsed by the schema."""

    def test_ingest_request_example_is_valid(self):
        """Verify IngestRequest example can be instantiated."""
        from api.schemas.ingest import IngestRequest

        schema = IngestRequest.model_json_schema()
        example = schema["examples"][0]

        # Should not raise validation error
        IngestRequest(**example)

    def test_sync_request_example_is_valid(self):
        """Verify SyncRequest example can be instantiated."""
        from api.schemas.ingest import SyncRequest

        schema = SyncRequest.model_json_schema()
        # Use filesystem example which doesn't require connection_string validation
        example = schema["examples"][1]

        # Should not raise validation error
        SyncRequest(**example)

    def test_reembed_request_example_is_valid(self):
        """Verify ReembedRequest example can be instantiated."""
        from api.schemas.ingest import ReembedRequest

        schema = ReembedRequest.model_json_schema()
        example = schema["examples"][0]

        # Should not raise validation error
        ReembedRequest(**example)

    def test_processing_options_example_is_valid(self):
        """Verify ProcessingOptions example can be instantiated."""
        from api.schemas.ingest import ProcessingOptions

        schema = ProcessingOptions.model_json_schema()
        example = schema["examples"][0]

        # Should not raise validation error
        ProcessingOptions(**example)

    def test_acl_context_example_is_valid(self):
        """Verify ACLContext example can be instantiated."""
        from api.schemas.ingest import ACLContext

        schema = ACLContext.model_json_schema()
        example = schema["examples"][0]

        # Should not raise validation error
        ACLContext(**example)

    def test_reindex_request_example_is_valid(self):
        """Verify ReindexRequest example can be instantiated."""
        from api.schemas.documents import ReindexRequest

        schema = ReindexRequest.model_json_schema()
        example = schema["examples"][0]

        # Should not raise validation error
        ReindexRequest(**example)
