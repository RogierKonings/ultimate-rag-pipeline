//! Regex patterns for PII detection.
#![allow(clippy::non_std_lazy_statics)] // lazy_static is used for consistency across the codebase

use lazy_static::lazy_static;
use regex::Regex;

lazy_static! {
    /// Email address pattern.
    pub static ref EMAIL: Regex = Regex::new(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    ).expect("Invalid email regex");

    /// US Phone number patterns (various formats).
    pub static ref PHONE_US: Regex = Regex::new(
        r"(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}"
    ).expect("Invalid phone regex");

    /// Social Security Number (US).
    pub static ref SSN: Regex = Regex::new(
        r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"
    ).expect("Invalid SSN regex");

    /// Credit card numbers (major types).
    pub static ref CREDIT_CARD: Regex = Regex::new(
        r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b"
    ).expect("Invalid credit card regex");

    /// IP addresses (IPv4).
    pub static ref IP_ADDRESS: Regex = Regex::new(
        r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
    ).expect("Invalid IP address regex");

    /// Date patterns (various formats).
    pub static ref DATE: Regex = Regex::new(
        r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})\b"
    ).expect("Invalid date regex");

    /// US Passport number.
    pub static ref PASSPORT_US: Regex = Regex::new(
        r"\b[A-Z]{1,2}[0-9]{6,9}\b"
    ).expect("Invalid passport regex");

    /// Bank account (generic - routing + account).
    pub static ref BANK_ACCOUNT: Regex = Regex::new(
        r"\b[0-9]{8,17}\b"
    ).expect("Invalid bank account regex");

    /// Driver's license (US - generic pattern).
    pub static ref DRIVERS_LICENSE: Regex = Regex::new(
        r"\b[A-Z]{1,2}[0-9]{5,8}\b"
    ).expect("Invalid drivers license regex");

    /// Medical record number (generic).
    pub static ref MEDICAL_RECORD: Regex = Regex::new(
        r"\b(?:MRN|MR#?|Medical Record)[:\s]?[A-Z0-9]{6,12}\b"
    ).expect("Invalid medical record regex");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_email_pattern() {
        assert!(EMAIL.is_match("test@example.com"));
        assert!(EMAIL.is_match("user.name+tag@domain.co.uk"));
        assert!(!EMAIL.is_match("not-an-email"));
    }

    #[test]
    fn test_phone_pattern() {
        assert!(PHONE_US.is_match("(555) 123-4567"));
        assert!(PHONE_US.is_match("555-123-4567"));
        assert!(PHONE_US.is_match("+1 555 123 4567"));
        assert!(!PHONE_US.is_match("12345"));
    }

    #[test]
    fn test_ssn_pattern() {
        assert!(SSN.is_match("123-45-6789"));
        assert!(SSN.is_match("123 45 6789"));
        assert!(SSN.is_match("123456789"));
    }

    #[test]
    fn test_credit_card_pattern() {
        // Visa
        assert!(CREDIT_CARD.is_match("4111111111111111"));
        // Mastercard
        assert!(CREDIT_CARD.is_match("5500000000000004"));
        // Amex
        assert!(CREDIT_CARD.is_match("340000000000009"));
    }

    #[test]
    fn test_ip_address_pattern() {
        assert!(IP_ADDRESS.is_match("192.168.1.1"));
        assert!(IP_ADDRESS.is_match("10.0.0.255"));
        assert!(!IP_ADDRESS.is_match("999.999.999.999"));
    }
}
