//! Document parsers for various file formats.
//!
//! This module provides parsers for:
//! - HTML documents ([`HtmlParser`])
//! - Markdown documents ([`MarkdownParser`])

mod base;

pub use base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
