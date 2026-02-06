//! Shared utility functions for the retrieval service.

/// Normalize a query string for consistent hashing and comparison.
///
/// This function:
/// - Trims leading and trailing whitespace
/// - Converts to lowercase
/// - Collapses multiple spaces into a single space
///
/// # Examples
///
/// ```
/// use rag_retrieval::utils::normalize_query;
///
/// assert_eq!(normalize_query("  HELLO   world  "), "hello world");
/// assert_eq!(normalize_query("Already Normal"), "already normal");
/// ```
pub fn normalize_query(query: &str) -> String {
    query
        .trim()
        .to_lowercase()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_query_trims_whitespace() {
        assert_eq!(normalize_query("  hello  "), "hello");
    }

    #[test]
    fn test_normalize_query_lowercases() {
        assert_eq!(normalize_query("HELLO World"), "hello world");
    }

    #[test]
    fn test_normalize_query_collapses_spaces() {
        assert_eq!(normalize_query("hello    world"), "hello world");
    }

    #[test]
    fn test_normalize_query_combined() {
        assert_eq!(normalize_query("  HELLO   world  "), "hello world");
    }

    #[test]
    fn test_normalize_query_already_normalized() {
        assert_eq!(normalize_query("hello world"), "hello world");
    }

    #[test]
    fn test_normalize_query_empty() {
        assert_eq!(normalize_query(""), "");
        assert_eq!(normalize_query("   "), "");
    }
}
