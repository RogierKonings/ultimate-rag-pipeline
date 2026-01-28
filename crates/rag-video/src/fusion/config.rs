//! Configuration for content fusion operations.

/// Configuration for the content fusion service.
#[derive(Debug, Clone)]
pub struct FusionConfig {
    /// Target chunk duration in milliseconds.
    pub target_chunk_duration_ms: u64,
    /// Minimum chunk duration in milliseconds.
    pub min_chunk_duration_ms: u64,
    /// Maximum chunk duration in milliseconds.
    pub max_chunk_duration_ms: u64,
    /// Overlap between chunks in milliseconds.
    pub overlap_ms: u64,
    /// Whether to include modality labels (e.g., [Speech], [Visual]) in fused text.
    pub include_modality_labels: bool,
    /// Separator between modalities in fused text.
    pub separator: String,
}

impl Default for FusionConfig {
    fn default() -> Self {
        Self {
            target_chunk_duration_ms: 20_000,
            min_chunk_duration_ms: 10_000,
            max_chunk_duration_ms: 30_000,
            overlap_ms: 2_000,
            include_modality_labels: true,
            separator: "\n\n".to_string(),
        }
    }
}

impl FusionConfig {
    /// Creates a new configuration with default values.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Sets the target chunk duration.
    #[must_use]
    pub const fn with_target_duration_ms(mut self, duration_ms: u64) -> Self {
        self.target_chunk_duration_ms = duration_ms;
        self
    }

    /// Sets the minimum chunk duration.
    #[must_use]
    pub const fn with_min_duration_ms(mut self, duration_ms: u64) -> Self {
        self.min_chunk_duration_ms = duration_ms;
        self
    }

    /// Sets the maximum chunk duration.
    #[must_use]
    pub const fn with_max_duration_ms(mut self, duration_ms: u64) -> Self {
        self.max_chunk_duration_ms = duration_ms;
        self
    }

    /// Sets the overlap between chunks.
    #[must_use]
    pub const fn with_overlap_ms(mut self, overlap_ms: u64) -> Self {
        self.overlap_ms = overlap_ms;
        self
    }

    /// Sets whether to include modality labels.
    #[must_use]
    pub const fn with_modality_labels(mut self, include: bool) -> Self {
        self.include_modality_labels = include;
        self
    }

    /// Sets the separator between modalities.
    #[must_use]
    pub fn with_separator(mut self, separator: impl Into<String>) -> Self {
        self.separator = separator.into();
        self
    }

    /// Validates the configuration.
    ///
    /// # Returns
    ///
    /// Returns `Ok(())` if the configuration is valid, otherwise returns an error message.
    pub fn validate(&self) -> Result<(), String> {
        if self.min_chunk_duration_ms > self.max_chunk_duration_ms {
            return Err(format!(
                "min_chunk_duration_ms ({}) cannot be greater than max_chunk_duration_ms ({})",
                self.min_chunk_duration_ms, self.max_chunk_duration_ms
            ));
        }

        if self.target_chunk_duration_ms < self.min_chunk_duration_ms {
            return Err(format!(
                "target_chunk_duration_ms ({}) cannot be less than min_chunk_duration_ms ({})",
                self.target_chunk_duration_ms, self.min_chunk_duration_ms
            ));
        }

        if self.target_chunk_duration_ms > self.max_chunk_duration_ms {
            return Err(format!(
                "target_chunk_duration_ms ({}) cannot be greater than max_chunk_duration_ms ({})",
                self.target_chunk_duration_ms, self.max_chunk_duration_ms
            ));
        }

        if self.overlap_ms >= self.min_chunk_duration_ms {
            return Err(format!(
                "overlap_ms ({}) must be less than min_chunk_duration_ms ({})",
                self.overlap_ms, self.min_chunk_duration_ms
            ));
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fusion_config_default() {
        let config = FusionConfig::default();
        assert_eq!(config.target_chunk_duration_ms, 20_000);
        assert_eq!(config.min_chunk_duration_ms, 10_000);
        assert_eq!(config.max_chunk_duration_ms, 30_000);
        assert_eq!(config.overlap_ms, 2_000);
        assert!(config.include_modality_labels);
        assert_eq!(config.separator, "\n\n");
    }

    #[test]
    fn test_fusion_config_new() {
        let config = FusionConfig::new();
        assert_eq!(config.target_chunk_duration_ms, 20_000);
    }

    #[test]
    fn test_fusion_config_builder() {
        let config = FusionConfig::new()
            .with_target_duration_ms(15_000)
            .with_min_duration_ms(5_000)
            .with_max_duration_ms(25_000)
            .with_overlap_ms(1_000)
            .with_modality_labels(false)
            .with_separator(" | ");

        assert_eq!(config.target_chunk_duration_ms, 15_000);
        assert_eq!(config.min_chunk_duration_ms, 5_000);
        assert_eq!(config.max_chunk_duration_ms, 25_000);
        assert_eq!(config.overlap_ms, 1_000);
        assert!(!config.include_modality_labels);
        assert_eq!(config.separator, " | ");
    }

    #[test]
    fn test_fusion_config_validate_success() {
        let config = FusionConfig::default();
        assert!(config.validate().is_ok());
    }

    #[test]
    fn test_fusion_config_validate_min_greater_than_max() {
        let config = FusionConfig::new()
            .with_min_duration_ms(30_000)
            .with_max_duration_ms(10_000);

        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("min_chunk_duration_ms"));
    }

    #[test]
    fn test_fusion_config_validate_target_less_than_min() {
        let config = FusionConfig::new()
            .with_target_duration_ms(5_000)
            .with_min_duration_ms(10_000);

        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("target_chunk_duration_ms"));
    }

    #[test]
    fn test_fusion_config_validate_target_greater_than_max() {
        let config = FusionConfig::new()
            .with_target_duration_ms(35_000)
            .with_max_duration_ms(30_000);

        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("target_chunk_duration_ms"));
    }

    #[test]
    fn test_fusion_config_validate_overlap_too_large() {
        let config = FusionConfig::new()
            .with_overlap_ms(15_000)
            .with_min_duration_ms(10_000);

        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("overlap_ms"));
    }

    #[test]
    fn test_fusion_config_clone() {
        let config = FusionConfig::default();
        let cloned = config.clone();
        assert_eq!(config.target_chunk_duration_ms, cloned.target_chunk_duration_ms);
        assert_eq!(config.separator, cloned.separator);
    }

    #[test]
    fn test_fusion_config_debug() {
        let config = FusionConfig::default();
        let debug = format!("{config:?}");
        assert!(debug.contains("FusionConfig"));
        assert!(debug.contains("target_chunk_duration_ms"));
    }
}
