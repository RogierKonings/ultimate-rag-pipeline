//! Custom tracing layers.

use tracing::{span, Subscriber};
use tracing_subscriber::{layer::Context, registry::LookupSpan, Layer};

/// Layer that adds request ID to spans.
pub struct RequestIdLayer;

impl<S> Layer<S> for RequestIdLayer
where
    S: Subscriber + for<'a> LookupSpan<'a>,
{
    fn on_new_span(&self, attrs: &span::Attributes<'_>, id: &span::Id, ctx: Context<'_, S>) {
        // If there's a request_id field, store it
        if let Some(span) = ctx.span(id) {
            let mut visitor = RequestIdVisitor::default();
            attrs.record(&mut visitor);
            if let Some(request_id) = visitor.request_id {
                span.extensions_mut().insert(RequestId(request_id));
            }
        }
    }
}

#[derive(Default)]
struct RequestIdVisitor {
    request_id: Option<String>,
}

impl tracing::field::Visit for RequestIdVisitor {
    fn record_str(&mut self, field: &tracing::field::Field, value: &str) {
        if field.name() == "request_id" {
            self.request_id = Some(value.to_string());
        }
    }

    fn record_debug(&mut self, _field: &tracing::field::Field, _value: &dyn std::fmt::Debug) {}
}

/// Stored request ID in span extensions.
#[derive(Debug, Clone)]
#[allow(dead_code)] // Used via span extensions
pub struct RequestId(pub String);

/// Create a request ID layer.
#[must_use]
pub fn request_id_layer<S>() -> RequestIdLayer
where
    S: Subscriber + for<'a> LookupSpan<'a>,
{
    RequestIdLayer
}

/// Generate a new request ID.
#[must_use]
#[allow(dead_code)] // Used by consuming crates
pub fn generate_request_id() -> String {
    uuid::Uuid::new_v4().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_generate_request_id() {
        let id1 = generate_request_id();
        let id2 = generate_request_id();

        assert_ne!(id1, id2);
        assert_eq!(id1.len(), 36); // UUID format
    }
}
