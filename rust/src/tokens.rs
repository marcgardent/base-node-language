use serde::{Deserialize, Serialize};

pub const KEYWORDS: &[&str] = &[
    "graph", "return", "true", "false", "and", "or", "xor", "not",
];

/// The numbers written as words: floats no digits write.
pub const WORD_NUMBERS: &[&str] = &["inf", "nan"];

pub const PUNCT: &[&str] = &[
    "::", "|>", "|", "->", "<=", ">=", "==", "!=", "<", ">", "(", ")", "[", "]", "{", "}", ",",
    ":", "..", ".", "=", "+", "-", "*", "/", "⋅", "·", "×", "@", "?",
];

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum TokenKind {
    Ident,
    Keyword,
    Number,
    String,
    OpenString,
    Color,
    Comment,
    Punct(String),
    Eof,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Token {
    pub kind: TokenKind,
    /// Of a string, its value: the escapes read.
    pub text: String,
    pub line: usize,
    pub col: usize,
    /// The characters of the source it takes: a string's quotes and escapes too.
    pub width: usize,
}

impl Token {
    pub fn new(
        kind: TokenKind,
        text: impl Into<String>,
        line: usize,
        col: usize,
        width: usize,
    ) -> Self {
        Self {
            kind,
            text: text.into(),
            line,
            col,
            width,
        }
    }

    /// A word the language keeps, never a name: a keyword, or `inf` and `nan`, which are numbers.
    pub fn is_reserved(&self) -> bool {
        match self.kind {
            TokenKind::Keyword => true,
            TokenKind::Number => WORD_NUMBERS.contains(&self.text.as_str()),
            _ => false,
        }
    }

    pub fn is(&self, kind_or_punct: &str) -> bool {
        match &self.kind {
            TokenKind::Ident => kind_or_punct == "IDENT",
            TokenKind::Keyword => kind_or_punct == "KEYWORD",
            TokenKind::Number => kind_or_punct == "NUMBER",
            TokenKind::String => kind_or_punct == "STRING",
            TokenKind::OpenString => kind_or_punct == "OPEN_STRING",
            TokenKind::Color => kind_or_punct == "COLOR",
            TokenKind::Comment => kind_or_punct == "COMMENT",
            TokenKind::Eof => kind_or_punct == "EOF",
            TokenKind::Punct(p) => p == kind_or_punct,
        }
    }

    pub fn is_with_text(&self, kind_or_punct: &str, text: &str) -> bool {
        self.is(kind_or_punct) && self.text == text
    }

    pub fn kind_str(&self) -> &str {
        match &self.kind {
            TokenKind::Ident => "IDENT",
            TokenKind::Keyword => "KEYWORD",
            TokenKind::Number => "NUMBER",
            TokenKind::String => "STRING",
            TokenKind::OpenString => "OPEN_STRING",
            TokenKind::Color => "COLOR",
            TokenKind::Comment => "COMMENT",
            TokenKind::Eof => "EOF",
            TokenKind::Punct(p) => p.as_str(),
        }
    }

    pub fn describe(&self) -> String {
        match &self.kind {
            TokenKind::Eof => "end of file".to_string(),
            _ => format!("'{}'", self.text),
        }
    }
}
