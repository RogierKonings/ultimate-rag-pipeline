// API Types matching backend schemas
//
// Source of truth: services/orchestrator/api/models/ (Pydantic models)
// Generated reference: frontend/src/lib/api/generated-types.ts
//
// To regenerate the reference types from backend models:
//   ./scripts/generate-api-types.sh
// To check for contract drift:
//   ./scripts/check-api-contracts.sh

export * from './contracts/documents';
export * from './contracts/ingestion';
export * from './contracts/query';
export * from './contracts/video';
export * from './contracts/errors';
export * from './contracts/capabilities';
