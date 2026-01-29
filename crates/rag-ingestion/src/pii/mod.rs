//! PII (Personally Identifiable Information) detection.
//!
//! This module provides regex-based PII detection for common patterns
//! like email addresses, phone numbers, SSNs, credit cards, etc.
//!
//! # Example
//!
//! ```
//! use rag_ingestion::pii::{PIIDetector, PIIType};
//!
//! let detector = PIIDetector::new();
//! let text = "Contact me at john@example.com";
//! let result = detector.detect(text);
//!
//! assert!(result.has_pii);
//! assert!(result.entity_counts.contains_key(&PIIType::EmailAddress));
//! ```

mod detector;
mod patterns;

pub use detector::{PIIDetector, PIIDetectorConfig, PIIEntity, PIIResult, PIIType};
