# Unified ACL Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make ACL first-class across all three data stores (PostgreSQL, Qdrant, OpenSearch) by creating a canonical `AclMetadata` struct in `rag-types` and writing all 6 ACL fields consistently at ingest time.

**Architecture:** A typed `AclMetadata` struct replaces the untyped metadata-bag approach. It is defined in `rag-types`, carried on `DocumentRecord`/`IndexedChunk` in ingestion, and written identically to all stores by the coordinator. The retrieval ACL filter already queries these fields — this change makes the ingest side match.

**Tech Stack:** Rust (rag-types, rag-ingestion, rag-retrieval, rag-database, rag-search), PostgreSQL (Alembic migration), Qdrant (payload), OpenSearch (keyword mapping)

---

## Problem Summary

| Field | Qdrant | OpenSearch | PostgreSQL |
|---|---|---|---|
| `visibility` | top-level, default `"public"` | top-level, default `"public"` | typed column, default `Private` |
| `allowed_groups` | top-level | top-level | typed `text[]` column |
| `allowed_users` | only via metadata merge | in nested `metadata` blob | in `metadata` JSONB only |
| `owner_id` | never written | never written | no column |
| `denied_groups` | never written | never written | no column |
| `denied_users` | never written | never written | no column |

---

### Task 1: Add `AclMetadata` struct to `rag-types`

**Files:**
- Modify: `rag-types/src/document.rs` (after `Visibility` impl block, ~line 75)
- Modify: `rag-types/src/lib.rs` (line 20, add re-export)
- Test: `rag-types/src/document.rs` (inline `#[cfg(test)]` module)

**Step 1: Write the failing test**

Add to the existing `tests` module at the bottom of `rag-types/src/document.rs`:

```rust
#[test]
fn test_acl_metadata_default() {
    let acl = AclMetadata::default();
    assert_eq!(acl.visibility, Visibility::Private);
    assert!(acl.owner_id.is_none());
    assert!(acl.allowed_groups.is_empty());
    assert!(acl.allowed_users.is_empty());
    assert!(acl.denied_groups.is_empty());
    assert!(acl.denied_users.is_empty());
}

#[test]
fn test_acl_metadata_serde_roundtrip() {
    let acl = AclMetadata {
        visibility: Visibility::Group,
        owner_id: Some("user-123".to_string()),
        allowed_groups: vec!["eng".to_string(), "qa".to_string()],
        allowed_users: vec!["user-456".to_string()],
        denied_groups: vec!["contractors".to_string()],
        denied_users: vec!["user-789".to_string()],
    };
    let json = serde_json::to_string(&acl).unwrap();
    let deserialized: AclMetadata = serde_json::from_str(&json).unwrap();
    assert_eq!(acl, deserialized);
}

#[test]
fn test_acl_metadata_to_json_value() {
    let acl = AclMetadata::default();
    let value = acl.to_json_value();
    assert_eq!(value["visibility"], "private");
    assert_eq!(value["allowed_groups"], serde_json::json!([]));
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-types -- test_acl_metadata`
Expected: FAIL — `AclMetadata` not defined

**Step 3: Write the implementation**

Add after the `TryFrom<String> for Visibility` impl block (~line 88) in `rag-types/src/document.rs`:

```rust
/// First-class ACL metadata carried on every document and chunk.
///
/// This struct is the canonical representation of access control across all stores
/// (PostgreSQL, Qdrant, OpenSearch). All stores must write these fields identically.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AclMetadata {
    /// Visibility level (default: Private — safe by default).
    #[serde(default)]
    pub visibility: Visibility,
    /// User ID of the document owner (set from X-User-Id at ingest time).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub owner_id: Option<String>,
    /// Groups explicitly granted access.
    #[serde(default)]
    pub allowed_groups: Vec<String>,
    /// Individual users explicitly granted access.
    #[serde(default)]
    pub allowed_users: Vec<String>,
    /// Groups explicitly denied access (overrides allowed).
    #[serde(default)]
    pub denied_groups: Vec<String>,
    /// Individual users explicitly denied access (overrides allowed).
    #[serde(default)]
    pub denied_users: Vec<String>,
}

impl Default for AclMetadata {
    fn default() -> Self {
        Self {
            visibility: Visibility::Private,
            owner_id: None,
            allowed_groups: vec![],
            allowed_users: vec![],
            denied_groups: vec![],
            denied_users: vec![],
        }
    }
}

impl AclMetadata {
    /// Convert to a flat JSON value suitable for Qdrant/OpenSearch payloads.
    #[must_use]
    pub fn to_json_value(&self) -> serde_json::Value {
        serde_json::json!({
            "visibility": self.visibility,
            "owner_id": self.owner_id,
            "allowed_groups": self.allowed_groups,
            "allowed_users": self.allowed_users,
            "denied_groups": self.denied_groups,
            "denied_users": self.denied_users,
        })
    }
}
```

Update `rag-types/src/lib.rs` line 20 to add `AclMetadata` to the re-export:
```rust
pub use document::{AclMetadata, Chunk, ChunkingStrategy, Document, IndexStatus, SourceType, Visibility};
```

**Step 4: Run test to verify it passes**

Run: `cd crates && cargo test -p rag-types -- test_acl_metadata`
Expected: 3 tests PASS

**Step 5: Commit**

```bash
git add crates/rag-types/src/document.rs crates/rag-types/src/lib.rs
git commit -m "feat(rag-types): add AclMetadata struct for unified ACL across stores"
```

---

### Task 2: Add ACL fields to ingestion `ACLContext` and route handler

**Files:**
- Modify: `rag-ingestion/src/api/types.rs:87-97` (ACLContext struct)
- Modify: `rag-ingestion/src/api/routes/ingest.rs:94-162` (ingest_single_document fn)
- Test: `rag-ingestion/src/api/types.rs` (inline tests module)

**Step 1: Write the failing test**

Add to the existing `tests` module in `rag-ingestion/src/api/types.rs`:

```rust
#[test]
fn test_acl_context_full_fields() {
    let json = r#"{
        "tenant_id": "test-tenant",
        "visibility": "group",
        "allowed_groups": ["eng"],
        "allowed_users": ["user-1"],
        "owner_id": "user-0",
        "denied_groups": ["contractors"],
        "denied_users": ["user-bad"]
    }"#;
    let acl: ACLContext = serde_json::from_str(json).unwrap();
    assert_eq!(acl.owner_id, Some("user-0".to_string()));
    assert_eq!(acl.denied_groups, vec!["contractors"]);
    assert_eq!(acl.denied_users, vec!["user-bad"]);
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-ingestion -- test_acl_context_full`
Expected: FAIL — `owner_id`, `denied_groups`, `denied_users` not fields on `ACLContext`

**Step 3: Write the implementation**

Update `ACLContext` in `rag-ingestion/src/api/types.rs` (lines 87-97):

```rust
/// Access control context for ingested documents.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ACLContext {
    pub tenant_id: String,
    #[serde(default)]
    pub visibility: Visibility,
    #[serde(default)]
    pub owner_id: Option<String>,
    #[serde(default)]
    pub allowed_groups: Vec<String>,
    #[serde(default)]
    pub allowed_users: Vec<String>,
    #[serde(default)]
    pub denied_groups: Vec<String>,
    #[serde(default)]
    pub denied_users: Vec<String>,
}
```

Add an `into_acl_metadata` conversion method:

```rust
impl ACLContext {
    /// Convert to the canonical `AclMetadata` type.
    #[must_use]
    pub fn into_acl_metadata(self) -> rag_types::AclMetadata {
        rag_types::AclMetadata {
            visibility: self.visibility,
            owner_id: self.owner_id,
            allowed_groups: self.allowed_groups,
            allowed_users: self.allowed_users,
            denied_groups: self.denied_groups,
            denied_users: self.denied_users,
        }
    }
}
```

Update `ingest_single_document` in `rag-ingestion/src/api/routes/ingest.rs` to:
1. Accept `HeaderMap` via Axum extractor
2. Extract `X-User-Id` and set `owner_id` if not already provided
3. Serialize all 6 ACL fields into the job payload

Change the function signature (line 95) to:
```rust
pub async fn ingest_single_document(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut request): Json<SingleIngestRequest>,
) -> ApiResult<(StatusCode, Json<IngestResponse>)> {
```

Add after the function body starts (before `let job_id = ...`):
```rust
    // Set owner_id from X-User-Id header if not explicitly provided
    if request.acl.owner_id.is_none() {
        if let Some(user_id) = headers.get("X-User-Id").and_then(|v| v.to_str().ok()) {
            request.acl.owner_id = Some(user_id.to_string());
        }
    }
```

Update the `"acl"` section in the job payload JSON to include all 6 fields:
```rust
"acl": {
    "tenant_id": request.acl.tenant_id,
    "visibility": request.acl.visibility,
    "owner_id": request.acl.owner_id,
    "allowed_groups": request.acl.allowed_groups,
    "allowed_users": request.acl.allowed_users,
    "denied_groups": request.acl.denied_groups,
    "denied_users": request.acl.denied_users
}
```

Apply the same changes to `start_ingestion` in the same file.

**Step 4: Run test to verify it passes**

Run: `cd crates && cargo test -p rag-ingestion -- test_acl_context`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/api/types.rs crates/rag-ingestion/src/api/routes/ingest.rs
git commit -m "feat(rag-ingestion): add full ACL fields to ACLContext and route handlers"
```

---

### Task 3: Add `acl` field to `DocumentRecord` and `IndexedChunk`

**Files:**
- Modify: `rag-ingestion/src/indexing/models.rs:8-22` (DocumentRecord), `:51-69` (IndexedChunk)
- Test: `rag-ingestion/src/indexing/models.rs` (inline tests module)

**Step 1: Write the failing test**

Add to the `tests` module in `rag-ingestion/src/indexing/models.rs`:

```rust
#[test]
fn test_document_record_with_acl() {
    let acl = AclMetadata {
        visibility: Visibility::Group,
        owner_id: Some("owner-1".to_string()),
        allowed_groups: vec!["eng".to_string()],
        ..AclMetadata::default()
    };
    let doc = DocumentRecord::new(
        DocumentId::new(),
        TenantId::new(),
        "test.pdf".to_string(),
    ).with_acl(acl.clone());
    assert_eq!(doc.acl, acl);
}

#[test]
fn test_indexed_chunk_inherits_acl() {
    let acl = AclMetadata {
        visibility: Visibility::Private,
        owner_id: Some("user-1".to_string()),
        ..AclMetadata::default()
    };
    let chunk = IndexedChunk::new(
        ChunkId::new(),
        DocumentId::new(),
        TenantId::new(),
        "content".to_string(),
        vec![0.1, 0.2],
        0,
    ).with_acl(acl.clone());
    assert_eq!(chunk.acl, acl);
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-ingestion -- test_document_record_with_acl test_indexed_chunk_inherits`
Expected: FAIL — no `acl` field or `with_acl` method

**Step 3: Write the implementation**

Add `acl: AclMetadata` field to `DocumentRecord` (after `metadata` field, ~line 21):
```rust
    /// Access control metadata.
    #[serde(default)]
    pub acl: AclMetadata,
```

Add `acl: AclMetadata` field to `IndexedChunk` (after `metadata` field, ~line 68):
```rust
    /// Access control metadata (inherited from parent document).
    #[serde(default)]
    pub acl: AclMetadata,
```

Add `with_acl` builder method to both `impl DocumentRecord` and `impl IndexedChunk`:
```rust
    /// Set ACL metadata.
    #[must_use]
    pub fn with_acl(mut self, acl: AclMetadata) -> Self {
        self.acl = acl;
        self
    }
```

Add the necessary import at the top of the file:
```rust
use rag_types::AclMetadata;
```

Update all existing test code and the `new()` constructors to include `acl: AclMetadata::default()`.

**Step 4: Run test to verify it passes**

Run: `cd crates && cargo test -p rag-ingestion -- test_document_record test_indexed_chunk`
Expected: PASS (both new and existing tests)

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/indexing/models.rs
git commit -m "feat(rag-ingestion): add typed acl field to DocumentRecord and IndexedChunk"
```

---

### Task 4: Update worker handler to build `AclMetadata` from payload

**Files:**
- Modify: `rag-ingestion/src/worker/handler.rs:253-273` (ACL extraction in `process_ingest_single`)

**Step 1: Write the implementation**

In `process_ingest_single` (handler.rs), replace the metadata-bag ACL injection (~lines 253-273):

Before (current code):
```rust
let mut doc_metadata = Self::json_object_to_map(payload.get("metadata"));
if let Some(acl) = payload.get("acl") {
    if let Some(visibility) = acl.get("visibility") {
        doc_metadata.insert("visibility".to_string(), visibility.clone());
    }
    if let Some(allowed_groups) = acl.get("allowed_groups") {
        doc_metadata.insert("allowed_groups".to_string(), allowed_groups.clone());
    }
    if let Some(allowed_users) = acl.get("allowed_users") {
        doc_metadata.insert("allowed_users".to_string(), allowed_users.clone());
    }
}
```

After:
```rust
let doc_metadata = Self::json_object_to_map(payload.get("metadata"));

// Build typed ACL from the "acl" section of the payload
let acl_metadata = if let Some(acl) = payload.get("acl") {
    AclMetadata {
        visibility: acl
            .get("visibility")
            .and_then(|v| serde_json::from_value(v.clone()).ok())
            .unwrap_or_default(),
        owner_id: acl
            .get("owner_id")
            .and_then(|v| v.as_str())
            .map(ToString::to_string),
        allowed_groups: acl
            .get("allowed_groups")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(ToString::to_string)).collect())
            .unwrap_or_default(),
        allowed_users: acl
            .get("allowed_users")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(ToString::to_string)).collect())
            .unwrap_or_default(),
        denied_groups: acl
            .get("denied_groups")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(ToString::to_string)).collect())
            .unwrap_or_default(),
        denied_users: acl
            .get("denied_users")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(ToString::to_string)).collect())
            .unwrap_or_default(),
    }
} else {
    AclMetadata::default()
};
```

Update the `DocumentRecord` construction to use the typed `acl`:
```rust
let document = DocumentRecord {
    document_id,
    tenant_id: tenant_id_typed,
    source_id: source_id.to_string(),
    title: document_title,
    metadata: doc_metadata.clone(),
    acl: acl_metadata.clone(),
};
```

Update the `IndexedChunk` construction in the `.map()` closure to carry the ACL:
```rust
IndexedChunk {
    chunk_id: ChunkId::new(),
    document_id,
    tenant_id: tenant_id_typed,
    content: chunk.content,
    chunk_index: chunk.chunk_index,
    embedding,
    metadata,
    acl: acl_metadata.clone(),
}
```

Add import: `use rag_types::AclMetadata;`

**Step 2: Run tests to verify compilation + existing tests still pass**

Run: `cd crates && cargo test -p rag-ingestion`
Expected: PASS (all existing tests)

**Step 3: Commit**

```bash
git add crates/rag-ingestion/src/worker/handler.rs
git commit -m "feat(rag-ingestion): build typed AclMetadata from job payload in worker handler"
```

---

### Task 5: Update coordinator to use typed `acl` for all store writes

**Files:**
- Modify: `rag-ingestion/src/indexing/coordinator.rs:151-219` (write_to_qdrant), `:221-285` (write_to_opensearch), `write_to_database` (PostgreSQL)

**Step 1: Update `write_to_qdrant` (~lines 151-219)**

Replace the metadata-bag ACL extraction with typed field access. Change the payload construction in the `.map(|c| { ... })` closure:

Before:
```rust
let visibility = c.metadata.get("visibility")
    .and_then(|v| v.as_str())
    .unwrap_or("public");
let allowed_groups = c.metadata.get("allowed_groups")
    .cloned()
    .unwrap_or_else(|| json!([]));
let mut payload = json!({ ... "visibility": visibility, "allowed_groups": allowed_groups });
```

After:
```rust
let acl_fields = c.acl.to_json_value();
let mut payload = json!({
    "chunk_id": c.chunk_id.to_string(),
    "document_id": c.document_id.to_string(),
    "tenant_id": c.tenant_id.to_string(),
    "chunk_index": c.chunk_index,
    "content": c.content,
    "title": document.title,
    "source_uri": document.source_id,
});
// Merge all ACL fields as top-level payload fields
if let (Some(payload_obj), Some(acl_obj)) = (payload.as_object_mut(), acl_fields.as_object()) {
    for (key, value) in acl_obj {
        payload_obj.insert(key.clone(), value.clone());
    }
    // Merge additional non-ACL metadata
    for (key, value) in &c.metadata {
        payload_obj.insert(key.clone(), value.clone());
    }
}
```

**Step 2: Update `write_to_opensearch` (~lines 221-285)**

Same pattern — replace metadata-bag extraction with typed ACL:

```rust
let acl_fields = c.acl.to_json_value();
let mut doc = json!({
    "chunk_id": c.chunk_id.to_string(),
    "document_id": c.document_id.to_string(),
    "tenant_id": c.tenant_id.to_string(),
    "content": c.content,
    "title": document.title,
    "source_uri": document.source_id,
    "chunk_index": c.chunk_index,
    "metadata": c.metadata,
});
// Merge ACL fields at top level
if let (Some(doc_obj), Some(acl_obj)) = (doc.as_object_mut(), acl_fields.as_object()) {
    for (key, value) in acl_obj {
        doc_obj.insert(key.clone(), value.clone());
    }
}
```

**Step 3: Update `write_to_database`**

Change the `NewSourceDocument` construction to read from `document.acl` instead of `document.metadata`:

```rust
visibility: document.acl.visibility,
owner_id: document.acl.owner_id.clone(),
allowed_groups: document.acl.allowed_groups.clone(),
allowed_users: document.acl.allowed_users.clone(),
denied_groups: document.acl.denied_groups.clone(),
denied_users: document.acl.denied_users.clone(),
```

**Step 4: Run tests**

Run: `cd crates && cargo test -p rag-ingestion`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/indexing/coordinator.rs
git commit -m "feat(rag-ingestion): coordinator writes all 6 ACL fields to all stores from typed struct"
```

---

### Task 6: Add new ACL columns to PostgreSQL models and repository

**Files:**
- Modify: `rag-database/src/models/source_document.rs:8-46` (SourceDocument), `:76-89` (SourceDocumentBuilder), `:183-208` (NewSourceDocument)
- Modify: `rag-database/src/repositories/document_repository.rs:20-53` (create method)

**Step 1: Update `SourceDocument` struct**

Add after `allowed_groups` field (~line 39):
```rust
    /// Document owner user ID.
    pub owner_id: Option<String>,
    /// Individual users allowed to access.
    #[sqlx(default)]
    pub allowed_users: Vec<String>,
    /// Groups explicitly denied access.
    #[sqlx(default)]
    pub denied_groups: Vec<String>,
    /// Users explicitly denied access.
    #[sqlx(default)]
    pub denied_users: Vec<String>,
```

**Step 2: Update `NewSourceDocument` struct**

Add after `allowed_groups` field:
```rust
    /// Owner user ID.
    pub owner_id: Option<String>,
    /// Allowed users.
    pub allowed_users: Vec<String>,
    /// Denied groups.
    pub denied_groups: Vec<String>,
    /// Denied users.
    pub denied_users: Vec<String>,
```

**Step 3: Update `SourceDocumentBuilder`**

Add fields and builder methods for `owner_id`, `allowed_users`, `denied_groups`, `denied_users`.

**Step 4: Update `document_repository.rs` `create()` method**

Update the INSERT SQL to include the 4 new columns:
```sql
INSERT INTO source_documents (
    id, tenant_id, title, source_uri, source_type, mime_type,
    content_hash, file_size, visibility, allowed_groups,
    owner_id, allowed_users, denied_groups, denied_users,
    metadata, status, chunk_count
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, 'pending', 0)
RETURNING *
```

Add binds:
```rust
.bind(&doc.owner_id)       // $11
.bind(&doc.allowed_users)  // $12
.bind(&doc.denied_groups)  // $13
.bind(&doc.denied_users)   // $14
.bind(&doc.metadata)       // $15
```

**Step 5: Run tests**

Run: `cd crates && cargo test -p rag-database`
Expected: PASS (unit tests — integration tests need the migration)

**Step 6: Commit**

```bash
git add crates/rag-database/src/models/source_document.rs crates/rag-database/src/repositories/document_repository.rs
git commit -m "feat(rag-database): add owner_id, allowed_users, denied_groups, denied_users columns"
```

---

### Task 7: Add OpenSearch index mapping fields

**Files:**
- Modify: `rag-search/src/client.rs:110-154` (create_documents_index)

**Step 1: Update mappings**

In `create_documents_index()`, add after the existing `"visibility"` field mapping (~line 146):

```rust
"owner_id": { "type": "keyword" },
"allowed_users": { "type": "keyword" },
"denied_groups": { "type": "keyword" },
"denied_users": { "type": "keyword" },
```

**Step 2: Run tests**

Run: `cd crates && cargo test -p rag-search`
Expected: PASS

**Step 3: Commit**

```bash
git add crates/rag-search/src/client.rs
git commit -m "feat(rag-search): add ACL fields to OpenSearch documents index mapping"
```

---

### Task 8: Update retrieval `UserContext::can_access()` and `RetrievalResult`

**Files:**
- Modify: `rag-retrieval/src/types.rs:91-124` (can_access method), `:127-178` (RetrievalResult)
- Modify: `rag-retrieval/src/api/routes/search.rs` (post-filter retain calls)

**Step 1: Write the failing test**

Add to tests in `rag-retrieval/src/types.rs`:

```rust
#[test]
fn test_can_access_full_checks_allowed_users() {
    let ctx = UserContext::new(
        Uuid::parse_str("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa").unwrap(),
        Uuid::new_v4(),
    );
    let acl = FullAcl {
        visibility: Visibility::Private,
        owner_id: None,
        allowed_groups: vec![],
        allowed_users: vec!["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa".to_string()],
        denied_groups: vec![],
        denied_users: vec![],
    };
    assert!(ctx.can_access_full(&acl));
}

#[test]
fn test_can_access_full_denied_user() {
    let ctx = UserContext::new(
        Uuid::parse_str("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa").unwrap(),
        Uuid::new_v4(),
    );
    let acl = FullAcl {
        visibility: Visibility::Public,
        owner_id: None,
        allowed_groups: vec![],
        allowed_users: vec![],
        denied_groups: vec![],
        denied_users: vec!["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa".to_string()],
    };
    assert!(!ctx.can_access_full(&acl));
}

#[test]
fn test_can_access_full_owner() {
    let user_id = Uuid::parse_str("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa").unwrap();
    let ctx = UserContext::new(user_id, Uuid::new_v4());
    let acl = FullAcl {
        visibility: Visibility::Private,
        owner_id: Some("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa".to_string()),
        allowed_groups: vec![],
        allowed_users: vec![],
        denied_groups: vec![],
        denied_users: vec![],
    };
    assert!(ctx.can_access_full(&acl));
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-retrieval -- test_can_access_full`
Expected: FAIL — `can_access_full` and `FullAcl` not defined

**Step 3: Write the implementation**

Add a `FullAcl` struct and `can_access_full` method to `UserContext` in `rag-retrieval/src/types.rs`:

```rust
/// Full ACL fields for post-search safety-net filtering.
#[derive(Debug, Clone, Default)]
pub struct FullAcl {
    pub visibility: Visibility,
    pub owner_id: Option<String>,
    pub allowed_groups: Vec<String>,
    pub allowed_users: Vec<String>,
    pub denied_groups: Vec<String>,
    pub denied_users: Vec<String>,
}

impl UserContext {
    /// Full ACL check including owner, allowed_users, and deny lists.
    #[must_use]
    pub fn can_access_full(&self, acl: &FullAcl) -> bool {
        if self.is_admin {
            return true;
        }

        // Deny lists take precedence
        let user_id_str = self.user_id.to_string();
        if acl.denied_users.iter().any(|u| u == &user_id_str) {
            return false;
        }
        if acl.denied_groups.iter().any(|dg| self.groups.contains(dg)) {
            return false;
        }

        match acl.visibility {
            Visibility::Public | Visibility::Tenant => true,
            Visibility::Private => {
                // Owner check
                acl.owner_id.as_deref() == Some(&user_id_str)
                    || acl.allowed_users.iter().any(|u| u == &user_id_str)
            }
            Visibility::Group => {
                self.groups.iter().any(|g| acl.allowed_groups.contains(g))
                    || acl.allowed_users.iter().any(|u| u == &user_id_str)
                    || acl.owner_id.as_deref() == Some(&user_id_str)
            }
        }
    }
}
```

Add `owner_id`, `allowed_users`, `denied_groups`, `denied_users` fields to `RetrievalResult`:
```rust
    // ACL fields
    #[serde(default)]
    pub visibility: Visibility,
    #[serde(default)]
    pub owner_id: Option<String>,
    #[serde(default)]
    pub allowed_groups: Vec<String>,
    #[serde(default)]
    pub allowed_users: Vec<String>,
    #[serde(default)]
    pub denied_groups: Vec<String>,
    #[serde(default)]
    pub denied_users: Vec<String>,
```

Update the post-filter `retain` calls in `search.rs` to use `can_access_full`:
```rust
results.retain(|r| user_context.can_access_full(&FullAcl {
    visibility: r.visibility,
    owner_id: r.owner_id.clone(),
    allowed_groups: r.allowed_groups.clone(),
    allowed_users: r.allowed_users.clone(),
    denied_groups: r.denied_groups.clone(),
    denied_users: r.denied_users.clone(),
}));
```

**Step 4: Run tests**

Run: `cd crates && cargo test -p rag-retrieval`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-retrieval/src/types.rs crates/rag-retrieval/src/api/routes/search.rs
git commit -m "feat(rag-retrieval): add full ACL post-filter with owner, allowed_users, deny lists"
```

---

### Task 9: Create Alembic migration for new PostgreSQL columns

**Files:**
- Create: `services/orchestrator/shared/database/migrations/versions/015_add_acl_columns.py`

**Step 1: Write the migration**

```python
"""Add owner_id, allowed_users, denied_groups, denied_users to source_documents.

Revision ID: 015
Revises: 014
"""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"


def upgrade():
    op.add_column("source_documents", sa.Column("owner_id", sa.Text(), nullable=True))
    op.add_column("source_documents", sa.Column("allowed_users", sa.ARRAY(sa.Text()), server_default="{}"))
    op.add_column("source_documents", sa.Column("denied_groups", sa.ARRAY(sa.Text()), server_default="{}"))
    op.add_column("source_documents", sa.Column("denied_users", sa.ARRAY(sa.Text()), server_default="{}"))


def downgrade():
    op.drop_column("source_documents", "denied_users")
    op.drop_column("source_documents", "denied_groups")
    op.drop_column("source_documents", "allowed_users")
    op.drop_column("source_documents", "owner_id")
```

**Step 2: Commit**

```bash
git add services/orchestrator/shared/database/migrations/versions/015_add_acl_columns.py
git commit -m "feat(database): add migration for ACL columns on source_documents"
```

---

### Task 10: Run full test suite and cross off gap analysis item

**Step 1: Run workspace tests**

Run: `cd crates && cargo test --workspace`
Expected: All tests PASS

**Step 2: Run clippy**

Run: `cd crates && cargo clippy --workspace -- -D warnings`
Expected: No warnings

**Step 3: Run fmt check**

Run: `cd crates && cargo fmt --all -- --check`
Expected: No formatting issues

**Step 4: Update gap analysis document**

In `.workflow/ideas/repo-gap-risk-pipeline-analysis-2026-03-02.md`, mark the item as fixed:
```
1. ~~Unify ACL behavior across PostgreSQL, Qdrant, and OpenSearch payloads.~~ **FIXED**
```

**Step 5: Final commit**

```bash
git add .workflow/ideas/repo-gap-risk-pipeline-analysis-2026-03-02.md
git commit -m "docs: mark unified ACL as fixed in gap analysis"
```
