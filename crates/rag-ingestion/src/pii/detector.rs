//! PII detection using regex patterns.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use super::patterns;

/// Types of PII that can be detected.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PIIType {
    EmailAddress,
    PhoneNumber,
    SocialSecurityNumber,
    CreditCard,
    IpAddress,
    Date,
    PassportNumber,
    BankAccount,
    DriversLicense,
    MedicalRecord,
}

impl PIIType {
    /// Get all PII types.
    #[must_use]
    pub fn all() -> &'static [Self] {
        &[
            Self::EmailAddress,
            Self::PhoneNumber,
            Self::SocialSecurityNumber,
            Self::CreditCard,
            Self::IpAddress,
            Self::Date,
            Self::PassportNumber,
            Self::BankAccount,
            Self::DriversLicense,
            Self::MedicalRecord,
        ]
    }

    /// Get high-sensitivity PII types.
    #[must_use]
    pub fn high_sensitivity() -> &'static [Self] {
        &[
            Self::SocialSecurityNumber,
            Self::CreditCard,
            Self::BankAccount,
            Self::MedicalRecord,
        ]
    }

    /// Check if this is a high-sensitivity type.
    #[must_use]
    pub fn is_high_sensitivity(&self) -> bool {
        matches!(
            self,
            Self::SocialSecurityNumber | Self::CreditCard | Self::BankAccount | Self::MedicalRecord
        )
    }

    /// Get placeholder text for redaction.
    #[must_use]
    pub fn placeholder(&self) -> &'static str {
        match self {
            Self::EmailAddress => "[EMAIL_ADDRESS]",
            Self::PhoneNumber => "[PHONE_NUMBER]",
            Self::SocialSecurityNumber => "[SSN]",
            Self::CreditCard => "[CREDIT_CARD]",
            Self::IpAddress => "[IP_ADDRESS]",
            Self::Date => "[DATE]",
            Self::PassportNumber => "[PASSPORT]",
            Self::BankAccount => "[BANK_ACCOUNT]",
            Self::DriversLicense => "[DRIVERS_LICENSE]",
            Self::MedicalRecord => "[MEDICAL_RECORD]",
        }
    }
}

/// A detected PII entity.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PIIEntity {
    /// Type of PII.
    pub entity_type: PIIType,
    /// The matched text.
    pub text: String,
    /// Start position in source text.
    pub start: usize,
    /// End position in source text.
    pub end: usize,
    /// Confidence score (1.0 for regex matches).
    pub score: f64,
}

/// Result of PII detection.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PIIResult {
    /// Detected entities.
    pub entities: Vec<PIIEntity>,
    /// Count by entity type.
    pub entity_counts: HashMap<PIIType, usize>,
    /// Whether any PII was found.
    pub has_pii: bool,
    /// Whether high-sensitivity PII was found.
    pub high_sensitivity: bool,
}

/// Configuration for PII detection.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PIIDetectorConfig {
    /// Entity types to detect.
    pub entities_to_detect: Vec<PIIType>,
    /// Minimum score threshold (for future NER support).
    pub score_threshold: f64,
}

impl Default for PIIDetectorConfig {
    fn default() -> Self {
        Self {
            entities_to_detect: PIIType::all().to_vec(),
            score_threshold: 0.5,
        }
    }
}

/// PII detector using regex patterns.
pub struct PIIDetector {
    config: PIIDetectorConfig,
}

impl PIIDetector {
    /// Create a new PII detector with default configuration.
    #[must_use]
    pub fn new() -> Self {
        Self::with_config(PIIDetectorConfig::default())
    }

    /// Create a new PII detector with custom configuration.
    #[must_use]
    pub fn with_config(config: PIIDetectorConfig) -> Self {
        Self { config }
    }

    /// Detect PII entities in text.
    pub fn detect(&self, text: &str) -> PIIResult {
        let mut entities = Vec::new();
        let mut entity_counts: HashMap<PIIType, usize> = HashMap::new();
        let mut has_high_sensitivity = false;

        for pii_type in &self.config.entities_to_detect {
            let matches = self.find_matches(text, *pii_type);
            for m in matches {
                entity_counts
                    .entry(*pii_type)
                    .and_modify(|c| *c += 1)
                    .or_insert(1);

                if pii_type.is_high_sensitivity() {
                    has_high_sensitivity = true;
                }

                entities.push(m);
            }
        }

        PIIResult {
            has_pii: !entities.is_empty(),
            high_sensitivity: has_high_sensitivity,
            entities,
            entity_counts,
        }
    }

    /// Redact PII from text.
    pub fn redact(&self, text: &str) -> String {
        let result = self.detect(text);
        if result.entities.is_empty() {
            return text.to_string();
        }

        // Sort by position descending to replace from end
        let mut sorted_entities = result.entities;
        sorted_entities.sort_by(|a, b| b.start.cmp(&a.start));

        let mut redacted = text.to_string();
        for entity in sorted_entities {
            let placeholder = entity.entity_type.placeholder();
            redacted.replace_range(entity.start..entity.end, placeholder);
        }

        redacted
    }

    /// Find all matches for a specific PII type.
    #[allow(clippy::unused_self)] // kept as method for future extensibility with detector config
    fn find_matches(&self, text: &str, pii_type: PIIType) -> Vec<PIIEntity> {
        let regex = match pii_type {
            PIIType::EmailAddress => &*patterns::EMAIL,
            PIIType::PhoneNumber => &*patterns::PHONE_US,
            PIIType::SocialSecurityNumber => &*patterns::SSN,
            PIIType::CreditCard => &*patterns::CREDIT_CARD,
            PIIType::IpAddress => &*patterns::IP_ADDRESS,
            PIIType::Date => &*patterns::DATE,
            PIIType::PassportNumber => &*patterns::PASSPORT_US,
            PIIType::BankAccount => &*patterns::BANK_ACCOUNT,
            PIIType::DriversLicense => &*patterns::DRIVERS_LICENSE,
            PIIType::MedicalRecord => &*patterns::MEDICAL_RECORD,
        };

        regex
            .find_iter(text)
            .map(|m| PIIEntity {
                entity_type: pii_type,
                text: m.as_str().to_string(),
                start: m.start(),
                end: m.end(),
                score: 1.0, // Regex matches are deterministic
            })
            .collect()
    }
}

impl Default for PIIDetector {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pii_detector_config_default() {
        let config = PIIDetectorConfig::default();
        assert_eq!(config.entities_to_detect.len(), PIIType::all().len());
    }

    #[test]
    fn test_detect_email() {
        let detector = PIIDetector::new();
        let text = "Contact me at john.doe@example.com for more info.";
        let result = detector.detect(text);

        assert!(result.has_pii);
        assert_eq!(result.entity_counts.get(&PIIType::EmailAddress), Some(&1));
        assert!(result
            .entities
            .iter()
            .any(|e| e.text == "john.doe@example.com"));
    }

    #[test]
    fn test_detect_phone() {
        let detector = PIIDetector::new();
        let text = "Call me at (555) 123-4567.";
        let result = detector.detect(text);

        assert!(result.has_pii);
        assert!(result.entity_counts.contains_key(&PIIType::PhoneNumber));
    }

    #[test]
    fn test_detect_ssn() {
        let detector = PIIDetector::new();
        let text = "SSN: 123-45-6789";
        let result = detector.detect(text);

        assert!(result.has_pii);
        assert!(result.high_sensitivity);
        assert!(result
            .entity_counts
            .contains_key(&PIIType::SocialSecurityNumber));
    }

    #[test]
    fn test_detect_credit_card() {
        let detector = PIIDetector::new();
        let text = "Card number: 4111111111111111";
        let result = detector.detect(text);

        assert!(result.has_pii);
        assert!(result.high_sensitivity);
        assert!(result.entity_counts.contains_key(&PIIType::CreditCard));
    }

    #[test]
    fn test_detect_multiple() {
        let detector = PIIDetector::new();
        let text = "Email: test@example.com, Phone: 555-123-4567, SSN: 123-45-6789";
        let result = detector.detect(text);

        assert!(result.has_pii);
        assert!(result.high_sensitivity);
        assert!(result.entities.len() >= 3);
    }

    #[test]
    fn test_no_pii() {
        let detector = PIIDetector::new();
        let text = "This is a normal text without any personal information.";
        let result = detector.detect(text);

        assert!(!result.has_pii);
        assert!(!result.high_sensitivity);
        assert!(result.entities.is_empty());
    }

    #[test]
    fn test_redact() {
        let detector = PIIDetector::new();
        let text = "Contact john@example.com or call 555-123-4567";
        let redacted = detector.redact(text);

        assert!(redacted.contains("[EMAIL_ADDRESS]"));
        assert!(redacted.contains("[PHONE_NUMBER]"));
        assert!(!redacted.contains("john@example.com"));
        assert!(!redacted.contains("555-123-4567"));
    }

    #[test]
    fn test_redact_no_pii() {
        let detector = PIIDetector::new();
        let text = "Normal text here";
        let redacted = detector.redact(text);

        assert_eq!(redacted, text);
    }

    #[test]
    fn test_selective_detection() {
        let config = PIIDetectorConfig {
            entities_to_detect: vec![PIIType::EmailAddress],
            score_threshold: 0.5,
        };
        let detector = PIIDetector::with_config(config);

        let text = "Email: test@example.com, Phone: 555-123-4567";
        let result = detector.detect(text);

        assert!(result.has_pii);
        assert_eq!(result.entities.len(), 1);
        assert_eq!(result.entities[0].entity_type, PIIType::EmailAddress);
    }

    #[test]
    fn test_pii_type_is_high_sensitivity() {
        assert!(PIIType::SocialSecurityNumber.is_high_sensitivity());
        assert!(PIIType::CreditCard.is_high_sensitivity());
        assert!(PIIType::BankAccount.is_high_sensitivity());
        assert!(PIIType::MedicalRecord.is_high_sensitivity());
        assert!(!PIIType::EmailAddress.is_high_sensitivity());
        assert!(!PIIType::PhoneNumber.is_high_sensitivity());
    }
}
