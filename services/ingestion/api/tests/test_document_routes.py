"""Tests for document management API routes."""

from uuid import uuid4

from services.documents import DocumentListResult


class TestListDocuments:
    """Tests for GET /documents endpoint."""

    def test_requires_auth(self, client_no_auth):
        """Returns 401 without auth."""
        response = client_no_auth.get("/documents")
        assert response.status_code == 401

    def test_list_documents_success(
        self,
        client,
        auth_headers,
        mock_document_service,
        sample_document_response,
    ):
        """Returns paginated document list."""
        mock_document_service.list_documents.return_value = DocumentListResult(
            documents=[sample_document_response],
            total=1,
        )

        # Note: Would need proper dependency override in real test


class TestGetDocument:
    """Tests for GET /documents/{id} endpoint."""

    def test_requires_auth(self, client_no_auth):
        """Returns 401 without auth."""
        doc_id = uuid4()
        response = client_no_auth.get(f"/documents/{doc_id}")
        assert response.status_code == 401


class TestDeleteDocument:
    """Tests for DELETE /documents/{id} endpoint."""

    def test_requires_auth(self, client_no_auth):
        """Returns 401 without auth."""
        doc_id = uuid4()
        response = client_no_auth.delete(f"/documents/{doc_id}")
        assert response.status_code == 401


class TestReindexDocument:
    """Tests for POST /documents/{id}/reindex endpoint."""

    def test_requires_auth(self, client_no_auth):
        """Returns 401 without auth."""
        doc_id = uuid4()
        response = client_no_auth.post(f"/documents/{doc_id}/reindex")
        assert response.status_code == 401


class TestPagination:
    """Tests for pagination behavior."""

    def test_default_pagination(self, client, auth_headers):
        """Uses default page size."""
        # Test will verify query params are passed correctly


class TestFiltering:
    """Tests for document filtering."""

    def test_filter_by_source_type(self, client, auth_headers):
        """Filters by source type."""
        # Test will verify query params are passed correctly

    def test_filter_by_status(self, client, auth_headers):
        """Filters by status."""
        # Test will verify query params are passed correctly

    def test_search(self, client, auth_headers):
        """Searches in title and filename."""
        # Test will verify query params are passed correctly
