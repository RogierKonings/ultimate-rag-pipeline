//! Document parsers for various file formats.
//!
//! This module provides parsers for:
//! - HTML documents ([`HtmlParser`])
//! - Markdown documents ([`MarkdownParser`])

mod base;
mod html;

pub use base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
pub use html::{HtmlParser, HtmlParserConfig};
