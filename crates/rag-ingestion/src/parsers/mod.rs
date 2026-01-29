//! Document parsers for various file formats.
//!
//! This module provides parsers for:
//! - HTML documents ([`HtmlParser`])
//! - Markdown documents ([`MarkdownParser`])
//! - PDF documents ([`PdfParser`])
//! - DOCX documents ([`DocxParser`])

mod base;
mod docx;
mod html;
mod markdown;
mod pdf;

pub use base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
pub use docx::{DocxParser, DocxParserConfig};
pub use html::{HtmlParser, HtmlParserConfig};
pub use markdown::MarkdownParser;
pub use pdf::{PdfParser, PdfParserConfig};
